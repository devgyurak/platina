"""Reproduction of spike 0007: misuse neither checker rejects (R1-R9); both must accept every line."""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated
from uuid import UUID

from domain import Item, Money, Order, OrderStatus, Seat, SeatHold, Transfer, User
from lib import INJECTED, Changes, Id, Load, Now, RowSet, insert, usecase

NOW = datetime(2026, 11, 26)


def active_holds(seat: Seat, now: Now) -> RowSet[SeatHold]:
    return SeatHold.where(SeatHold.seat_id == seat.id, SeatHold.expires_at > now)


holds_load = Load.after(active_holds)
type ActiveHolds = Annotated[Sequence[SeatHold], holds_load]


@usecase
def hold(
    seat: Seat, user_id: Id[User], holds: ActiveHolds = INJECTED, now: Now = INJECTED
) -> Changes:
    return insert(SeatHold(seat_id=seat.id, user_id=user_id, expires_at=now))


@usecase
def note(order: Order, text: str = INJECTED) -> Changes:  # R4 INJECTED on a plain parameter
    return order.set(Order.number.to(text))


type WrongHolds = Annotated[list[Item], holds_load]  # R9 declared type is not the function's result


def r(oid: UUID, seat: Seat, uid: Id[User], m: Money, order: Order, item: Item) -> Changes:
    c1 = Order.ref(oid).delete()  # R1 delete on a ref
    hold.bind(
        seat=seat, user_id=uid, holds=[], now=NOW
    )  # R2 runner-filled parameters passed to bind
    hold(seat, uid)  # R3 direct call without the runner-filled parameters
    t = Transfer(amount=m)
    c5 = insert(t) + t.set(
        Transfer.amount.to(m)
    )  # R5 candidate A: column operation on a new entity
    Transfer(amount=m)  # R6 a new entity never inserted
    c7 = insert(order)  # R7 insert of a loaded snapshot
    c8 = Order.where(Order.status == OrderStatus.PENDING).set(Order.items.remove(item))  # R8
    return c1 + c5 + c7 + c8


@usecase
def r9(seat: Seat, holds: WrongHolds = INJECTED) -> Changes:  # R9 used
    return insert(holds[0])  # holds is list[Item] to both checkers
