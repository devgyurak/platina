"""Spike 0007 round 6: a `Load.after` function returning a union of entities, with no load argument.

Run per checker against both stubs (`run.sh` stage 4): the round-5 stub (`Load.after(fn, *paths:
Path[E]) -> Load`) and the round-6 stub (`Load.after(fn) -> LoadAfter[E]`). With no load
argument the two forms differ only in their return type, so this shows whether round 5's
invariant `Path` was what rejected a union result (W8 / U8), or nothing does (N1, N2). `reveal_type`
prints what each checker solves `E` to.
"""

from collections.abc import Sequence
from typing import reveal_type

from domain import Order, Wallet
from lib import Load


def wallet_or_order(order: Order) -> Sequence[Wallet | Order]:
    return [order]


def one_or_other(order: Order) -> Wallet | Order | None:
    return order


n1 = Load.after(wallet_or_order)  # N1 a list of refs of two entities, no load argument
n2 = Load.after(one_or_other)  # N2 one ref of two entities, no load argument
reveal_type(n1)
reveal_type(n2)
