"""Addendum for ADR-0010: lines both checkers must accept on the addendum stub (`lib.pyi` here).

A1 `OwnedRelation.update(item, *ops: Op[E])`; A2 the alias `Write[O] = Op[O] | RelOp[O]`; A3 the
alternative `Part` base for owned children. Run: `bash spikes/0007-phase-1a-type-shapes/addendum/run.sh`.
"""

from collections.abc import Sequence
from typing import assert_type

from domain import Item, Leg, LegSide, Money, Order, OrderStatus, Transfer, User
from domain_addendum import GLine, GOrder, MLine, MOrder
from lib import Changes, Op, RelOp, Write, insert


# --------------------------------------------------------------------------- A1 narrowed update
def a1_column_update(item: Item) -> RelOp[Order]:
    return assert_type(Order.items.update(item, Item.quantity.to(2)), RelOp[Order])


def a1_update_of_a_child_that_declares_an_owned_relation(line: GLine) -> RelOp[GOrder]:
    return assert_type(GOrder.lines.update(line, GLine.quantity.to(1)), RelOp[GOrder])


# --------------------------------------------------------------------------- A2 Write[O]
def a2_collected_writes(order: Order, item: Item, gone: Item) -> Changes:
    ops: list[Write[Order]] = []
    ops.append(Order.status.to(OrderStatus.PAID))
    ops.append(Order.items.add(Item.stub()))
    ops.append(Order.items.update(item, Item.quantity.to(3)))
    ops.append(Order.items.remove(gone))
    return assert_type(order.set(*ops), Changes)


def a2_alias_is_the_union(op: Write[User]) -> None:
    def takes_union(_: object) -> None: ...

    takes_union(op)
    assert_type(op, Op[User] | RelOp[User])  # the alias is exactly the union


# --------------------------------------------------------------------------- A3 marker (alternative)
def a3_owned_child_through_its_root(order: MOrder, line: MLine) -> Changes:
    assert_type(order.lines, Sequence[MLine])
    return order.set(
        MOrder.lines.add(MLine(quantity=1)), MOrder.lines.update(line, MLine.quantity.to(2))
    )


def a3_new_root_with_part_children() -> Changes:
    return insert(MOrder(note="n"), MOrder.lines.add(MLine(quantity=1)))


def a3_stub_and_ref() -> None:
    assert_type(MLine.stub(), MLine)
    assert_type(MLine.ref(MLine.stub().id), MLine)


# --------------------------------------------------------------------------- unchanged shapes
def unchanged_new_root_with_children(m: Money) -> Changes:
    t = Transfer(amount=m)
    leg = Leg(account_id=Leg.stub().account_id, side=LegSide.CREDIT, amount=m)
    return insert(t, Transfer.legs.add(leg))
