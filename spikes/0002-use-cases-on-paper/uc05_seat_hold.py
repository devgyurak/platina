"""Use case 5 - seat reservation (write skew, SERIALIZABLE). Requirements R5.1-R5.5.

Source: pretix/pretix `models/seating.py` `Seat.is_available`; callers in `services/orders.py`
`_check_positions` and `services/cart.py`. Rules restated, no code copied.
"""

from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

import pytest
from domain import (
    LineStatus,
    OrderStatus,
    Seat,
    SeatHold,
    SeatUnavailable,
    Show,
    Ticket,
    User,
)
from lib import INJECTED, App, Changes, Id, Load, Now, Profile, usecase

app = App(dsn="postgresql://app@primary/shop")

HOLD = timedelta(minutes=15)

# --- What R5.2 needs is two existence reads over predicates:
#   "an active ticket of a PENDING/PAID order holds this seat" and
#   "an unexpired hold of another user holds this seat".
# (a) A partial load with a predicate over a relation of the child (Ticket.order.status) and over
#     an injected value (`now`) cannot be declared: a `Profile` is static, it cannot name `now`,
#     and `Ticket.order.status` is not a column expression. This type-checks only because the
#     comparison is against a literal; the `now` form cannot be written at all.
active_tickets = Seat.tickets.where(Ticket.status == LineStatus.ACTIVE).exists()
# (b) Written instead: load the rows and decide in Python. Over-reads expired holds and the
#     tickets of cancelled orders; needs a nested path (`Ticket.order` under `Seat.tickets`),
#     which the design does not show.
seat_state = Profile(Seat.tickets, Ticket.order, Seat.holds)
# R5.3 needs "taken seats of the show near this seat": a range predicate on x/y relative to a row
# loaded in the same use case. It is written as "load the whole show".
show_state = Profile(Show.seats, Seat.tickets, Ticket.order, Seat.holds)

type HoldableSeat = Annotated[Seat, seat_state]
type ShowSeating = Annotated[Show, show_state]


def taken(seat: Seat, now: datetime, me: Id[User]) -> bool:
    by_ticket = any(
        t.status is LineStatus.ACTIVE and t.order.status in (OrderStatus.PENDING, OrderStatus.PAID)
        for t in seat.tickets
    )
    by_hold = any(h.expires_at >= now and h.user_id != me for h in seat.holds)
    return by_ticket or by_hold


@usecase
def hold_seat(
    seat: HoldableSeat, show: ShowSeating, user_id: Id[User], now: Now = INJECTED
) -> Changes:
    if seat.show_id != show.id:
        raise SeatUnavailable(seat.id)
    if seat.blocked and not show.allow_blocked:  # R5.1
        raise SeatUnavailable(seat.id)
    if taken(seat, now, user_id):  # R5.2
        raise SeatUnavailable(seat.id)
    if show.min_distance > 0:  # R5.3
        for other in show.seats:
            if other.id == seat.id or not taken(other, now, user_id):
                continue
            if show.distance_within_row and other.row != seat.row:
                continue
            if (other.x - seat.x) ** 2 + (other.y - seat.y) ** 2 < show.min_distance**2:
                raise SeatUnavailable(seat.id)
    # R5.4; R5.5 is the SERIALIZABLE default: the reads above are the predicate that a concurrent
    # hold of the same seat (or of a near seat) writes into, so one of the two must fail
    hold = SeatHold(seat_id=seat.id, user_id=user_id, expires_at=now + HOLD)
    return seat.set(Seat.holds.add(hold))


# --------------------------------------------------------------------------- call site
async def post_hold(seat_id: UUID, show_id: UUID, user_id: Id[User]) -> None:
    await app.run(hold_seat.bind(seat=Seat.ref(seat_id), show=Show.ref(show_id), user_id=user_id))


# --------------------------------------------------------------------------- 4.12 unit tests
NOW = datetime(2026, 11, 25, 20, 0)


def test_expired_hold_of_another_user_does_not_block() -> None:
    other = User.stub()
    show = Show.stub(min_distance=0.0)
    seat = Seat.stub(
        show_id=show.id,
        blocked=False,
        tickets=[],
        holds=[SeatHold.stub(user_id=other.id, expires_at=NOW - timedelta(seconds=1))],
    )
    me = User.stub()
    r = hold_seat(seat, show, me.id, now=NOW)
    [hold] = r.inserted(SeatHold)
    assert hold.expires_at == NOW + HOLD


def test_near_taken_seat_blocks_with_distance_rule() -> None:
    other = User.stub()
    taken_seat = Seat.stub(
        row="A",
        x=0.0,
        y=0.0,
        tickets=[],
        holds=[SeatHold.stub(user_id=other.id, expires_at=NOW + HOLD)],
    )
    seat = Seat.stub(row="A", x=1.0, y=0.0, blocked=False, tickets=[], holds=[])
    show = Show.stub(min_distance=1.5, seats=[taken_seat, seat])
    seat = Seat.stub(id=seat.id, show_id=show.id, row="A", x=1.0, y=0.0, tickets=[], holds=[])
    with pytest.raises(SeatUnavailable):
        hold_seat(seat, show, User.stub().id, now=NOW)


# a hold loaded with the seat is compared by ID, not with `==`: two stubs of "the same seat"
# (the seat as loaded alone and as loaded inside `show.seats`) are different snapshots (#54)
def test_seat_in_show_is_found_by_id() -> None:
    seat = Seat.stub(tickets=[], holds=[])
    show = Show.stub(seats=[Seat.stub(id=seat.id, tickets=[], holds=[], x=9.0)])
    assert [s.id for s in show.seats] == [seat.id]


_ = Load
