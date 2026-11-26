"""Spike 0006, observations O9-O10 (added after the architect review): lines read from the
signatures, run directly through both checkers.

O9 - a child's parent key changed after creation, and `add` of a child that belongs to another
parent. O10 - ordering on an enum column (no order in Python), and comparisons on an embedded
value column, whose value class is ordered in Python (`@value`, `order_default=True`) but whose
column spans several SQL columns.
"""

from decimal import Decimal
from typing import reveal_type

from domain import Item, Money, Order, PaymentMethod


def reparent(order: Order, other: Order, item: Item) -> None:
    reveal_type(order.set(Order.items.update(item, Item.order_id.to(other.id))))
    reveal_type(Item.where(Item.sku == "A").set(Item.order_id.to(other.id)))
    reveal_type(order.set(Order.items.add(other.items[0])))


def ordering() -> None:
    reveal_type(Order.paid_with >= PaymentMethod.POINT)  # an enum column
    reveal_type(Order.total >= Money(Decimal(1)))  # an embedded value column
    reveal_type(Order.total == Money(Decimal(1)))
    reveal_type(Money(Decimal(1)) < Money(Decimal(2)))  # the value class itself is ordered
