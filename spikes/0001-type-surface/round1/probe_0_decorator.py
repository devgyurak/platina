"""Item 0: with `@entity(...)` alone (no base class), are new/ref/where/stub/set visible?"""

from enum import Enum
from typing import reveal_type
from uuid import UUID

from lib_design import Col, Id, column, entity, pk


class OrderStatus(Enum):
    PENDING = "pending"
    PAID = "paid"


@entity(table="orders", aggregate_root=True)
class Order:
    id: Col[Id[Order]] = pk(generated="uuid7")
    number: Col[str] = column(unique=True, length=20)
    status: Col[OrderStatus] = column(default=OrderStatus.PENDING, enum_as="text")


def probe(oid: UUID, order: Order) -> None:
    reveal_type(Order)
    reveal_type(Order(number="A-1"))  # the synthesised __init__ exists
    reveal_type(Order.new(number="A-1"))
    reveal_type(Order.ref(oid))
    reveal_type(Order.where(Order.status == OrderStatus.PENDING))
    reveal_type(Order.stub())
    reveal_type(order.set(Order.status.to(OrderStatus.PAID)))
