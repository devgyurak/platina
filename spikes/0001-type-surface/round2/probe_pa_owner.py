"""P-A: owner types propagated into relations, predicates, set changes and queries."""

from datetime import datetime
from decimal import Decimal
from typing import reveal_type

from domain_final import Coupon, Item, Money, Order, OrderStatus, OrderSummary, User, Wallet, orders
from lib_final import Id, count, select, select_from


def positives(order: Order, item: Item, now: datetime, uid: Id[User]) -> None:
    reveal_type(Order.status)
    reveal_type(Order.items)
    reveal_type(Order.status == OrderStatus.PAID)
    reveal_type(Order.items.add(item))
    reveal_type(Order.items.update(item, Item.position.to(2)))
    reveal_type(order.set(Order.items.update(item, Item.position.to(2))))
    reveal_type(Order.where(Order.status == OrderStatus.PENDING, Order.created_at < now))
    reveal_type(
        Order.where(Order.status == OrderStatus.PENDING).set(Order.status.to(OrderStatus.EXPIRED))
    )
    reveal_type(Order.total.path(Money.amount))
    reveal_type(orders.summaries(user_id=uid))


def misuse(
    order: Order, item: Item, wallet: Wallet, coupon: Coupon, m: Money, uid: Id[User]
) -> None:
    Order.items.update(item, Order.status.to(OrderStatus.PAID))  # M1 parent op in a child update
    Order.items.update(item, Wallet.balance.to(m))  # M2 other entity's op in a child update
    wallet.set(Order.items.add(item))  # M3 another entity's relation op
    Order.where(Wallet.user_id == uid)  # M4 another entity's predicate
    Order.where(Order.status == OrderStatus.PENDING).set(Wallet.balance.to(m))  # M5 set-change op
    Order.items.add(coupon)  # M6 wrong child type


def queries(uid: Id[User]) -> None:
    # S1 (the stub's Select): predicates over any entity
    q1 = (
        select(OrderSummary, id=Order.id, item_count=count(Item.id))
        .join(Order.items, outer=True)
        .where(Order.user_id == uid, Item.position < 3)
    )
    reveal_type(q1)
    select(OrderSummary, id=Order.id).where(Wallet.user_id == uid)  # Q1 not joined, S1 accepts?
    # S2: a query that tracks the entities it reads
    q2 = select_from(OrderSummary, id=Order.id, number=Order.number)
    reveal_type(q2)
    q3 = q2.join(Order.items, outer=True)
    reveal_type(q3)
    reveal_type(q3.where(Order.user_id == uid, Item.position < 3))
    q3.where(Wallet.user_id == uid)  # Q2 not joined, S2 rejects?
    q4 = select_from(OrderSummary, id=Order.id, item_count=Item.id)  # columns of two entities
    reveal_type(q4)
    q4.where(Wallet.user_id == uid)  # Q3 two-entity select, not joined
    _ = Decimal
