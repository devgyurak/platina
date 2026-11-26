"""Spike 0007 type reproduction, round 6 (type-reviewer): a union result, no load argument.

Run per checker against both stubs (round 5's `Load.after(fn, *paths: Path[E]) -> Load` and the
receiver form `-> LoadAfter[E]`). N1x / N2x are the write-up's N1 / N2 in the reproducer's words;
N3x-N8x are the reproducer's own; C1x is a control (a non-entity member must be rejected, so an
accepted union is not a vacuous pass).
"""

from collections.abc import Sequence
from typing import reveal_type

from domain import Item, Order, Wallet
from lib import Load, RowSet


def seq_union(order: Order) -> Sequence[Wallet | Order]:
    raise NotImplementedError


def opt_union(order: Order) -> Wallet | Order | None:
    raise NotImplementedError


def req_union(order: Order) -> Wallet | Order:
    raise NotImplementedError


def list_union(order: Order) -> list[Wallet | Order]:
    raise NotImplementedError


def rowset_of_union(order: Order) -> RowSet[Wallet | Order]:
    raise NotImplementedError


def union_of_rowsets(order: Order) -> RowSet[Wallet] | RowSet[Order]:
    raise NotImplementedError


def order_or_item(order: Order) -> Sequence[Order | Item]:
    raise NotImplementedError


def seq_non_entity(order: Order) -> Sequence[Wallet | int]:
    raise NotImplementedError


reveal_type(Load.after(seq_union))  # N1x Sequence[Wallet | Order]
reveal_type(Load.after(opt_union))  # N2x Wallet | Order | None
reveal_type(Load.after(opt_union, missing="none"))  # N3x N2x with missing=
reveal_type(Load.after(req_union))  # N4x Wallet | Order, not optional
reveal_type(Load.after(list_union))  # N5x list[Wallet | Order]
reveal_type(Load.after(rowset_of_union))  # N6x RowSet[Wallet | Order]
reveal_type(Load.after(union_of_rowsets))  # N7x RowSet[Wallet] | RowSet[Order]
reveal_type(Load.after(order_or_item))  # N8x Order | Item, where only one has Item.allocations
reveal_type(Load.after(seq_non_entity))  # C1x control: a non-entity member


def rowset_of_union_body(order: Order) -> RowSet[Wallet | Order]:
    # N6b: can a body produce N6x's result? (RowSet is invariant)
    return Order.where(Order.id == order.id)
