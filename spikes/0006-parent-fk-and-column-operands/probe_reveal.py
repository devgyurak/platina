"""Spike 0006: the inferred types behind the assert_type lines, as each checker prints them."""

from decimal import Decimal
from typing import reveal_type

from domain import Item, Money, Order, Wallet

reveal_type(Order.amount >= Decimal(0))
reveal_type(Order.ratio >= 1)
reveal_type(Order.qty <= Order.cap)
reveal_type(Wallet.user_id == Order.user_id)
reveal_type(Order.user_id == Wallet.user_id)
reveal_type(Wallet.user_id == Order.guest_id)
reveal_type(Order.guest_id == Wallet.user_id)
reveal_type(Decimal(0) <= Order.amount)
reveal_type(Order.total.path(Money.amount) == Wallet.balance.path(Money.amount))
reveal_type(Item.order_id)
reveal_type(Item(sku="A", price=Decimal(1)).order_id)
reveal_type(Item.__init__)
