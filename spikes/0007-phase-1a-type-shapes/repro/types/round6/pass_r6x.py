"""Spike 0007 type reproduction, round 6 (type-reviewer): lines both checkers must accept.

The receiver form `Load.after(fn, missing=...) -> LoadAfter[E]` with `.load(*paths: LoadPath[E])`,
on the reproducer's own copy of the round-5 stub (`lib.pyi` here). Q2 of the write-up, and the
reproducer's own lines (marked "own").
"""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, assert_type
from uuid import UUID

from domain import Order, Seat, SeatHold, Show, Stock, Ticket, User, Variant, Wallet, wallets
from lib import INJECTED, Changes, Load, LoadAfter, Now, RowSet, insert, usecase

NOW = datetime(2026, 11, 26)


def holds_of(seat: Seat, now: Now) -> RowSet[SeatHold]:
    return SeatHold.where(SeatHold.seat_id == seat.id, SeatHold.expires_at > now)


def seats_near(seat: Seat) -> RowSet[Seat]:
    return Seat.where(Seat.show_id == seat.show_id)


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


def variants_tuple(order: Order) -> tuple[Variant, ...]:
    return tuple(Variant.ref(i.variant_id) for i in order.items)


def point_wallet(order: Order) -> Wallet | None:
    return wallets.by_user(order.user_id) if order.user_id is not None else None


def order_of(ticket: Ticket) -> Order | None:
    return Order.ref(ticket.order_id)


def ticket_order(ticket: Ticket) -> Order:
    return Order.ref(ticket.order_id)


def shows_of(order: Order) -> RowSet[Show]:
    return Show.where(Show.name == order.number)


def show_of(order: Order) -> Show | None:
    return Show.ref(order.show_id) if order.show_id is not None else None


def open_orders(user: User) -> RowSet[Order]:
    return Order.where(Order.user_id == user.id)


# Q2: the three return forms, bare and with load arguments
assert_type(Load.after(holds_of), LoadAfter[SeatHold])
assert_type(Load.after(variants_of), LoadAfter[Variant])
assert_type(Load.after(variants_tuple), LoadAfter[Variant])
assert_type(Load.after(point_wallet, missing="none"), LoadAfter[Wallet])
assert_type(Load.after(point_wallet), LoadAfter[Wallet])
assert_type(Load.after(ticket_order), LoadAfter[Order])  # own: a non-optional one ref
assert_type(Load.after(seats_near).load(Seat.holds), LoadAfter[Seat])
assert_type(Load.after(variants_of).load(Variant.stocks), LoadAfter[Variant])
assert_type(Load.after(order_of, missing="none").load(Order.items), LoadAfter[Order])

# Q2: nested, three levels through a many-to-one, chained
assert_type(Load.after(variants_of).load(Variant.stocks.load(Stock.warehouse)), LoadAfter[Variant])
three = Load.after(seats_near).load(Seat.tickets.load(Ticket.order.load(Order.items)))
assert_type(three, LoadAfter[Seat])
assert_type(Load.after(seats_near).load(Seat.holds).load(Seat.tickets), LoadAfter[Seat])

# Q2: nested paths through the nullable many-to-one relations `Order.show`, `Order.user`
nullable = Load.after(open_orders).load(
    Order.show.load(Show.seats), Order.user.load(User.addresses)
)
assert_type(nullable, LoadAfter[Order])

# own: the entity of a nullable relation as the function's result (row set and one ref)
assert_type(Load.after(shows_of).load(Show.seats.load(Seat.holds)), LoadAfter[Show])
assert_type(Load.after(show_of, missing="none").load(Show.seats), LoadAfter[Show])

# own: `.load()` with no paths (as `Order.items.load()`), and a LoadAfter where a Load is expected
assert_type(Load.after(variants_of).load(), LoadAfter[Variant])
as_load: Load = Load.after(variants_of).load(Variant.stocks)
seats_load = Load.after(seats_near).load(Seat.holds)
holds_load = Load.after(holds_of)

type NearSeats = Annotated[Sequence[Seat], seats_load]
type ActiveHolds = Annotated[Sequence[SeatHold], holds_load]


@usecase
def hold(
    seat: Annotated[Seat, Load()],
    user_id: UUID,
    near: NearSeats = INJECTED,
    holds: ActiveHolds = INJECTED,
    now: Now = INJECTED,
) -> Changes:
    assert_type(near, Sequence[Seat])
    assert_type(holds, Sequence[SeatHold])
    return insert(SeatHold(seat_id=seat.id, user_id=User.stub().id, expires_at=now))


hold.bind(seat=Seat.ref(UUID(int=1)), user_id=UUID(int=2))
