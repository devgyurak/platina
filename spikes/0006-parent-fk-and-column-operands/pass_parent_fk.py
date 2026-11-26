"""Spike 0006, part A (#49): the parent-set FK lines that must type-check, with their types."""

from decimal import Decimal
from typing import assert_type

from domain import Item, Order, Payment
from lib import Changes, Column, Id, Op


def parent_set_key(order: Order, item: Item) -> None:
    new = Item(sku="A", price=Decimal(1))  # A1: the FK is not a parameter
    assert_type(new, Item)
    assert_type(Order.items.add(new), Op[Order])
    assert_type(order.set(Order.items.add(item)), Changes)  # A4
    assert_type(item.order_id, Id[Order])  # A5: instance access
    assert_type(Item.order_id, Column[Item, Id[Order]])  # A5: class access


def non_owned_key(order: Order) -> None:
    # The counterpart of A3: a non-owned child still takes its FK.
    assert_type(Payment(order_id=order.id, amount=Decimal(1)), Payment)
