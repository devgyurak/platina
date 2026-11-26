"""Spike 0007: the shapes of #48, #57, #59 and #60 that both checkers must accept.

Each line pins what the checkers infer with `assert_type` (an inference that differs is an error
in that checker). Run with `uv run python -m tools.typetests` (see the write-up).
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Annotated, assert_type
from uuid import UUID

from domain import (
    Account,
    Allocation,
    Coupon,
    CouponRedemption,
    Item,
    Leg,
    LegSide,
    Money,
    Order,
    OrderExpired,
    OrderStatus,
    Payment,
    PaymentMethod,
    Seat,
    SeatHold,
    Show,
    Stock,
    Ticket,
    Transfer,
    User,
    Variant,
    Wallet,
    wallets,
)
from lib import (
    INJECTED,
    AddOp,
    Changes,
    Col,
    Entity,
    Id,
    Load,
    Now,
    Owned,
    OwnedRelation,
    Pred,
    Profile,
    Relation,
    RelColumn,
    RelOp,
    RowSet,
    SetChange,
    insert,
    owns_many,
    pk,
    usecase,
)

NOW = datetime(2026, 11, 26)


# --------------------------------------------------------------------------- #57 delete
def p57_row_delete(order: Order) -> Changes:
    return assert_type(order.delete(), Changes)  # S1: a loaded root


def p57_set_level_delete() -> Changes:
    rows = Order.where(Order.status == OrderStatus.EXPIRED)
    assert_type(rows, RowSet[Order])  # S2: a row set, not a Changes
    return assert_type(rows.delete(), Changes)  # S2


def p57_set_change_still_reads_as_4_3() -> Changes:
    change = (
        Order.where(Order.status == OrderStatus.PENDING, Order.expires_at < NOW)
        .set(Order.status.to(OrderStatus.EXPIRED))
        .emit_each(OrderExpired, order_id=Order.id)
    )
    return assert_type(change, SetChange[Order])  # S2: design 4.3's set change unchanged


# --------------------------------------------------------------------------- #60 insert
def p60_insert_one_row(seat: Seat, user: User) -> Changes:
    hold = SeatHold(seat_id=seat.id, user_id=user.id, expires_at=NOW)
    return assert_type(insert(hold), Changes)  # S3: a non-owned row, written directly


def p60_candidate_a(src: Account, amount: Money) -> Changes:
    t = Transfer(amount=amount)
    leg = Leg(account_id=src.id, side=LegSide.CREDIT, amount=amount)  # #49: no transfer_id
    return insert(t) + assert_type(t.set(Transfer.legs.add(leg)), Changes)  # S3 candidate A


def p60_candidate_b(src: Account, amount: Money) -> Changes:
    t = Transfer(amount=amount)
    leg = Leg(account_id=src.id, side=LegSide.CREDIT, amount=amount)
    return assert_type(insert(t, Transfer.legs.add(leg)), Changes)  # S3 candidate B


# --------------------------------------------------------------------------- #60 point 4 relation types
assert_type(Order.items, OwnedRelation[Order, Item])  # S4: owned=True
assert_type(Order.payments, Relation[Order, Payment])  # S4: not owned
assert_type(Order.items.add(Item.stub()), AddOp[Order])  # S4: `add` is the AddOp insert takes
assert_type(Order.items.remove(Item.stub()), RelOp[Order])  # S4
assert_type(Order.user, RelColumn[Order, User | None])  # unchanged single-valued relation


def p60_owned_child_update(order: Order, item: Item) -> Changes:
    return order.set(Order.items.update(item, Item.quantity.to(2)))  # S4: through the root


def p60_non_owned_row_directly(payment: Payment) -> Changes:
    return payment.set(Payment.provider_ref.to("x")) + payment.delete()  # S4: written directly


class S4bOrder(Entity, table="s4b_orders"):  # S4 alternative: a separate specifier, no flag
    id: Col[Id[S4bOrder]] = pk()
    items: Owned[list[Item]] = owns_many(lambda: Item.order_id)


assert_type(S4bOrder.items, OwnedRelation[S4bOrder, Item])


# --------------------------------------------------------------------------- #59 point 1 nested paths
deep = Order.items.load(Item.allocations.load(Allocation.stock))
assert_type(deep, Relation[Order, Item])  # S5: three levels; a load path is read-only
assert_type(Seat.tickets.load(Ticket.order), Relation[Seat, Ticket])  # S5: a many-to-one step
assert_type(Ticket.order.load(Order.items), RelColumn[Ticket, Order])  # S5: from a many-to-one
assert_type(Order.show.load(Show.seats), RelColumn[Order, Show | None])  # S5: nullable many-to-one
assert_type(Order.user.load(User.addresses), RelColumn[Order, User | None])  # S5
releasable = Profile(deep, Order.show)  # S5: as a profile


# --------------------------------------------------------------------------- #59 points 2, 3 dependent loads
def active_holds(seat: Seat, now: Now) -> RowSet[SeatHold]:
    return SeatHold.where(SeatHold.seat_id == seat.id, SeatHold.expires_at > now)  # S6 row set


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]  # S6 list of refs


def point_wallet(order: Order) -> Wallet | None:
    return wallets.by_user(order.user_id) if order.user_id is not None else None  # S6 one ref


def redemption_of(coupon: Coupon, user: User) -> RowSet[CouponRedemption]:
    return CouponRedemption.where(
        CouponRedemption.coupon_id == coupon.id, CouponRedemption.user_id == user.id
    )  # S6: "absent" is an empty set


def stocks_of(order: Order) -> RowSet[Stock]:
    return Stock.where(Stock.variant_id.in_([i.variant_id for i in order.items]))  # S6 + in_


holds_load = Load.after(active_holds)  # S6
variants_load = Load.after(variants_of, Variant.stocks.load(Stock.warehouse))  # S6 + load args
wallet_load = Load.after(point_wallet, missing="none")  # S6 one ref, missing
stocks_load = Load.after(stocks_of, Stock.warehouse)  # S6 row set + load args
when_none = Load.when(
    Order.paid_with == PaymentMethod.WALLET,
    match=Wallet.user_id == Order.user_id,  # #51 overload (nullable on one side)
    missing="none",  # S7: `missing` on Load.when
)
assert_type(Wallet.user_id == Order.user_id, Pred[Wallet | Order])  # #51 shape, as given
assert_type(Stock.variant_id.in_([]), Pred[Stock])
assert_type(Stock.allocated <= Stock.quantity, Pred[Stock])  # #51, spike 0006's overloads


def variants_tuple(order: Order) -> tuple[Variant, ...]:
    return tuple(Variant.ref(i.variant_id) for i in order.items)  # S6: any Sequence of refs


variants_seq_load = Load.after(
    variants_tuple, Variant.stocks
)  # S6 round 4: Sequence, not only list

type ActiveHolds = Annotated[Sequence[SeatHold], holds_load]
type PointWallet = Annotated[Wallet | None, wallet_load]


# --------------------------------------------------------------------------- #48 INJECTED on dependent loads
@usecase
def hold(
    seat: Annotated[Seat, Load()],
    user_id: Id[User],
    holds: ActiveHolds = INJECTED,
    now: Now = INJECTED,
) -> Changes:
    assert_type(holds, Sequence[SeatHold])  # S8: the parameter's type inside
    assert_type(now, datetime)
    return insert(SeatHold(seat_id=seat.id, user_id=user_id, expires_at=now))


@usecase
def refund(order: Annotated[Order, Load(Order.items)], wallet: PointWallet = INJECTED) -> Changes:
    changes = order.set(Order.status.to(OrderStatus.CANCELLED))
    if wallet is not None:
        changes += wallet.set(Wallet.balance.path(Money.amount).add(Decimal(1)))
    return changes


hold.bind(
    seat=Seat.ref(UUID(int=1)), user_id=User.stub().id
)  # S8: dependent load and injected value omitted
refund.bind(order=Order.ref(UUID(int=1)))  # S8: 4.7's example with `= INJECTED`
