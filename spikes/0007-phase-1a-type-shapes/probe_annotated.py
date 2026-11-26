"""Spike 0007: are the new load shapes checked inside `Annotated[...]` metadata? (spike 0002 X1)

Run directly under each checker (the checkers disagree here by design, so it is not a
`tools.typetests` file). The four marked lines repeat fail_shapes.py's F13 (twice), F17 and F18,
written where a use case writes its load declarations.
"""

from collections.abc import Sequence
from typing import Annotated

from domain import Order, Seat, SeatHold, Variant
from lib import INJECTED, Changes, Load, RowSet, usecase


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


def active_holds(seat: Seat) -> RowSet[SeatHold]:
    return SeatHold.where(SeatHold.seat_id == seat.id)


type A1 = Annotated[Order, Load(Order.items.load(Order.payments))]  # F13 inside a type alias
type A2 = Annotated[list[Variant], Load.after(variants_of, Order.items)]  # F17 inside a type alias


@usecase
def a3(
    order: Annotated[
        Order, Load(Order.items.load(Order.payments))
    ],  # F13 in a parameter annotation
    holds: Annotated[
        Sequence[SeatHold], Load.after(active_holds, missing="none")
    ] = INJECTED,  # F18
) -> Changes:
    return order.delete()
