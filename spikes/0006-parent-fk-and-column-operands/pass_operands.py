"""Spike 0006, part B (#51): the comparison lines that must type-check, with their types."""

from decimal import Decimal
from typing import assert_type

from domain import Order, Wallet
from lib import Check, Pred, SetChange


def operands() -> None:
    assert_type(Order.amount >= Decimal(0), Pred[Order])  # B1: a value of exactly T
    assert_type(Order.ratio >= 1, Pred[Order])  # B4: int to float, the typing spec's promotion
    assert_type(Order.qty <= Order.cap, Pred[Order])  # B5: two columns of one entity
    assert_type(Wallet.user_id == Order.user_id, Pred[Wallet | Order])  # B6: 4.7's match
    assert_type(Wallet.user_id == Order.guest_id, Pred[Wallet | Order])  # B7: T against T | None
    assert_type(Order.guest_id == Wallet.user_id, Pred[Order | Wallet])  # B7: T | None against T
    assert_type(Check(lambda: Order.qty <= Order.cap), Check)  # B10
    assert_type(Order.where(Order.qty <= Order.cap), SetChange[Order])  # B11
