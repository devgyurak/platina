"""Addendum repro (type-reviewer): lines both checkers must accept (A1, A2, A3 and beyond)."""

from collections.abc import Sequence
from decimal import Decimal
from typing import assert_type
from uuid import UUID

from domain import Item, LineStatus, Money, Order, OrderStatus, Transfer, User, Wallet
from domain_x import GLine, GOrder, GPart, MLine, MOrder
from lib import (
    AddOp,
    Changes,
    Entity,
    Load,
    Op,
    OwnedRelation,
    Profile,
    Relation,
    RelOp,
    Write,
    insert,
)


# fmt: off
# --------------------------------------------------------------------------- A1
def a1_column_update(item: Item) -> None:
    assert_type(Order.items.update(item, Item.quantity.to(2)), RelOp[Order])  # A1 (ii)


def a1_several_and_unpacked(item: Item, ops: list[Op[Item]]) -> None:
    assert_type(
        Order.items.update(item, Item.quantity.to(2), Item.status.to(LineStatus.CANCELLED)),
        RelOp[Order],
    )
    assert_type(Order.items.update(item, *ops), RelOp[Order])
    assert_type(Order.items.update(item), RelOp[Order])  # beyond: an empty update still types


def a1_grandchild_column(line: GLine) -> None:
    assert_type(GOrder.lines.update(line, GLine.quantity.to(2)), RelOp[GOrder])


def a1_beyond_grandchild_written_directly(line: GLine, part: GPart) -> Changes:
    # beyond: the narrowing closes only the nested form; the child's own `set` and `insert` still
    # take its relation operations (the seal rule, not the type, rejects GLine.parts)
    return line.set(GLine.parts.add(GPart(sku="x")), GLine.parts.remove(part)) + insert(
        GLine(quantity=1), GLine.parts.add(GPart(sku="y"))
    )


# --------------------------------------------------------------------------- A2
def a2_mixed_list(order: Order, item: Item) -> Changes:
    ops: list[Write[Order]] = [
        Order.status.to(OrderStatus.PAID),
        Order.items.add(item),
        Order.items.remove(item),
        Order.items.update(item, Item.quantity.to(1)),
    ]
    ops.append(Order.paid_at.to(None))
    ops.append(Order.items.add(item))
    ops += [Order.status.to(OrderStatus.CANCELLED), Order.items.remove(item)]
    ops.extend([Order.items.add(item)])
    ops.insert(0, Order.number.to("n"))
    return assert_type(order.set(*ops), Changes)


def a2_alias_is_the_union(w: Op[User] | RelOp[User], x: Write[User]) -> None:
    assert_type(w, Write[User])
    assert_type(x, Op[User] | RelOp[User])


def a2_star_param(order: Order, *ops: Write[Order]) -> Changes:
    return order.set(*ops)


def a2_tuple_and_sequence(order: Order, t: tuple[Write[Order], ...], s: Sequence[Write[Order]]) -> Changes:
    return order.set(*t) + order.set(*s)


def a2_spelled_out_list_is_the_same_type(ops: list[Op[Order] | RelOp[Order]]) -> list[Write[Order]]:
    return ops  # the alias and its expansion are interchangeable, even under list invariance


def a2_generic_helper[O: Entity](row: O, *ops: Write[O]) -> Changes:
    return row.set(*ops)


def a2_generic_helper_use(order: Order, item: Item) -> Changes:
    return a2_generic_helper(order, Order.status.to(OrderStatus.PAID), Order.items.add(item))


def a2_comprehension(order: Order, items: list[Item]) -> Changes:
    ops: list[Write[Order]] = [Order.items.update(i, Item.status.to(LineStatus.CANCELLED)) for i in items]
    return order.set(*ops, Order.status.to(OrderStatus.CANCELLED))


def a2_insert_takes_addops(t: Transfer, adds: list[AddOp[Transfer]]) -> Changes:
    return insert(t, *adds)


def a2_wallet_list(w: Wallet) -> Changes:
    ops: list[Write[Wallet]] = [Wallet.balance.to(Money(Decimal(1)))]
    return w.set(*ops)


# --------------------------------------------------------------------------- A3
def a3_through_root(order: MOrder, line: MLine) -> Changes:
    return assert_type(
        order.set(MOrder.lines.add(MLine(quantity=1)), MOrder.lines.update(line, MLine.quantity.to(2))),
        Changes,
    )


def a3_insert_root(line: MLine) -> Changes:
    return insert(MOrder(number="1"), MOrder.lines.add(MLine(quantity=1))) + MOrder.stub().set(
        MOrder.lines.remove(line)
    )


def a3_part_class_api(order: MOrder, ident: UUID) -> None:
    assert_type(MLine.stub(), MLine)
    assert_type(MLine.ref(ident), MLine)
    assert_type(MLine.ref(ident, expected_version=3), MLine)
    assert_type(order.lines, Sequence[MLine])
    assert_type(order.lines[0].quantity, int)
    assert_type(MOrder.lines, OwnedRelation[MOrder, MLine])
    assert_type(MOrder.lines.where(MLine.quantity > 1), Relation[MOrder, MLine])
    Load(MOrder.lines)
    Profile(MOrder.lines)
# fmt: on
