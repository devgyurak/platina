"""Round 6: a copy of `../uc05_seat_hold.py` with the `Load.after` lines in the receiver form; every changed
line carries `# [r6]`.

Use case 5 (spike 0002) in the spike 0007 shapes - seat reservation. Requirements R5.1-R5.5.

Changed from spike 0002: R5.2's two existence reads are row-set loads over the predicates the rule
states - unexpired holds of other users (a predicate over `now`, which a partial load cannot
name), active tickets with their order - and R5.3 loads the seats of the show near this seat
instead of the whole show. The hold is written with `insert` (#60 point 4: `Seat.holds` is not
owned, so it has no `add`).

Still awkward: for the near seats, their holds and tickets are whole relations, filtered in Python
(the holds need `now`, which a partial load cannot name; the tickets could be a constant partial
load), so expired holds and tickets of cancelled orders of *those* seats are still loaded; the ticket's order status is a predicate over a relation of
the row, which a row set cannot state either (it is loaded with `Ticket.order` and checked here).
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

import pytest
from domain import LineStatus, OrderStatus, Seat, SeatHold, SeatUnavailable, Show, Ticket, User
from lib import INJECTED, App, Changes, Id, Load, Now, RowSet, insert, usecase

app = App(dsn="postgresql://app@primary/shop")

HOLD = timedelta(minutes=15)


# R5.2 - both bind to the use case's parameters by name (`seat`, `user_id`, `now`)
def other_holds(seat: Seat, user_id: Id[User], now: Now) -> RowSet[SeatHold]:
    return SeatHold.where(
        SeatHold.seat_id == seat.id, SeatHold.expires_at >= now, SeatHold.user_id != user_id
    )


def active_tickets(seat: Seat) -> RowSet[Ticket]:
    return Ticket.where(Ticket.seat_id == seat.id, Ticket.status == LineStatus.ACTIVE)


# R5.3 - a box around the seat, from values loaded in stage 1 (the exact distance is checked here)
def near_seats(seat: Seat, show: Show) -> RowSet[Seat]:
    d = show.min_distance
    return Seat.where(
        Seat.show_id == show.id,
        Seat.x >= seat.x - d,
        Seat.x <= seat.x + d,
        Seat.y >= seat.y - d,
        Seat.y <= seat.y + d,
    )


holds_load = Load.after(other_holds)
tickets_load = Load.after(active_tickets).load(Ticket.order)  # [r6]
near_load = Load.after(near_seats).load(Seat.tickets.load(Ticket.order), Seat.holds)  # [r6]

type OtherHolds = Annotated[Sequence[SeatHold], holds_load]
type ActiveTickets = Annotated[Sequence[Ticket], tickets_load]
type NearSeats = Annotated[Sequence[Seat], near_load]


def ticket_holds(t: Ticket) -> bool:
    return t.status is LineStatus.ACTIVE and t.order.status in (
        OrderStatus.PENDING,
        OrderStatus.PAID,
    )


def taken(seat: Seat, now: datetime, me: Id[User]) -> bool:  # for the near seats (over-read)
    return any(ticket_holds(t) for t in seat.tickets) or any(
        h.expires_at >= now and h.user_id != me for h in seat.holds
    )


@usecase
def hold_seat(
    seat: Annotated[Seat, Load()],
    show: Annotated[Show, Load()],
    user_id: Id[User],
    holds: OtherHolds = INJECTED,
    tickets: ActiveTickets = INJECTED,
    near: NearSeats = INJECTED,
    now: Now = INJECTED,
) -> Changes:
    if seat.show_id != show.id:
        raise SeatUnavailable(seat.id)
    if seat.blocked and not show.allow_blocked:  # R5.1
        raise SeatUnavailable(seat.id)
    if holds or any(ticket_holds(t) for t in tickets):  # R5.2
        raise SeatUnavailable(seat.id)
    if show.min_distance > 0:  # R5.3
        for other in near:
            if other.id == seat.id or not taken(other, now, user_id):
                continue
            if show.distance_within_row and other.row != seat.row:
                continue
            if (other.x - seat.x) ** 2 + (other.y - seat.y) ** 2 < show.min_distance**2:
                raise SeatUnavailable(seat.id)
    # R5.4; R5.5 is the SERIALIZABLE default over the rows read above
    return insert(SeatHold(seat_id=seat.id, user_id=user_id, expires_at=now + HOLD))


# --------------------------------------------------------------------------- call site
async def post_hold(seat_id: UUID, show_id: UUID, user_id: Id[User]) -> None:
    await app.run(hold_seat.bind(seat=Seat.ref(seat_id), show=Show.ref(show_id), user_id=user_id))


# --------------------------------------------------------------------------- 4.12 unit tests
NOW = datetime(2026, 11, 26, 20, 0)


def test_free_seat_is_held() -> None:
    show = Show.stub(min_distance=0.0)
    seat = Seat.stub(show_id=show.id, blocked=False)
    r = hold_seat(seat, show, User.stub().id, holds=[], tickets=[], near=[], now=NOW)
    [hold] = r.inserted(SeatHold)
    assert hold.expires_at == NOW + HOLD


def test_unexpired_hold_of_another_user_blocks() -> None:
    show = Show.stub(min_distance=0.0)
    seat = Seat.stub(show_id=show.id, blocked=False)
    other = SeatHold.stub(seat_id=seat.id, expires_at=NOW + HOLD)
    with pytest.raises(SeatUnavailable):
        hold_seat(seat, show, User.stub().id, holds=[other], tickets=[], near=[], now=NOW)
