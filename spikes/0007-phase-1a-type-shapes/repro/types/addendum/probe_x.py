"""Addendum repro (type-reviewer): beyond the claims - per-checker inference, run raw (no markers).

Each `# P<n>` line is reported separately for pyright and mypy in run.sh's output.
"""

from typing import reveal_type

from domain import Item, Order, OrderStatus
from domain_x import MLine
from lib import Changes, RowSet, Write


def p1_unannotated_mixed_list(order: Order, item: Item) -> Changes:
    ops = [Order.status.to(OrderStatus.PAID), Order.items.add(item)]
    reveal_type(ops)  # P1
    return order.set(*ops)  # P1 use


def p2_ternary(order: Order, item: Item, flag: bool) -> Changes:
    op = Order.status.to(OrderStatus.PAID) if flag else Order.items.add(item)
    reveal_type(op)  # P2
    return order.set(op)  # P2 use


def p3_empty_then_append(order: Order, item: Item) -> Changes:
    ops = [Order.status.to(OrderStatus.PAID)]
    ops.append(Order.items.add(item))  # P3: list[Op[Order]] inferred from the first element
    return order.set(*ops)


def p4_spread(order: Order, item: Item, ops: list[Write[Order]]) -> Changes:
    more = [*ops, Order.items.add(item)]
    reveal_type(more)  # P4
    return order.set(*more)


def p5_rowset_of_part(rows: RowSet[MLine]) -> Changes:
    # RowSet's entity has no Entity bound: a RowSet of a Part child is a well-formed type, so
    # `.set` / `.delete` type-check once a value exists (no producer exists in the stub)
    return rows.set(MLine.quantity.to(2)) + rows.delete()  # P5


def p6_rowset_constructible() -> Changes:
    return RowSet[MLine]().delete()  # P6: the stub declares no __init__, so RowSet() constructs
