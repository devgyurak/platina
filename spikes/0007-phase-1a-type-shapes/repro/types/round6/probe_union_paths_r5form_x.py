"""Spike 0007 type reproduction, round 6 (type-reviewer): a union result with load arguments.

Round 5's form `Load.after(fn, *paths)`, run per checker against the round-5 stub (invariant
`Path`). The same lines as `probe_union_paths_r6x.py` (M1x-M8x).
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


reveal_type(Load.after(seq_union, Order.items))  # M1x U8 / W8: the path of one member
reveal_type(Load.after(order_or_item, Item.allocations))  # M2x the other member's path
reveal_type(Load.after(order_or_item, Order.items.load(Item.allocations)))  # M3x nested
reveal_type(Load.after(order_or_item, Order.items, Item.allocations))  # M4x one of each
reveal_type(Load.after(opt_union, Order.items))  # M5x one ref, a member's path
reveal_type(Load.after(opt_union, Seat.holds))  # M6x one ref, a path of neither member
reveal_type(Load.after(seq_union, Seat.holds))  # M7x list, a path of neither member
reveal_type(Load.after(rowset_of_union, Order.items))  # M8x row set of a union
