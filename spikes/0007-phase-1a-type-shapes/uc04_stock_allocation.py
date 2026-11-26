"""Use case 4 (spike 0002) in the spike 0007 shapes - stock allocation. Requirements R4.1-R4.5.

Changed from spike 0002: the stock rows are declared - `Load.after` returns the variants of the
order's items as a list of refs and loads each with its stocks and their warehouse (#59 points 1
and 3: load arguments, a nested path) - so the caller no longer pre-reads them and the stale-list
check is gone. Allocation rows are written with `insert` (#60 point 4: `Item.allocations` is not
owned, so `Order.items.update(item, Item.allocations.add(...))` is no longer a form).
Not covered: `lock="for_update"` on a `Load.after` (no `lock=` argument; #64 decides `lock=`).
"""

from collections import defaultdict
from collections.abc import Sequence
from typing import Annotated
from uuid import UUID

import pytest
from domain import Allocation, InsufficientStock, Item, Order, Stock, Variant, Warehouse, orders
from lib import INJECTED, Add, App, Changes, Id, Load, insert, usecase

app = App(dsn="postgresql://app@primary/shop")


def variants_of(order: Order) -> list[Variant]:  # R4.1: one statement for the list (3.1)
    return [Variant.ref(i.variant_id) for i in order.items]


variants_with_stock = Load.after(variants_of, Variant.stocks.load(Stock.warehouse))
type OrderWithItems = Annotated[Order, orders.with_items]
type VariantsWithStock = Annotated[Sequence[Variant], variants_with_stock]


@usecase
def allocate(order: OrderWithItems, variants: VariantsWithStock = INJECTED) -> Changes:
    by_variant = {v.id: v for v in variants}
    tracked = [i for i in order.items if by_variant[i.variant_id].track_inventory]  # R4.1
    planned: dict[Id[Stock], int] = defaultdict(int)
    parts: list[tuple[Item, Stock, int]] = []
    short: list[Id[Item]] = []
    for item in tracked:
        stocks = [
            s
            for s in by_variant[item.variant_id].stocks
            if s.warehouse.group == order.warehouse_group
        ]
        stocks.sort(key=lambda s: s.quantity - s.allocated - planned[s.id], reverse=True)  # R4.2
        left, mine = item.quantity, list[tuple[Item, Stock, int]]()
        for stock in stocks:
            take = min(stock.quantity - stock.allocated - planned[stock.id], left)
            if take > 0:
                mine.append((item, stock, take))
                left -= take
        if left > 0:  # R4.4
            short.append(item.id)
            continue
        for _, stock, take in mine:
            planned[stock.id] += take
        parts += mine
    if short:
        raise InsufficientStock(short)
    changes = Changes()
    for item, stock, take in parts:  # R4.3: allocation rows are not owned: written directly
        changes += insert(Allocation(item_id=item.id, stock_id=stock.id, quantity=take))
    by_stock_id = {s.id: s for v in variants for s in v.stocks}
    for stock_id, qty in planned.items():
        changes += by_stock_id[stock_id].set(Stock.allocated.add(qty))
    return changes


# --------------------------------------------------------------------------- call site
async def post_allocate(order_id: UUID) -> None:
    await app.run(allocate.bind(order=Order.ref(order_id)))  # no pre-read of the variants


# --------------------------------------------------------------------------- 4.12 unit tests
def test_item_is_split_over_two_warehouses() -> None:
    w = Warehouse.stub(group="default")
    a = Stock.stub(quantity=3, allocated=0, warehouse=w)
    b = Stock.stub(quantity=10, allocated=8, warehouse=w)
    variant = Variant.stub(track_inventory=True, stocks=[a, b])
    order = Order.stub(
        items=[Item.stub(variant_id=variant.id, quantity=4)], warehouse_group="default"
    )
    r = allocate(order, [variant])
    assert r.updated(a)[Stock.allocated] == Add(3)
    assert r.updated(b)[Stock.allocated] == Add(1)
    assert sorted(x.quantity for x in r.inserted(Allocation)) == [1, 3]


def test_short_items_are_all_reported() -> None:
    variant = Variant.stub(track_inventory=True, stocks=[])
    with pytest.raises(InsufficientStock):
        allocate(Order.stub(items=[Item.stub(variant_id=variant.id, quantity=1)]), [variant])
