"""Spike 0007 type reproduction, round 2: misuse neither checker rejects (R1-R15, no R8)."""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated
from uuid import UUID

from domain import (
    Account,
    Allocation,
    Item,
    Leg,
    LegSide,
    Money,
    Order,
    Seat,
    SeatHold,
    Transfer,
    User,
)
from lib import INJECTED, Changes, Id, Load, Now, Profile, RowSet, insert, insert_all, usecase

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
    return c1 + c5 + c7


def r10(item: Item, m: Money, a: Account) -> Changes:
    c10 = item.delete()  # R10 delete of an owned child, not through its root
    c11 = item.set(Item.quantity.to(1))  # R11 set on an owned child, not through its root
    leg = Leg(account_id=a.id, side=LegSide.DEBIT, amount=m)
    c12 = insert(leg)  # R12 an owned child inserted directly
    t = Transfer(amount=m)
    c13 = insert(t) + t.set(Transfer.legs.add(leg))  # R13 candidate B: .set on a new entity
    c14 = insert_all([t, Leg(account_id=a.id, side=LegSide.CREDIT, amount=m)])  # R14 bulk path
    return c10 + c11 + c12 + c13 + c14


flat = Profile(Order.items, Item.allocations, Allocation.stock)  # R15 the flat path (seal)


@usecase
def r9(seat: Seat, holds: WrongHolds = INJECTED) -> Changes:  # R9 used
    return insert(holds[0])  # holds is list[Item] to both checkers
