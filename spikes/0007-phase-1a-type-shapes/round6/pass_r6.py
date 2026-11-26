"""Spike 0007 round 6: the receiver form of `Load.after` - lines both checkers must accept.

`Load.after(fn, missing=...)` returns a `LoadAfter[E]` for the entity `fn` returns; its load
arguments go on it with `.load(*paths: LoadPath[E])`, as on a relation (#59 point 1). The stub is
`lib.pyi` here (round 5's with the receiver form and no invariant `Path`).
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, assert_type
from uuid import UUID

from domain import Order, Seat, SeatHold, Show, Stock, Ticket, User, Variant, Wallet, wallets
from lib import INJECTED, Changes, Load, LoadAfter, Now, RowSet, usecase


def active_holds(seat: Seat, now: Now) -> RowSet[SeatHold]:
    return SeatHold.where(SeatHold.seat_id == seat.id, SeatHold.expires_at > now)


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


def point_wallet(order: Order) -> Wallet | None:
    return wallets.by_user(order.user_id) if order.user_id is not None else None


def order_of(ticket: Ticket) -> Order | None:
    return Order.ref(ticket.order_id)


def open_orders(user: User) -> RowSet[Order]:
    return Order.where(Order.user_id == user.id)


def seats_of(show: Show) -> RowSet[Seat]:
    return Seat.where(Seat.show_id == show.id)


# P1-P3: each return form, without load arguments (what `Load.after` itself returns)
assert_type(Load.after(active_holds), LoadAfter[SeatHold])  # P1 row set
assert_type(Load.after(variants_of), LoadAfter[Variant])  # P2 Sequence of refs
assert_type(Load.after(point_wallet, missing="none"), LoadAfter[Wallet])  # P3 one ref, missing

# P4-P6: each return form with load arguments
assert_type(Load.after(seats_of).load(Seat.holds), LoadAfter[Seat])  # P4 row set
assert_type(Load.after(variants_of).load(Variant.stocks), LoadAfter[Variant])  # P5 Sequence of refs
assert_type(
    Load.after(order_of, missing="none").load(Order.items), LoadAfter[Order]
)  # P6 one ref, with missing=

# P7-P9: nested paths under a `Load.after` result
assert_type(
    Load.after(variants_of).load(Variant.stocks.load(Stock.warehouse)), LoadAfter[Variant]
)  # P7 two levels
assert_type(
    Load.after(seats_of).load(Seat.tickets.load(Ticket.order.load(Order.items))),
    LoadAfter[Seat],
)  # P8 three levels, through a many-to-one
assert_type(
    Load.after(open_orders).load(Order.show.load(Show.seats), Order.user.load(User.addresses)),
    LoadAfter[Order],
)  # P9 through two nullable many-to-one relations (`Show | None`, `User | None`)

# P10: several arguments, and `.load` chained (the same as one call, as on a relation)
assert_type(Load.after(seats_of).load(Seat.holds).load(Seat.tickets), LoadAfter[Seat])  # P10

# P11: a named value used in `Annotated[...]` (X1: both checkers check the named value)
holds_load = Load.after(active_holds)
seats_load = Load.after(seats_of).load(Seat.tickets.load(Ticket.order), Seat.holds)
type ActiveHolds = Annotated[Sequence[SeatHold], holds_load]
type ShowSeats = Annotated[Sequence[Seat], seats_load]


@usecase
def hold(
    seat: Annotated[Seat, Load()],
    holds: ActiveHolds = INJECTED,
    seats: ShowSeats = INJECTED,
    now: Now = INJECTED,
) -> Changes:
    assert_type(holds, Sequence[SeatHold])
    assert_type(seats, Sequence[Seat])
    assert_type(now, datetime)
    return seat.set()


hold.bind(seat=Seat.ref(UUID(int=1)))  # P12 the dependent loads are left out of bind (#48)
