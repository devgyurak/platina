"""Spike 0007 type reproduction, round 3: lines both checkers must reject."""

from decimal import Decimal
from uuid import UUID

from domain import (
    Account,
    Allocation,
    Item,
    Leg,
    LegSide,
    Money,
    Order,
    OrderStatus,
    Payment,
    PaymentMethod,
    Seat,
    SeatHold,
    Stock,
    Transfer,
    User,
    Variant,
    Wallet,
)
from lib import (
    INJECTED,
    Changes,
    Col,
    Entity,
    Id,
    Load,
    Now,
    Op,
    Owned,
    Profile,
    Rel,
    RelOp,
    RowSet,
    column,
    insert,
    one_to_many,
    owns_many,
    pk,
    usecase,
)


def active_holds(seat: Seat, now: Now) -> RowSet[SeatHold]:
    return SeatHold.where(SeatHold.seat_id == seat.id, SeatHold.expires_at > now)


def variants_of(order: Order) -> list[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


def payer_wallet(order: Order) -> Wallet | None:
    return None if order.user_id is None else Wallet.ref(order.user_id)


def one_wallet(order: Order) -> Wallet:
    return Wallet.ref(order.id)


def stocks_of(order: Order) -> RowSet[Stock]:
    return Stock.where(Stock.variant_id.in_([i.variant_id for i in order.items]))


@usecase
def hold(seat: Seat, now: Now = INJECTED) -> Changes:
    return insert(SeatHold(seat_id=seat.id, user_id=Id[User](int=0), expires_at=now))


# fmt: off
def f1() -> Changes:
    return Order.where(Order.status == OrderStatus.PENDING)  # expect-error[reportReturnType, return-value]: F1 a row set is not Changes


def f2(order: Order) -> Changes:
    return Order.where(Order.status == OrderStatus.PENDING) + order.delete()  # expect-error[reportOperatorIssue, reportUnknownVariableType, operator, no-any-return]: F2 a row set has no +


def f3(m: Money, seat: Seat) -> None:
    Order.where(Order.status == OrderStatus.PENDING).set(Wallet.balance.to(m))  # expect-error[reportArgumentType, arg-type]: F3 Op[Wallet] in a row set of Order
    SeatHold.where(Seat.id == seat.id)  # expect-error[reportArgumentType, arg-type]: F4 Pred[Seat] in SeatHold.where


def f5(order: Order, payment: Payment, item: Item, stock: Stock) -> None:
    Order.payments.add(payment)  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: F5 add on a relation that is not owned
    Item.allocations.remove(Allocation(item_id=item.id, stock_id=stock.id, quantity=1))  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: F6 remove on a relation that is not owned
    Variant.stocks.update(stock, Stock.quantity.to(1))  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: F7 update on a relation that is not owned


class BadOwned(Entity, table="bad"):
    id: Col[Id[BadOwned]] = pk(generated="uuid7")
    items: Rel[list[Item]] = one_to_many(lambda: Item.order_id, owned=True)  # expect-error[reportAssignmentType, reportUnknownVariableType, assignment]: F8 owned=True is an Owned[...]
    lines: Owned[list[Item]] = one_to_many(lambda: Item.order_id)  # expect-error[reportAssignmentType, reportUnknownVariableType, assignment]: F9 Owned[...] without owned=True


def f10(src: Account, m: Money, item: Item) -> None:
    t = Transfer(amount=m)
    insert(t, Transfer.amount.to(m))  # expect-error[reportArgumentType, arg-type]: F10 a column operation in insert
    insert(t, Order.items.add(item))  # expect-error[reportArgumentType, arg-type, misc]: F11 another entity's relation operation in insert
    Leg(transfer_id=t.id, account_id=src.id, side=LegSide.DEBIT, amount=m)  # expect-error[reportCallIssue, call-arg]: F12 parent key is not a constructor parameter


def f13() -> None:
    Order.items.load(Order.payments)  # expect-error[reportArgumentType, arg-type]: F13 a path of Order under items
    Order.items.load(Allocation.stock)  # expect-error[reportArgumentType, arg-type]: F14 skips a level
    Order.items.load(Item.allocations.load(Stock.warehouse))  # expect-error[reportArgumentType, arg-type]: F15 wrong owner one level deeper
    Profile(Order.items.load(Allocation.stock))  # expect-error[reportArgumentType, arg-type]: F16 skipped level inside Profile


f17 = Load.after(variants_of, Order.items)  # expect-error[reportArgumentType, reportCallIssue, reportUnknownVariableType, arg-type]: F17 not a path of Variant
f18 = Load.after(active_holds, missing="none")  # expect-error[reportArgumentType, reportCallIssue, call-overload]: F18 missing= on a row set
f19 = Stock.variant_id.in_([Decimal(1)])  # expect-error[reportArgumentType, list-item, arg-type]: F19 values of another type
f20 = Load.when(Order.paid_with == PaymentMethod.WALLET, match=Wallet.user_id == Order.user_id, missing="skip")  # expect-error[reportArgumentType, arg-type]: F20 not a missing= value


# own additions (E1-E8)
def e1(order: Order, item: Item, payment: Payment, m: Money, leg: Leg) -> None:
    order.set(Order.payments.add(payment))  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownArgumentType, attr-defined]: E1 add on a relation that is not owned, inside set
    order.set(Wallet.balance.to(m))  # expect-error[reportArgumentType, arg-type]: E2 still owner-checked
    insert(Order.where(Order.status == OrderStatus.PENDING))  # expect-error[reportArgumentType, arg-type, type-var]: E3 a row set is not an entity
    Order.items.add(leg)  # expect-error[reportArgumentType, arg-type]: E4 a child of another relation
    order.items.add(item)  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: E5 instance access is a Sequence


