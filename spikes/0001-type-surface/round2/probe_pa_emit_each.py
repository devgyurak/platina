"""P-A follow-up (after the round-2 reproduction): `SetChange[O].emit_each(event, **fields: OwnedExpr[O])`."""

from datetime import datetime
from typing import reveal_type

from domain_final import Order, OrderExpired, OrderPaid, OrderStatus, Wallet


def probe(cutoff: datetime) -> None:
    expired = Order.where(Order.status == OrderStatus.PENDING, Order.created_at < cutoff).set(
        Order.status.to(OrderStatus.EXPIRED)
    )
    reveal_type(expired.emit_each(OrderExpired, order_id=Order.id))  # E1 one own column
    reveal_type(expired.emit_each(OrderPaid, order_id=Order.id, user_id=Order.user_id))  # E2 two
    expired.emit_each(OrderExpired, order_id=Wallet.id)  # N1 another entity's column
    expired.emit_each(OrderPaid, order_id=Order.id, user_id=Wallet.user_id)  # N2 mixed
