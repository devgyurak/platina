"""Spike 0007 type reproduction, round 6 (type-reviewer): a union result with load arguments.

Receiver form, run per checker against the round-6 stub. M1x-M8x are the reproducer's own: what
`.load(...)` takes once a union result has fixed `E`. `probe_union_paths_r5form_x.py` has the same
lines in round 5's form.
"""

from collections.abc import Sequence
from typing import reveal_type

from domain import Item, Order, Seat, Wallet
from lib import Load, RowSet


def seq_union(order: Order) -> Sequence[Wallet | Order]:
    raise NotImplementedError


def opt_union(order: Order) -> Wallet | Order | None:
    raise NotImplementedError


def rowset_of_union(order: Order) -> RowSet[Wallet | Order]:
    raise NotImplementedError


def order_or_item(order: Order) -> Sequence[Order | Item]:
    raise NotImplementedError


reveal_type(Load.after(seq_union).load(Order.items))  # M1x U8 / W8: the path of one member
reveal_type(Load.after(order_or_item).load(Item.allocations))  # M2x the other member's path
reveal_type(Load.after(order_or_item).load(Order.items.load(Item.allocations)))  # M3x nested
reveal_type(Load.after(order_or_item).load(Order.items, Item.allocations))  # M4x one of each
reveal_type(Load.after(opt_union).load(Order.items))  # M5x one ref, a member's path
reveal_type(Load.after(opt_union).load(Seat.holds))  # M6x one ref, a path of neither member
reveal_type(Load.after(seq_union).load(Seat.holds))  # M7x list, a path of neither member
reveal_type(Load.after(rowset_of_union).load(Order.items))  # M8x row set of a union