e7 = Load.after(variants_of, missing="none")  # expect-error[reportArgumentType, reportCallIssue, call-overload]: E7 missing= on a list of refs
e6: RelOp[Entity] = Order.items.remove(Item.ref(UUID(int=0)))  # expect-error[reportAssignmentType, assignment]: E6 RelOp is invariant in its owner
hold.bind(seat=Seat.ref(UUID(int=0)), extra=1)  # expect-error[reportCallIssue, call-arg]: E8 unknown keyword in bind


# round 2: F21-F29
f21 = Load.after(payer_wallet, Order.items)  # expect-error[reportArgumentType, reportCallIssue, reportUnknownVariableType, arg-type]: F21 not a path of Wallet (one-ref form)
f22 = Load.after(payer_wallet, Order.items, missing="none")  # expect-error[reportArgumentType, arg-type, call-overload]: F22 the same with missing=
f23 = Load.after(stocks_of, Order.items)  # expect-error[reportArgumentType, reportCallIssue, reportUnknownVariableType, arg-type, misc]: F23 not a path of Stock (row-set form)


def f24(m: Money, leg: Leg, item: Item, order: Order) -> None:
    t = Transfer(amount=m)
    insert(t, Transfer.legs.remove(leg))  # expect-error[reportArgumentType, arg-type]: F24 insert takes add only
    Order.items.where(Item.quantity > 1).add(item)  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: F25 a write through a where view
    Order.items.load(Item.allocations).remove(item)  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: F26 a write through a load view
    Order.where(Order.status == OrderStatus.PENDING).set(Order.items.remove(item))  # expect-error[reportArgumentType, arg-type]: F27 a relation operation in a set change


class F28Order(Entity, table="f28"):
    id: Col[Id[F28Order]] = pk(generated="uuid7")
    items: Rel[list[Item]] = owns_many(lambda: Item.order_id)  # expect-error[reportAssignmentType, reportUnknownVariableType, assignment]: F28 owns_many is Owned[...]


class F29Order(Entity, table="f29"):
    id: Col[Id[F29Order]] = pk(generated="uuid7")
    delete: Col[bool] = column(default=False)  # expect-error[reportIncompatibleMethodOverride, assignment]: F29 delete is reserved


# round 2: the reproducer's own
e9 = Load.after(one_wallet, Order.items)  # expect-error[reportArgumentType, reportCallIssue, reportUnknownVariableType, arg-type]: E9 one-ref form, function without None


def e10(m: Money, leg: Leg, item: Item, order: Order, stock: Stock) -> None:
    t = Transfer(amount=m)
    insert(t, Transfer.legs.update(leg))  # expect-error[reportArgumentType, arg-type]: E10 update is not an AddOp
    Order.items.update(item, Transfer.legs.add(leg))  # expect-error[reportArgumentType, arg-type]: E11 another owner's operation inside update
    x: Op[Order] = Order.items.add(item)  # expect-error[reportAssignmentType, assignment]: E14 a RelOp is not an Op
    order.set(Order.items.add(item), x)


def e13() -> RowSet[Stock]:
    return Entity.where(Stock.quantity > 0)  # expect-error[reportReturnType, return-value]: E13 RowSet is invariant


class E12Order(Entity, table="e12"):
    id: Col[Id[E12Order]] = pk(generated="uuid7")
    set: Col[int] = column(default=0)  # expect-error[reportIncompatibleMethodOverride, assignment]: E12 set is reserved too
# fmt: on
