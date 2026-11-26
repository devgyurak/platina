"""Spike 0007: misuse the decisions reject at seal or at run time, which both checkers accept.

Every line here type-checks under both checkers (run through `tools.typetests` as a pass file);
the comment names who rejects it instead. These are the places where a shape cannot remove the
mistake and the runtime check of the decision is the last resort.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from domain import (
    Account,
    Item,
    Leg,
    LegSide,
    Money,
    Order,
    OrderStatus,
    Seat,
    SeatHold,
    Transfer,
    User,
)
from lib import INJECTED, Changes, Id, Load, Now, Profile, RowSet, insert, insert_all, usecase

NOW = datetime(2026, 11, 26)


def active_holds(seat: Seat, now: Now) -> RowSet[SeatHold]:
    return SeatHold.where(SeatHold.seat_id == seat.id, SeatHold.expires_at > now)


@usecase
def hold(
    seat: Annotated[Seat, Load()],
    user_id: Id[User],
    holds: Annotated[list[SeatHold], Load.after(active_holds)] = INJECTED,
    now: Now = INJECTED,
) -> Changes:
    return insert(SeatHold(seat_id=seat.id, user_id=user_id, expires_at=now))


# R1 #57: `.delete()` on a ref - a ref is an entity at the type level (UnloadedReference at run time)
def r1(order_id: UUID) -> Changes:
    return Order.ref(order_id).delete()


# R2 #48: a runner-filled parameter passed to `bind` (UsageError raised by `bind`)
hold.bind(seat=Seat.ref(UUID(int=1)), user_id=User.stub().id, holds=[], now=NOW)


# R3 #48: a direct call that leaves a runner-filled parameter out (UsageError from the wrapper)
r3 = hold(Seat.stub(), User.stub().id)


# R4 #48: `= INJECTED` on a parameter the runner does not fill (SealError)
@usecase
def r4(order: Annotated[Order, Load()], note: str = INJECTED) -> Changes:
    return order.set(Order.status.to(OrderStatus.PAID))


# R5 #60: `.set` on a new entity with a column operation (its values belong in the constructor).
# Candidate A's rule: `.set` on a new entity takes relation operations only; under B it is R13's
# rule (`.set` on a new entity is an error). Inside `insert`, B rejects it by type (F10)
def r5(amount: Money) -> Changes:
    t = Transfer(amount=amount)
    return insert(t) + t.set(Transfer.amount.to(amount))


# R6 #60: a created entity that is never inserted (UsageError when the step ends)
def r6(order: Order, amount: Money) -> Changes:
    Transfer(amount=amount)
    return order.set(Order.status.to(OrderStatus.PAID))


# R7 #60: `insert` of a loaded snapshot or a ref (it is an entity at the type level)
def r7(order: Order) -> Changes:
    return insert(order)


# R9 #59: the declared parameter type and the function's result do not match (seal; spike 0002
# X13 item 1): the function returns a row set of SeatHold, the parameter says `list[Item]`
@usecase
def r9(
    seat: Annotated[Seat, Load()], holds: Annotated[list[Item], Load.after(active_holds)] = INJECTED
) -> Changes:
    return Changes()


# R10 #57 / #60: an owned child deleted directly - a second way next to `Order.items.remove(item)`
def r10(item: Item) -> Changes:
    return item.delete()


# R11 #60: an owned child written directly, not through its root (no root version bump)
def r11(item: Item) -> Changes:
    return item.set(Item.quantity.to(1))


# R12 #60: an owned child inserted directly - it has no parent key (#49)
def r12(src: Account, amount: Money) -> Changes:
    return insert(Leg(account_id=src.id, side=LegSide.CREDIT, amount=amount))


# R13 #60 candidate B: `.set` on a new entity (B's rule: an error; its children go into `insert`)
def r13(src: Account, amount: Money) -> Changes:
    t = Transfer(amount=amount)
    return insert(t) + t.set(
        Transfer.legs.add(Leg(account_id=src.id, side=LegSide.CREDIT, amount=amount))
    )


# R14 #60: `insert_all` with a root and an owned child - the bulk path around the owned-root rule
def r14(src: Account, amount: Money) -> Changes:
    t = Transfer(amount=amount)
    return insert_all([t, Leg(account_id=src.id, side=LegSide.CREDIT, amount=amount)])


# R15 #59 point 1: a flat path list - ambiguous, made a seal error by the decision
r15 = Profile(Order.items, Item.allocations)
