"""Spike 0006, observations O9-O10 (added after the architect review): lines read from the
signatures, run directly through both checkers.

O9 - a child's parent key changed after creation, and `add` of a child that belongs to another
parent. O10 - ordering operators on value types without a natural order (an enum, an embedded
value).
"""

from decimal import Decimal
from typing import reveal_type

from domain import Item, Money, Order, PaymentMethod


def reparent(order: Order, other: Order, item: Item) -> None:
    reveal_type(order.set(Order.items.update(item, Item.order_id.to(other.id))))
    reveal_type(Item.where(Item.sku == "A").set(Item.order_id.to(other.id)))
    reveal_type(order.set(Order.items.add(other.items[0])))


def ordering() -> None:
    reveal_type(Order.paid_with >= PaymentMethod.POINT)
    reveal_type(Order.total >= Money(Decimal(1)))
