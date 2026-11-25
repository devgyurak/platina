"""Item 3: writes."""

from datetime import datetime
from typing import reveal_type

from domain import Item, Money, Order, OrderStatus, Wallet


def probe(order: Order, item: Item, now: datetime, money: Money) -> None:
    reveal_type(order.set(Order.status.to(OrderStatus.PAID), Order.paid_at.to(now)))
    reveal_type(order.set(Order.items.add(item)))
    reveal_type(Order.paid_at.to(None))

    Order.status.to(123)  # W1 int is not OrderStatus
    order.status = OrderStatus.PAID  # W2 snapshots are immutable
    order.items.append(item)  # W3 Sequence has no append
    Order.number.to(None)  # W4 None is not str
    Order.status.to("paid")  # W5 str is not OrderStatus

    # observation: the owner of an operation is not checked (Wallet field on an Order)
    reveal_type(order.set(Wallet.balance.to(money)))
