"""Addendum repro (type-reviewer): misuse both checkers must reject (A1, A2, A3 and beyond)."""

from decimal import Decimal

from domain import Item, Money, Order, OrderStatus, Transfer, Wallet
from domain_x import GLine, GOrder, GPart, MLine, MOrder
from lib import Changes, Entity, Op, RelOp, Write, insert, insert_all


# fmt: off
# --------------------------------------------------------------------------- A1
def f_a1_grandchild_add(line: GLine) -> RelOp[GOrder]:
    return GOrder.lines.update(line, GLine.parts.add(GPart(sku="x")))  # expect-error[reportArgumentType, arg-type]: A1 (i) a grandchild's relation operation inside a child update


def f_a1_grandchild_remove(line: GLine, part: GPart) -> RelOp[GOrder]:
    return GOrder.lines.update(line, GLine.parts.remove(part))  # expect-error[reportArgumentType, arg-type]: A1 (i) remove


def f_a1_grandchild_update(line: GLine, part: GPart) -> RelOp[GOrder]:
    return GOrder.lines.update(line, GLine.parts.update(part, GPart.sku.to("y")))  # expect-error[reportArgumentType, arg-type]: A1 (i) nested update


def f_a1_unpacked_write_list(item: Item, ops: list[Write[Item]]) -> RelOp[Order]:
    return Order.items.update(item, *ops)  # expect-error[reportArgumentType, arg-type]: A1 a Write list of the child no longer feeds update


def f_a1_wrong_owner(item: Item) -> RelOp[Order]:
    return Order.items.update(item, Order.status.to(OrderStatus.PAID))  # expect-error[reportArgumentType, arg-type]: unchanged - an operation of the root inside a child update


# --------------------------------------------------------------------------- A2
def f_a2_wrong_owner_in_list() -> list[Write[Order]]:
    ops: list[Write[Order]] = [Wallet.balance.to(Money(Decimal(1)))]  # expect-error[reportAssignmentType, list-item]: A2 the alias widens no owner
    return ops


def f_a2_wrong_owner_append(ops: list[Write[Order]]) -> None:
    ops.append(Wallet.balance.to(Money(Decimal(1))))  # expect-error[reportArgumentType, arg-type]: A2 append of another owner


def f_a2_wrong_relop_append(ops: list[Write[Order]], leg_ops: list[Write[Transfer]]) -> None:
    ops.extend(leg_ops)  # expect-error[reportArgumentType, arg-type]: A2 extend with another owner's writes


def f_a2_rowset(ops: list[Write[Order]]) -> Changes:
    return Order.where(Order.status == OrderStatus.PENDING).set(*ops)  # expect-error[reportArgumentType, arg-type]: A2 RowSet.set takes Op only


def f_a2_setchange(ops: list[Write[Order]]) -> Changes:
    return Order.where(Order.status == OrderStatus.PENDING).set(Order.status.to(OrderStatus.EXPIRED)).set(*ops)  # expect-error[reportArgumentType, arg-type]: A2 SetChange.set takes Op only


def f_a2_insert(t: Transfer, ops: list[Write[Transfer]]) -> Changes:
    return insert(t, *ops)  # expect-error[reportArgumentType, arg-type]: A2 insert takes AddOp only


def f_a2_other_receiver(w: Wallet, ops: list[Write[Order]]) -> Changes:
    return w.set(*ops)  # expect-error[reportArgumentType, arg-type]: A2 another receiver


def f_a2_list_invariance(ops: list[Op[Order]]) -> list[Write[Order]]:
    return ops  # expect-error[reportReturnType, return-value]: beyond - a list[Op[O]] is not a list[Write[O]] (invariance)


# --------------------------------------------------------------------------- A3
def f_a3_set(line: MLine) -> None:
    line.set(MLine.quantity.to(2))  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: A3 no set on a Part


def f_a3_delete(line: MLine) -> None:
    line.delete()  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: A3 no delete on a Part


def f_a3_where() -> None:
    MLine.where(MLine.quantity == 1).delete()  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: A3 no where on a Part


def f_a3_insert() -> Changes:
    return insert(MLine(quantity=1))  # expect-error[reportArgumentType, type-var]: A3 insert takes an Entity


def f_a3_insert_all() -> Changes:
    return insert_all([MLine(quantity=1)])  # expect-error[reportArgumentType, list-item]: beyond - insert_all takes Entities


def save_any[E: Entity](row: E, *ops: Write[E]) -> Changes:
    return row.set(*ops) + row.delete()


def save_entity(row: Entity) -> Changes:
    return row.delete()


def f_a3_generic_helper(line: MLine) -> Changes:
    return save_any(line)  # expect-error[reportArgumentType, type-var]: beyond - an Entity-bound generic helper


def f_a3_entity_helper(line: MLine) -> Changes:
    return save_entity(line)  # expect-error[reportArgumentType, arg-type]: beyond - an Entity-typed helper


def f_a3_missing_field() -> MLine:
    return MLine()  # expect-error[reportCallIssue, call-arg]: beyond - the constructor still requires quantity


def f_a3_child_op_on_root(order: MOrder) -> Changes:
    return order.set(MLine.quantity.to(2))  # expect-error[reportArgumentType, arg-type]: beyond - a child's Op on the root


def f_a3_insert_line_as_root(line: MLine) -> Changes:
    return insert(MOrder(number="1"), MOrder.lines.update(line, MLine.quantity.to(1)))  # expect-error[reportArgumentType, arg-type]: unchanged - insert takes AddOp only
# fmt: on
