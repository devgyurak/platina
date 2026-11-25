"""F3 (copied from the round-1 reproducer's rp_probe_delta.py): Wallet.balance.add(Decimal) with balance: Col[Money] unchanged, Money declaring Additive[Decimal]."""

from decimal import Decimal
from typing import reveal_type

from lib_delta import Additive, Col


class Money(Additive[Decimal]):
    amount: Decimal


class Wallet:
    balance: Col[Money]
    count: Col[int]
    name: Col[str]


def probe(m: Money) -> None:
    reveal_type(Wallet.balance)
    reveal_type(Wallet.balance.add(Decimal("-1")))
    reveal_type(Wallet.count.add(1))
    reveal_type(Wallet.balance.add(m))  # whole-value add: falls to overload 2
    Wallet.balance.add("1")  # N1
    Wallet.count.add("1")  # N2
    Wallet.balance.to(Decimal("1"))  # N3: to still takes a Money
