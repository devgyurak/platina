"""Probe: are expressions inside `Annotated[...]` metadata type-checked by both checkers?

The use cases declare loads as `Annotated[T, Load...(...)]`. If a checker does not evaluate the
metadata, a misuse inside a load declaration passes that checker silently.
"""

from typing import Annotated

from domain import Order, PaymentMethod, Wallet
from lib import Load, Profile

# 1. outside `Annotated`: the column-to-column comparison
outside = Load.when(Order.paid_with == PaymentMethod.WALLET, match=Wallet.user_id == Order.user_id)

# 2. the same expression in a PEP 695 alias
type InAlias = Annotated[
    Wallet | None,
    Load.when(Order.paid_with == PaymentMethod.WALLET, match=Wallet.user_id == Order.user_id),
]


# 3. the same expression in a parameter annotation
def in_param(
    w: Annotated[
        Wallet | None,
        Load.when(Order.paid_with == PaymentMethod.WALLET, match=Wallet.user_id == Order.user_id),
    ],
) -> None: ...


# 4. a plain wrong argument type inside the metadata (not a #51 question)
type WrongArg = Annotated[Order, Profile(Order.items, lock="for_share")]
type WrongArgOutside = Profile
wrong_outside = Profile(Order.items, lock="for_share")
