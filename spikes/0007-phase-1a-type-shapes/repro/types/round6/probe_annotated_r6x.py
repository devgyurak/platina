"""Spike 0007 type reproduction, round 6: the receiver form inside `Annotated[...]` (X1).

Run per checker. Every marked line is a misuse; the write-up expects pyright to report each and
mypy none (it does not check `Annotated` metadata).
"""

from collections.abc import Sequence
from typing import Annotated

from domain import Order, Seat, SeatHold, Stock, Variant
from lib import INJECTED, Changes, Load, RowSet, usecase


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


def active_holds(seat: Seat) -> RowSet[SeatHold]:
    return SeatHold.where(SeatHold.seat_id == seat.id)


def seats_near(seat: Seat) -> RowSet[Seat]:
    return Seat.where(Seat.show_id == seat.show_id)


type A1 = Annotated[Order, Load(Order.items.load(Order.payments))]  # X-a F13 in a type alias
type A2 = Annotated[list[Variant], Load.after(variants_of).load(Order.items)]  # X-b F17
type A3 = Annotated[list[Variant], Load.after(variants_of).load(Stock.quantity)]  # X-c column


@usecase
def a4(
    seat: Annotated[Seat, Load(Seat.tickets.load(Order.payments))],  # X-d F13-like, parameter
    holds: Annotated[
        Sequence[SeatHold], Load.after(active_holds, missing="none")
    ] = INJECTED,  # X-e F18
    near: Annotated[Sequence[Seat], Load.after(seats_near).load(Order.items)] = INJECTED,  # X-f
) -> Changes:
    return seat.delete()
