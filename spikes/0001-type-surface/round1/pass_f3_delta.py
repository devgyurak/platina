"""F3 pinned: `Wallet.balance.add(Decimal)` through a structural self-type (`lib_delta.pyi`)."""

from decimal import Decimal
from typing import assert_type

from lib_delta import Additive, Col, Column, Op


class Money(Additive[Decimal]):
    amount: Decimal


class Wallet:
    balance: Col[Money]
    count: Col[int]


def f3(m: Money) -> None:
    assert_type(Wallet.balance, Column[Money])
    assert_type(Wallet.balance.add(Decimal("-1")), Op)
    assert_type(Wallet.count.add(1), Op)
    assert_type(Wallet.balance.add(m), Op)  # the whole value also matches (second overload)
