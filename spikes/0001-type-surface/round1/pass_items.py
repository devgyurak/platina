"""Items 0-3 and 5-7: every positive line and every observation, pinned under both checkers."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Never, assert_type
from uuid import UUID

from domain import (
    Coupon,
    Item,
    Money,
    Order,
    OrderPaid,
    OrderRepo,
    OrderStatus,
    PaymentMethod,
    User,
    Wallet,
    apply_coupon,
    orders,
    pay,
    wallets,
)
from lib_design import (
    INJECTED,
    Bound,
    BoundFinder,
    Chain,
    ChainBlock,
    Changes,
    Column,
    Expr,
    Finder,
    Id,
    Op,
    Relation,
    RelColumn,
    SetChange,
    StepResult,
    chain,
)


def item0(oid: UUID, order: Order) -> None:
    assert_type(Order.ref(oid), Order)
    assert_type(Order.ref(oid, expected_version=3), Order)
    assert_type(Order.where(Order.status == OrderStatus.PENDING), SetChange)
    assert_type(Order.stub(), Order)
    assert_type(order.set(Order.status.to(OrderStatus.PAID)), Changes)


def item1(order: Order, item: Item, paid: OrderPaid) -> None:
    assert_type(Order.status, Column[OrderStatus])
    assert_type(order.status, OrderStatus)
    assert_type(Order.paid_with, Column[PaymentMethod | None])
    assert_type(order.paid_at, datetime | None)
    assert_type(order.id, Id[Order])
    assert_type(Order.total, Column[Money])
    assert_type(order.total, Money)
    assert_type(Order.items, Relation[Item])
    assert_type(order.items, Sequence[Item])
    assert_type(Order.user, RelColumn[User])
    assert_type(order.user, User)
    assert_type(Order.items.add(item), Op)
    assert_type(Order.items.remove(item), Op)
    assert_type(Order.items.update(item, Item.position.to(2)), Op)
    assert_type(Order.items.count(), Expr)
    assert_type(OrderPaid.order_id, Column[Id[Order]])
    assert_type(paid.order_id, Id[Order])


def item2(uid: Id[User], oid: Id[Order], money: Money, now: datetime) -> None:
    assert_type(Order.new(number="A-1", total=money, user_id=uid), Order)
    assert_type(
        Order.new(
            number="A-1",
            total=money,
            user_id=uid,
            status=OrderStatus.PAID,
            paid_with=None,
            paid_at=now,
        ),
        Order,
    )
    assert_type(Item.new(order_id=oid, position=1, price=money), Item)
    assert_type(OrderPaid(order_id=oid, user_id=uid, total=money, paid_at=now), OrderPaid)
    assert_type(Money(Decimal("1000")), Money)
    # observations: accepted, although the design has one creation way and a typed stub in mind
    assert_type(Order(number="A-1", total=money, user_id=uid), Order)
    assert_type(Order.stub(statuss=1), Order)


def item3(order: Order, item: Item, now: datetime, money: Money) -> None:
    assert_type(order.set(Order.status.to(OrderStatus.PAID), Order.paid_at.to(now)), Changes)
    assert_type(order.set(Order.items.add(item)), Changes)
    assert_type(Order.paid_at.to(None), Op)
    # observation: the entity an operation belongs to is not checked
    assert_type(order.set(Wallet.balance.to(money)), Changes)


def item5(oid: UUID, uid: Id[User], order: Order, wallet: Wallet, now: datetime) -> None:
    assert_type(INJECTED, Never)  # Never is assignable to every type: that is how the default fits
    assert_type(wallets.by_user(uid), Wallet)
    assert_type(pay.bind(order=Order.ref(oid), wallet=wallets.by_user(uid)), Bound)
    assert_type(pay(order, wallet, now=now), StepResult)
    # observations: accepted
    assert_type(pay.bind(order=Order.ref(oid), wallet=wallets.by_user(uid), now=now), Bound)
    assert_type(pay.bind(Order.ref(oid), wallets.by_user(uid)), Bound)
    assert_type(pay(order, wallet), StepResult)


def item6(order: Order, wallet: Wallet, coupon: Coupon, now: datetime) -> None:
    assert_type(chain(order, wallet), ChainBlock[Order, Wallet])
    with chain(order, wallet) as (c, o2, w2):
        assert_type(c, Chain)
        assert_type(o2, Order)
        assert_type(w2, Wallet)
        c.run(apply_coupon, o2, coupon)
        c.run(pay, o2, w2, now)
        c.run(pay, o2, w2)
        c.run(pay, order=o2, wallet=w2)
    assert_type(c.changes, Changes)
    with chain(order, wallet, coupon) as (c3, a, b, d):
        assert_type((a, b, d), tuple[Order, Wallet, Coupon])
        c3.run(apply_coupon, a, d)
    with chain(order, wallet) as (c4, order, wallet):
        assert_type(order, Order)
        assert_type(wallet, Wallet)
        c4.run(pay, order, wallet)


def item7(order: Order, wallet: Wallet, coupon: Coupon, uid: Id[User]) -> None:
    assert_type(apply_coupon(order, coupon), StepResult)
    assert_type(order.set() + wallet.set(), Changes)
    assert_type(OrderRepo.by_number, Finder[str])
    assert_type(orders.by_number, BoundFinder[Order, str])
    assert_type(orders.by_number("A-1"), Order)
    assert_type(wallets.by_user(uid), Wallet)
