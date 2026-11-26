"""Reproduction of spike 0007 (type-reviewer): lines both checkers must accept, S1-S8."""

from collections.abc import Sequence
from datetime import datetime
from typing import Annotated, assert_type
from uuid import UUID

from domain import (
    Account,
    Allocation,
    Item,
    Leg,
    LegSide,
    Money,
    Order,
    OrderExpired,
    OrderStatus,
    Payment,
    PaymentMethod,
    Refund,
    RefundTarget,
    Seat,
    SeatHold,
    Stock,
    Ticket,
    Transfer,
    User,
    Variant,
    Wallet,
    Warehouse,
)
from lib import (
    INJECTED,
    Changes,
    Id,
    Load,
    Now,
    Op,
    OwnedRelation,
    Pred,
    Profile,
    Relation,
    RelColumn,
    RelOp,
    RowSet,
    SetChange,
    insert,
    usecase,
)


# --- S1: Entity.delete() -> Changes
def s1(order: Order) -> Changes:
    assert_type(order.delete(), Changes)
    return order.delete()


# --- S2: Entity.where(...) -> RowSet[Self]: set, delete, load result
def s2(now: datetime) -> Changes:
    rows = Order.where(Order.status == OrderStatus.PENDING, Order.expires_at < now)
    assert_type(rows, RowSet[Order])
    assert_type(rows.delete(), Changes)
    expire = rows.set(Order.status.to(OrderStatus.EXPIRED)).emit_each(
        OrderExpired, order_id=Order.id
    )
    assert_type(expire, SetChange[Order])
    return expire + Order.where(Order.status == OrderStatus.CANCELLED).delete()


# --- S3: insert, candidates A and B
def s3_insert(seat: Seat, user: User, now: datetime) -> Changes:
    change = insert(SeatHold(seat_id=seat.id, user_id=user.id, expires_at=now))
    assert_type(change, Changes)
    return change


def s3_candidate_a(src: Account, dst: Account, m: Money) -> Changes:
    t = Transfer(amount=m)
    debit = Leg(account_id=src.id, side=LegSide.DEBIT, amount=m)
    credit = Leg(account_id=dst.id, side=LegSide.CREDIT, amount=m)
    return insert(t) + t.set(Transfer.legs.add(debit), Transfer.legs.add(credit))


def s3_candidate_b(src: Account, dst: Account, m: Money) -> Changes:
    t = Transfer(amount=m)
    debit = Leg(account_id=src.id, side=LegSide.DEBIT, amount=m)
    credit = Leg(account_id=dst.id, side=LegSide.CREDIT, amount=m)
    change = insert(t, Transfer.legs.add(debit), Transfer.legs.add(credit))
    assert_type(change, Changes)
    return change


# --- S4: relation operations only on owned relations
def s4(order: Order, item: Item) -> Changes:
    assert_type(Order.items, OwnedRelation[Order, Item])
    assert_type(Order.payments, Relation[Order, Payment])
    assert_type(Order.items.add(item), RelOp[Order])
    assert_type(order.items, Sequence[Item])
    assert_type(order.payments, Sequence[Payment])
    op: Op[Order] = Order.items.remove(item)  # a RelOp is an Op of the same owner
    new_item = Item(variant_id=item.variant_id, quantity=1, price=item.price, position=2)
    return order.set(Order.items.add(new_item), Order.items.update(item, Item.quantity.to(3)), op)


# --- S5: nested paths
def s5() -> None:
    assert_type(
        Order.items.load(Item.allocations.load(Allocation.stock)), OwnedRelation[Order, Item]
    )
    assert_type(Item.allocations.load(Allocation.stock), Relation[Item, Allocation])
    assert_type(Seat.tickets.load(Ticket.order), Relation[Seat, Ticket])
    assert_type(Ticket.order.load(Order.items), RelColumn[Ticket, Order])
    assert_type(Allocation.stock.load(Stock.warehouse), RelColumn[Allocation, Stock])


three_levels = Profile(
    Order.items.load(Item.allocations.load(Allocation.stock.load(Stock.warehouse)))
)


# --- S6: Load.after forms
def active_holds(seat: Seat, now: Now) -> RowSet[SeatHold]:
    return SeatHold.where(SeatHold.seat_id == seat.id, SeatHold.expires_at > now)


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


def payer_wallet(order: Order) -> Wallet | None:
    return None if order.user_id is None else Wallet.ref(order.user_id)


def stocks_of(order: Order) -> RowSet[Stock]:
    return Stock.where(Stock.variant_id.in_([i.variant_id for i in order.items]))


holds_load = Load.after(active_holds)
variants_load = Load.after(variants_of, Variant.stocks.load(Stock.warehouse))
wallet_after = Load.after(payer_wallet, missing="none")
stocks_load = Load.after(stocks_of, Stock.warehouse)
assert_type(holds_load, Load)


def s6(ids: list[Id[Variant]]) -> None:
    assert_type(Stock.variant_id.in_(ids), Pred[Stock])
    assert_type(Stock.warehouse, RelColumn[Stock, Warehouse])


# --- S7: missing="none" on Load.when
wallet_when = Load.when(
    Order.paid_with == PaymentMethod.WALLET, match=Wallet.user_id == Order.user_id, missing="none"
)
assert_type(Wallet.user_id == Order.user_id, Pred[Wallet | Order])

# --- S8: = INJECTED on dependent-load parameters; bind leaves them out
type ActiveHolds = Annotated[Sequence[SeatHold], holds_load]
type PointWallet = Annotated[Wallet | None, wallet_when]


@usecase
def hold(
    seat: Seat, user_id: Id[User], holds: ActiveHolds = INJECTED, now: Now = INJECTED
) -> Changes:
    assert_type(holds, Sequence[SeatHold])
    assert_type(now, datetime)
    return insert(SeatHold(seat_id=seat.id, user_id=user_id, expires_at=now))


@usecase
def refund(order: Order, wallet: PointWallet = INJECTED) -> Changes:
    assert_type(wallet, Wallet | None)
    target = RefundTarget.WALLET if wallet is not None else RefundTarget.MANUAL
    return insert(Refund(order_id=order.id, amount=order.total, target=target))


def s8(seat_id: UUID, user_id: Id[User], order_id: UUID) -> None:
    hold.bind(seat=Seat.ref(seat_id), user_id=user_id)
    refund.bind(order=Order.ref(order_id))
