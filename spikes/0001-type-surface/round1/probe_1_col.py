"""Item 1: Col[T] / Rel[...] class and instance access."""

from collections.abc import Sequence
from datetime import datetime
from typing import assert_type, reveal_type

from domain import Item, Money, Order, OrderPaid, OrderStatus, PaymentMethod, User
from lib_design import Column, Expr, Id, Op, Relation, RelColumn


def probe(order: Order, item: Item, paid: OrderPaid) -> None:
    reveal_type(Order.status)
    reveal_type(order.status)
    reveal_type(Order.items)
    reveal_type(order.items)
    reveal_type(Order.user)
    reveal_type(order.user)
    reveal_type(Order.total)
    reveal_type(order.total)
    reveal_type(OrderPaid.order_id)
    reveal_type(paid.order_id)

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
