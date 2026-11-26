"""Spike 0006, observation O8: `==` / `!=` with a value of the wrong type.

Run directly through both checkers. `>=` and `<` have no fallback; `==` and `!=` fall back to the
reflected `__eq__` of the value's class, which typeshed types `(object) -> bool`.
"""

from decimal import Decimal
from typing import reveal_type

from domain import Order
from lib import Check

reveal_type(Order.amount == 0)  # int for a Decimal column
reveal_type(Order.number == 1)  # int for a str column
reveal_type(Order.number != 1)
reveal_type(Order.amount == Decimal(0))  # the right type, for contrast
reveal_type(Order.where(Order.amount == 0))  # caught where a Pred is required
reveal_type(Check(lambda: Order.amount == 0))  # caught by Check (found by the reproduction)
