"""Probe: 4.12's assertion shape `r.updated(order) == {Order.status: PAID, ...}`.

A dict display with `Column` keys. `Column` overrides `__eq__` (it builds a predicate) and the
stub declares no `__hash__`.
"""

from datetime import datetime
from decimal import Decimal
from typing import reveal_type

from domain import Money, Order, OrderStatus, Wallet
from lib import Add
from uc01_payment import pay

NOW = datetime(2026, 11, 24)


def test_pay_moves_balance_4_12() -> None:
    order = Order.stub(status=OrderStatus.PENDING, total=Money(Decimal("1000")))
    wallet = Wallet.stub(balance=Money(Decimal("5000")))
    r = pay(order, wallet, now=NOW)
    expected = {Order.status: OrderStatus.PAID, Order.paid_at: NOW}  # 4.12, line 1
    reveal_type(expected)
    assert r.updated(order) == expected
    assert r.updated(wallet) == {Wallet.balance: Add(Decimal("-1000"))}  # 4.12, line 2
    assert r.updated(wallet)[Wallet.balance] == Add(Decimal("-1000"))  # indexing instead
