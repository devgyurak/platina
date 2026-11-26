"""Addendum for ADR-0010: misuse both checkers must reject on the addendum stub, codes observed.

A1-F1: a relation operation on a grandchild inside a child update (spike 0002 X15).
A2-F1..F3: the `Write[O]` alias does not widen what each receiver takes.
A3-F1..F4: with the alternative `Part` base, direct writes of an owned child (spike 0007 R10-R12).
"""

from domain import Order, OrderStatus, Transfer, Wallet
from domain_addendum import GLine, GOrder, GPart, MLine
from lib import Changes, Write, insert


# fmt: off
def a1_f1_grandchild_operation_in_update(line: GLine) -> object:
    return GOrder.lines.update(line, GLine.parts.add(GPart(label="x")))  # expect-error[reportArgumentType, arg-type]: A1-F1 a relation operation is not an Op[GLine]


def a2_f1_other_entity_in_the_list(m: Wallet) -> None:
    ops: list[Write[Order]] = [Wallet.balance.to(m.balance)]  # expect-error[reportAssignmentType, list-item]: A2-F1 Op[Wallet] is not a Write[Order]
    del ops


def a2_f2_row_set_takes_column_operations_only(ops: list[Write[Order]]) -> object:
    return Order.where(Order.status == OrderStatus.PENDING).set(*ops)  # expect-error[reportArgumentType, arg-type]: A2-F2 RowSet.set takes Op only


def a2_f3_insert_takes_add_only(t: Transfer, ops: list[Write[Transfer]]) -> Changes:
    return insert(t, *ops)  # expect-error[reportArgumentType, arg-type]: A2-F3 insert takes AddOp only


def a3_f1_set_on_owned_child(line: MLine) -> object:
    return line.set(MLine.quantity.to(2))  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType, attr-defined]: A3-F1 a Part has no set (R11)


def a3_f2_delete_on_owned_child(line: MLine) -> object:
    return line.delete()  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType, attr-defined]: A3-F2 a Part has no delete (R10)


def a3_f3_insert_owned_child() -> Changes:
    return insert(MLine(quantity=1))  # expect-error[reportArgumentType, type-var]: A3-F3 a Part is not an Entity (R12)


def a3_f4_row_set_of_owned_child() -> object:
    return MLine.where(MLine.quantity > 0)  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType, attr-defined]: A3-F4 a Part has no where
# fmt: on
