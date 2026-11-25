"""Use case 6 - order merge (two parameters of one type). Requirements R6.1-R6.6.

Source: solidusio/solidus `core/app/models/spree/order_merger.rb` `merge!`. Rules restated.
"""

from decimal import Decimal
from typing import Annotated
from uuid import UUID

import pytest
from domain import CannotMerge, Item, LineStatus, Money, Order, OrderStatus, User, orders
from lib import Add, App, Changes, Id, Op, UNDECIDED_delete, usecase

app = App(dsn="postgresql://app@primary/shop")

type MergeableOrder = Annotated[Order, orders.with_items]


@usecase
def merge(src: MergeableOrder, dst: MergeableOrder, user_id: Id[User] | None) -> Changes:
    # R6.1: "the same order" is a comparison of keys. `src == dst` would compare values (#54,
    # provisional rule) - true for two snapshots of one row, but also what a test with two stubs
    # of equal values would hit; the ID comparison says what is meant.
    if src.id == dst.id:
        raise CannotMerge(src.id)
    if src.total.currency != dst.total.currency:
        raise CannotMerge(src.id)
    if src.status is not OrderStatus.PENDING or dst.status is not OrderStatus.PENDING:
        raise CannotMerge(src.id)
    by_variant = {i.variant_id: i for i in dst.items}  # keys are IDs, not entities
    ops: list[Op[Order]] = []
    # dst's active lines after the merge, for R6.4 (cancelled lines do not count)
    quantity = {i.id: i.quantity for i in dst.items if i.status is LineStatus.ACTIVE}
    lines = [(i.id, i.price.amount) for i in dst.items if i.status is LineStatus.ACTIVE]
    next_position = max((i.position for i in dst.items), default=-1) + 1
    for s in src.items:  # R6.2
        match = by_variant.get(s.variant_id)
        if match is not None:
            ops.append(Order.items.update(match, Item.quantity.add(s.quantity)))
            quantity[match.id] = quantity.get(match.id, 0) + s.quantity
            continue
        # a copy with a new ID (as the source does); "move the row to dst" has no operation:
        # `Order.items` operations act on one parent, and the child's parent key is a column
        copy = Item(
            order_id=dst.id,  # parent key by hand (#49)
            variant_id=s.variant_id,
            quantity=s.quantity,
            price=s.price,
            position=next_position,
        )
        next_position += 1
        ops.append(Order.items.add(copy))
        quantity[copy.id] = copy.quantity
        lines.append((copy.id, copy.price.amount))
    if dst.user_id is None and user_id is not None:  # R6.3
        ops.append(Order.user_id.to(user_id))
    total = sum((price * quantity[line] for line, price in lines), Decimal(0))  # R6.4
    ops.append(Order.total.to(Money(total, dst.total.currency)))
    # R6.5: the children can be removed; the root row has no delete operation in section 4
    return (
        dst.set(*ops) + src.set(*(Order.items.remove(i) for i in src.items)) + UNDECIDED_delete(src)
    )


# --------------------------------------------------------------------------- call site
async def post_merge(guest_cart: UUID, user_cart: UUID, user_id: Id[User]) -> None:
    # two refs of one type: nothing stops the caller passing the same ID twice; whether the loader
    # then gives two snapshots of one row (and what two writes to it mean) is not stated
    await app.run(merge.bind(src=Order.ref(guest_cart), dst=Order.ref(user_cart), user_id=user_id))


# --------------------------------------------------------------------------- 4.12 unit tests
def test_same_variant_adds_quantity() -> None:
    line = Item.stub(quantity=1, price=Money(Decimal("100")))
    dst = Order.stub(status=OrderStatus.PENDING, items=[line], total=Money(Decimal("100")))
    src_line = Item.stub(variant_id=line.variant_id, quantity=2, price=Money(Decimal("100")))
    src = Order.stub(status=OrderStatus.PENDING, items=[src_line], total=Money(Decimal("200")))
    r = merge(src, dst, None)
    # a child update recorded inside the root's changes: no assertion shape in 4.12 / 11.11
    # reaches it except through the child snapshot
    assert r.updated(line)[Item.quantity] == Add(2)
    assert r.updated(dst)[Order.total] == Money(Decimal("300"))
    assert r.removed(src_line)


def test_merge_into_itself_is_rejected() -> None:
    order = Order.stub(status=OrderStatus.PENDING)
    with pytest.raises(CannotMerge):
        merge(order, order, None)
