"""Items 0-3 and 5-7: every negative line, with the codes each checker actually reports."""

from datetime import datetime
from uuid import UUID

from domain import (
    ChargeableWallet,
    Coupon,
    Item,
    Money,
    Order,
    OrderPaid,
    OrderStatus,
    PayableOrder,
    User,
    Wallet,
    apply_coupon,
    orders,
    pay,
    wallets,
)
from lib_design import INJECTED, Changes, Col, Id, Now, chain, column, entity, usecase


@entity(table="orders_d", aggregate_root=True)
class OrderD:
    number: Col[str] = column(unique=True, length=20)


@usecase
def pay2(order: PayableOrder, wallet: ChargeableWallet, now: Now = INJECTED) -> Changes:
    return order.set(Order.paid_at.to(now))


# fmt: off
def item0(oid: UUID, d: OrderD) -> None:
    OrderD.new(number="A-1")  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: decorator-only entity has no new
    OrderD.ref(oid)  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: no ref
    OrderD.where()  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: no where
    OrderD.stub()  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: no stub
    d.set()  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: no set


def item2(uid: Id[User], oid: Id[Order], money: Money, now: datetime, order: Order) -> None:
    Order.new(number="A-1")  # expect-error[reportCallIssue, call-arg]: total, user_id missing
    Order.new(number=1, total=money, user_id=uid)  # expect-error[reportArgumentType, arg-type]: int is not str
    Order.new(number="A-1", total=money, user_id=uid, version=3)  # expect-error[reportCallIssue, call-arg]: version_column is init=False
    Order.new(number="A-1", total=money, user_id=uid, id=oid)  # expect-error[reportCallIssue, call-arg]: generated pk is init=False
    Order.new(number="A-1", total=money, user_id=uid, created_at=now)  # expect-error[reportCallIssue, call-arg]: server_default is init=False
    Order.new(number="A-1", total=money, user_id=uid, items=[])  # expect-error[reportCallIssue, call-arg]: relation is init=False
    Order.new("A-1", money, uid)  # expect-error[reportCallIssue, call-arg, arg-type]: keyword only (mypy adds arg-type per position)
    OrderPaid(order_id=oid, user_id=uid, total=money)  # expect-error[reportCallIssue, call-arg]: paid_at missing
    order.status = OrderStatus.PAID  # expect-error[reportAttributeAccessIssue, arg-type]: __set__ instance is Never


def item3(order: Order, item: Item) -> None:
    Order.status.to(123)  # expect-error[reportArgumentType, arg-type]: int is not OrderStatus
    order.status = OrderStatus.PAID  # expect-error[reportAttributeAccessIssue, arg-type]: immutable
    order.items.append(item)  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: Sequence has no append
    Order.number.to(None)  # expect-error[reportArgumentType, arg-type]: None is not str
    Order.status.to("paid")  # expect-error[reportArgumentType, arg-type]: str is not OrderStatus


def item5(oid: UUID, uid: Id[User]) -> None:
    pay.bind(order=oid, wallet=wallets.by_user(uid))  # expect-error[reportArgumentType, arg-type]: UUID is not Order
    pay.bind(ordr=Order.ref(oid), wallet=wallets.by_user(uid))  # expect-error[reportCallIssue, call-arg]: name typo
    pay.bind(order=Order.ref(oid))  # expect-error[reportCallIssue, call-arg]: wallet missing
    pay.bind(order=wallets.by_user(uid), wallet=Order.ref(oid))  # expect-error[reportArgumentType, arg-type]: swapped
    pay.bind(order=Order.ref(oid), wallet=wallets.by_user(uid), now="now")  # expect-error[reportArgumentType, arg-type]: str is not datetime
    pay2.bind(order=oid, wallet=wallets.by_user(uid))  # expect-error[reportArgumentType, arg-type]: options form, UUID is not Order


@usecase  # expect-error[reportArgumentType, arg-type]: a use case must return Changes
def not_changes(order: Order) -> int:
    return 1


def item6(order: Order, wallet: Wallet, coupon: Coupon) -> None:
    with chain(order, wallet) as (c, o2, w2):
        c.run(apply_coupon, coupon, o2)  # expect-error[reportArgumentType, arg-type]: swapped
        c.run(apply_coupon, o2)  # expect-error[reportCallIssue, call-arg]: coupon missing
        c.run(apply_coupon, o2, coupon, 1)  # expect-error[reportCallIssue, call-arg]: one too many
        c.run(pay, o2, w2)
    with chain(order, wallet) as (c4, x):  # expect-error[reportAssignmentType, misc]: unpacking arity
        c4.run(apply_coupon, x, coupon)
    with chain(order, wallet) as (c5, wallet, order):  # expect-error[reportAssignmentType, assignment]: swapped rebinding
        c5.run(pay, order, wallet)


def item7(order: Order, wallet: Wallet, coupon: Coupon, oid: Id[Order], raw: UUID) -> None:
    apply_coupon(order, coupon) + pay(order, wallet)  # expect-error[reportOperatorIssue, reportUnusedExpression, operator]: StepResult has no +
    order.set() + pay(order, wallet)  # expect-error[reportOperatorIssue, reportUnusedExpression, operator]: Changes + StepResult
    orders.by_number(42)  # expect-error[reportArgumentType, arg-type]: int is not str
    wallets.by_user(oid)  # expect-error[reportArgumentType, arg-type]: Id[Order] is not Id[User]
    wallets.by_user(raw)  # expect-error[reportArgumentType, arg-type]: plain UUID is not Id[User]
# fmt: on
