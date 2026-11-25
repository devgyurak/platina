"""P-C: design 11.8 `pass_composition` and the round-2 surface, on lib_final + shop_final."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import assert_type
from uuid import UUID

from domain_final import (
    Coupon,
    Item,
    Money,
    Order,
    OrderExpired,
    OrderPaid,
    OrderRepo,
    OrderStatus,
    OrderSummary,
    User,
    Wallet,
    apply_coupon,
    orders,
    pay,
    wallets,
)
from lib_final import (
    App,
    BoundFinder,
    Changes,
    Column,
    ConsistencyToken,
    Finder,
    Id,
    Op,
    Pred,
    Relation,
    SetChange,
    StepResult,
    chain,
)

app = App(dsn="postgresql://app@primary/shop")


async def composition(oid: UUID, uid: Id[User], order: Order, wallet: Wallet, money: Money) -> None:
    result = await app.run(pay.bind(order=Order.ref(oid), wallet=wallets.by_user(uid)))
    assert_type(result.token, ConsistencyToken)
    rows = await app.query(orders.summaries(user_id=uid))
    assert_type(rows, list[OrderSummary])
    assert_type(Order.status, Column[Order, OrderStatus])
    assert_type(order.status, OrderStatus)
    with chain(order, wallet) as (c, o2, w2):
        assert_type(o2, Order)
        assert_type(w2, Wallet)
    assert_type(c.changes, Changes)
    new = Order(number="A-1", total=money, user_id=uid)  # required-field check
    assert_type(new, Order)


def surface(order: Order, item: Item, coupon: Coupon, m: Money, now: datetime) -> None:
    assert_type(Money.amount, Column[Money, Decimal])
    assert_type(m.amount, Decimal)
    assert_type(Money(Decimal("1000")), Money)
    assert_type(Order.total.path(Money.amount), Column[Order, Decimal])
    assert_type(Wallet.balance.path(Money.amount).add(Decimal("-1")), Op[Wallet])
    assert_type(Order.items, Relation[Order, Item])
    assert_type(order.items, Sequence[Item])
    assert_type(Order.items.update(item, Item.position.to(2)), Op[Order])
    assert_type(Order.status == OrderStatus.PAID, Pred[Order])
    assert_type(Order.where(Order.created_at < now), SetChange[Order])
    assert_type(order.set(Order.status.to(OrderStatus.PAID), Order.paid_at.to(now)), Changes)
    assert_type(OrderRepo.by_number, Finder[Order, str])
    assert_type(orders.by_number, BoundFinder[Order, str])
    assert_type(apply_coupon(order, coupon), StepResult)
    assert_type({order}, set[Order])  # frozen base: hashable in both checkers
    expired = Order.where(Order.created_at < now).set(Order.status.to(OrderStatus.EXPIRED))
    assert_type(expired.emit_each(OrderExpired, order_id=Order.id), SetChange[Order])
    assert_type(
        expired.emit_each(OrderPaid, order_id=Order.id, user_id=Order.user_id), SetChange[Order]
    )
