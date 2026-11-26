"""Use case 6 (spike 0002) in the spike 0007 shapes - order merge. Requirements R6.1-R6.6.

Changed from spike 0002: R6.5 is `src.delete()` (#57), which also deletes `src`'s owned items, so
the explicit `Order.items.remove(...)` of every source line is gone; the copied lines take their
parent key from `Order.items.add` (#49, as given), so `order_id=dst.id` is gone too.
"""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

import pytest
from domain import CannotMerge, Item, LineStatus, Money, Order, OrderStatus, User, orders
from lib import Add, App, Changes, Id, Op, RelOp, usecase

app = App(dsn="postgresql://app@primary/shop")

type MergeableOrder = Annotated[Order, orders.with_items]


@usecase
def merge(src: MergeableOrder, dst: MergeableOrder, user_id: Id[User] | None) -> Changes:
    if src.id == dst.id:  # R6.1 - by key (`==` compares columns, #54)
        raise CannotMerge(src.id)
    if src.total.currency != dst.total.currency:
        raise CannotMerge(src.id)
    if src.status is not OrderStatus.PENDING or dst.status is not OrderStatus.PENDING:
        raise CannotMerge(src.id)
    by_variant = {i.variant_id: i for i in dst.items}
    ops: list[Op[Order] | RelOp[Order]] = []  # a relation operation is not an Op (R8)
    quantity = {i.id: i.quantity for i in dst.items if i.status is LineStatus.ACTIVE}
    lines = [(i.id, i.price.amount) for i in dst.items if i.status is LineStatus.ACTIVE]
    next_position = max((i.position for i in dst.items), default=-1) + 1
    for s in src.items:  # R6.2
        match = by_variant.get(s.variant_id)
        if match is not None:
            ops.append(Order.items.update(match, Item.quantity.add(s.quantity)))
            quantity[match.id] = quantity.get(match.id, 0) + s.quantity
            continue
        copy = Item(  # #49: no parent key - `Order.items.add` sets it
            variant_id=s.variant_id, quantity=s.quantity, price=s.price, position=next_position
        )
        next_position += 1
        ops.append(Order.items.add(copy))
        quantity[copy.id] = copy.quantity
        lines.append((copy.id, copy.price.amount))
    if dst.user_id is None and user_id is not None:  # R6.3
        ops.append(Order.user_id.to(user_id))
    total = sum((price * quantity[line] for line, price in lines), Decimal(0))  # R6.4
    ops.append(Order.total.to(Money(total, dst.total.currency)))
    return dst.set(*ops) + src.delete()  # R6.5: the root and its owned items (#57)


# --------------------------------------------------------------------------- call site
async def post_merge(guest_cart: UUID, user_cart: UUID, user_id: Id[User]) -> None:
    await app.run(merge.bind(src=Order.ref(guest_cart), dst=Order.ref(user_cart), user_id=user_id))


# --------------------------------------------------------------------------- 4.12 unit tests
def test_same_variant_adds_quantity_and_deletes_the_source() -> None:
    line = Item.stub(quantity=1, price=Money(Decimal("100")))
    dst = Order.stub(status=OrderStatus.PENDING, items=[line], total=Money(Decimal("100")))
    src_line = Item.stub(variant_id=line.variant_id, quantity=2, price=Money(Decimal("100")))
    src = Order.stub(status=OrderStatus.PENDING, items=[src_line], total=Money(Decimal("200")))
    r = merge(src, dst, None)
    assert r.updated(line)[Item.quantity] == Add(2)
    assert r.updated(dst)[Order.total] == Money(Decimal("300"))
    assert r.removed(src)
    # #57: the owned items go with the root without being listed - `r.removed(src_line)` has no
    # row-level answer; the test can only see "every owned child of src" through `r.removed(src)`


def test_merge_into_itself_is_rejected() -> None:
    order = Order.stub(status=OrderStatus.PENDING)
    with pytest.raises(CannotMerge):
        merge(order, order, None)
