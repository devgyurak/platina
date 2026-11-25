"""Item 6: chain with TypeVarTuple; c.run argument checks."""

from datetime import datetime
from typing import assert_type, reveal_type

from domain import Coupon, Order, Wallet, apply_coupon, pay
from lib_design import Chain, Changes, chain


def probe(order: Order, wallet: Wallet, coupon: Coupon, now: datetime) -> Changes:
    with chain(order, wallet) as (c, o2, w2):
        reveal_type(chain(order, wallet))
        reveal_type(c)
        reveal_type(o2)
        reveal_type(w2)
        assert_type(c, Chain)
        assert_type(o2, Order)
        assert_type(w2, Wallet)
        c.run(apply_coupon, o2, coupon)
        c.run(pay, o2, w2, now)
        c.run(pay, o2, w2)  # O1 injected parameter omitted
        c.run(pay, order=o2, wallet=w2)  # O2 keywords
        c.run(apply_coupon, coupon, o2)  # C1 swapped
        c.run(apply_coupon, o2)  # C2 missing coupon
        c.run(apply_coupon, o2, coupon, 1)  # C3 one too many
    reveal_type(c.changes)
    with chain(order, wallet, coupon) as (c3, a, b, d):
        assert_type((a, b, d), tuple[Order, Wallet, Coupon])
        c3.run(apply_coupon, a, d)
    with chain(order, wallet) as (c4, x):  # C4 arity of the unpacking
        c4.run(apply_coupon, x, coupon)
    return c.changes


def rebinding(order: Order, wallet: Wallet) -> None:
    with chain(order, wallet) as (c, order, wallet):  # 4.6: rebound to the same names
        assert_type(order, Order)
        c.run(pay, order, wallet)
    with chain(order, wallet) as (c, wallet, order):  # C5 swapped rebinding
        c.run(pay, order, wallet)
