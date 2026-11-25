"""Use case 4 - stock allocation (hot rows, pessimistic lock profile). Requirements R4.1-R4.5.

Source: saleor/saleor `warehouse/management.py` `allocate_stocks`, `_create_allocations`;
`warehouse/lock_objects.py`. Rules restated, no code copied.
"""

from collections import defaultdict
from typing import Annotated
from uuid import UUID

import pytest
from domain import (
    Allocation,
    InsufficientStock,
    Item,
    Order,
    Stock,
    Variant,
    Warehouse,
    orders,
)
from lib import Add, App, Changes, Finder, Id, Load, Profile, Repository, usecase

app = App(dsn="postgresql://app@primary/shop")


# --- What the rule needs: "the stock rows of each item's variant in the order's warehouses",
# a set of rows chosen by a predicate over values loaded in stage 1 (R4.1).
# (a) A Finder is "one row by a column": on a non-unique column it still types as one row.
class StockRepo(Repository[Stock]):
    by_variant = Finder(Stock.variant_id)  # `stocks.by_variant(v)` -> `Stock`: one row, not a set


# (b) `Load.after` with a function returning a list (3.1: "if the function returns a list of
# refs, they are batch-loaded at once"; 4.7: it "returns a ref or None"). After stage 1 the
# variant IDs are known, so the function can name the variants - the nearest form to the design.
# What it cannot say is how those refs are loaded: their stocks, each stock's warehouse, and the
# lock. A load declaration attaches to a parameter (`Annotated[T, Profile(...)]`), not to the
# refs a `Load.after` function returns, and the stub (like the design) has no way to combine them.
def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


type VariantsAfter = Annotated[list[Variant], Load.after(variants_of)]  # stocks not loaded


# (c) What is written instead: the caller passes the variants (read before the run on the query
# path), each loaded with its stocks and their warehouse, locked. Not shown by the design: a
# `list[Entity]` parameter of refs; a nested path (`Stock.warehouse` under `Variant.stocks`); and
# which rows `lock="for_update"` locks and in what order (saleor: stock rows, by primary key).
lockable = Profile(Variant.stocks, Stock.warehouse, lock="for_update")
type LockedVariants = Annotated[list[Variant], lockable]
type OrderWithItems = Annotated[Order, orders.with_items]


@usecase
def allocate(order: OrderWithItems, variants: LockedVariants) -> Changes:
    by_variant = {v.id: v for v in variants}
    # the caller's variant list may be stale (TOCTOU): every item's variant must be present
    if any(i.variant_id not in by_variant for i in order.items):
        raise LookupError("variants changed since the caller read them; retry")
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
            free = stock.quantity - stock.allocated - planned[stock.id]
            take = min(free, left)
            if take > 0:
                mine.append((item, stock, take))
                left -= take
        if left > 0:  # R4.4: all short items, nothing written
            short.append(item.id)
            continue
        for _, stock, take in mine:
            planned[stock.id] += take
        parts += mine
    if short:
        raise InsufficientStock(short)
    # R4.3: allocation rows through the owned item (a relation operation nested in `update`),
    # stock increments on the stock snapshots loaded through the variants
    changes = order.set(
        *(
            Order.items.update(
                item,
                Item.allocations.add(Allocation(item_id=item.id, stock_id=stock.id, quantity=take)),
            )
            for item, stock, take in parts
        )
    )
    by_stock_id = {s.id: s for v in variants for s in v.stocks}
    for stock_id, qty in planned.items():
        changes += by_stock_id[stock_id].set(Stock.allocated.add(qty))
    return changes


# --------------------------------------------------------------------------- call site
async def post_allocate(order_id: UUID, variant_ids: list[UUID]) -> None:
    await app.run(
        allocate.bind(order=Order.ref(order_id), variants=[Variant.ref(v) for v in variant_ids])
    )


# --------------------------------------------------------------------------- 4.12 unit tests
def test_item_is_split_over_two_warehouses() -> None:
    w = Warehouse.stub(group="default")
    a = Stock.stub(quantity=3, allocated=0, warehouse=w)
    b = Stock.stub(quantity=10, allocated=8, warehouse=w)
    variant = Variant.stub(track_inventory=True, stocks=[a, b])
    item = Item.stub(variant_id=variant.id, quantity=4)
    order = Order.stub(items=[item], warehouse_group="default")
    r = allocate(order, [variant])
    assert r.updated(a)[Stock.allocated] == Add(3)
    assert r.updated(b)[Stock.allocated] == Add(1)
    assert sorted(x.quantity for x in r.inserted(Allocation)) == [1, 3]


def test_short_items_are_all_reported() -> None:
    variant = Variant.stub(track_inventory=True, stocks=[])
    item = Item.stub(variant_id=variant.id, quantity=1)
    with pytest.raises(InsufficientStock):
        allocate(Order.stub(items=[item]), [variant])
