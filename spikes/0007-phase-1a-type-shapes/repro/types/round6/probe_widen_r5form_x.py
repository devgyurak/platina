"""Spike 0007 type reproduction, round 6: W6-W8 of probe_widen_r6x.py in round 5's form.

Run per checker against the round-5 stub (`Load.after(fn, *paths: Path[E]) -> Load`): is the
widening through a declared type, or through a function with a union result, new in round 6?
"""

from collections.abc import Sequence

from domain import Order, Wallet, wallets
from lib import Load


def point_wallet(order: Order) -> Wallet | None:
    return wallets.by_user(order.user_id) if order.user_id is not None else None


def wallet_or_order(order: Order) -> Sequence[Wallet | Order]:
    return [order]


u6: Load = Load.after(point_wallet, Order.items)  # U6 = W6/W7: a declared type on the result
u8 = Load.after(wallet_or_order, Order.items)  # U8 = W8: a union result takes either's path
