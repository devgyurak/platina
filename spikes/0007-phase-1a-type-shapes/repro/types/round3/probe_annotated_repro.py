"""Own probe: misuse written inside Annotated[...] metadata (spike 0002 X1), per checker."""

from collections.abc import Sequence
from typing import Annotated

from domain import Allocation, Order, PaymentMethod, Seat, SeatHold, Variant, Wallet
from lib import INJECTED, Changes, Load, Now, RowSet, insert, usecase


def active_holds(seat: Seat, now: Now) -> RowSet[SeatHold]:
    return SeatHold.where(SeatHold.seat_id == seat.id, SeatHold.expires_at > now)


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


type A1 = Annotated[Sequence[Order], Load(Order.items.load(Order.payments))]  # F13 in a type alias
type A2 = Annotated[
    Sequence[Order], Load(Order.items.load(Allocation.stock))
]  # F14 in a type alias
type A3 = Annotated[Sequence[Variant], Load.after(variants_of, Order.items)]  # F17 in a type alias
type A4 = Annotated[Sequence[SeatHold], Load.after(active_holds, missing="none")]  # F18
type A5 = Annotated[
    Wallet | None,
    Load.when(
        Order.paid_with == PaymentMethod.WALLET,
        match=Wallet.user_id == Order.user_id,
        missing="skip",
    ),
]  # F20


@usecase
def f(
    order: Order,
    x: Annotated[
        Sequence[Order], Load(Order.items.load(Order.payments))
    ] = INJECTED,  # F13 in a parameter
    y: Annotated[Sequence[Order], Load(Order.items.laod())] = INJECTED,  # misspelled method
) -> Changes:
    return insert(order)
