"""Spike 0006, observation O6: 4.7's `Load.when` inside `Annotated` metadata.

Run directly through both checkers. Spike 0002 (X1): mypy checks nothing inside `Annotated[...]`
metadata, pyright does. Lines 1-2 are 4.7's text; lines 3-4 carry a deliberate operand error.
"""

from typing import Annotated

from domain import Order, PaymentMethod, Wallet
from lib import Load

# 1. 4.7 as written: the condition is a value comparison, the match a column-to-column comparison.
type PointWallet = Annotated[
    Wallet | None,
    Load.when(Order.paid_with == PaymentMethod.POINT, match=Wallet.user_id == Order.user_id),
]

# 2. The match written the other way round, as in 4.7's `Order.user_id` against `Wallet.user_id`.
type PointWalletReversed = Annotated[
    Wallet | None,
    Load.when(Order.paid_with == PaymentMethod.POINT, match=Order.user_id == Wallet.user_id),
]

# 3. A match between columns of different value types (`Id[User]` against `str`).
type BadMatch = Annotated[
    Wallet | None,
    Load.when(Order.paid_with == PaymentMethod.POINT, match=Wallet.user_id == Order.number),
]

# 4. A condition with a value of the wrong type (`int` for `PaymentMethod | None`).
type BadCondition = Annotated[
    Wallet | None,
    Load.when(Order.paid_with == 1, match=Wallet.user_id == Order.user_id),
]
