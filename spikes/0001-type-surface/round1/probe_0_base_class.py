"""Item 0 variant: an `Entity` base class carries the members (dataclass_transform on the base)."""

from collections.abc import Callable
from enum import Enum
from typing import reveal_type
from uuid import UUID

from lib_design import Col, Entity, Id, column, pk


class OrderStatus(Enum):
    PENDING = "pending"
    PAID = "paid"


# (i) options as class keywords
class Order(Entity, table="orders", aggregate_root=True):
    id: Col[Id[Order]] = pk(generated="uuid7")
    number: Col[str] = column(unique=True, length=20)
    status: Col[OrderStatus] = column(default=OrderStatus.PENDING, enum_as="text")


# (ii) the design's decorator kept for the options, the base class only for the members
def options[C](*, table: str, aggregate_root: bool = False) -> Callable[[type[C]], type[C]]:
    raise NotImplementedError


@options(table="orders2", aggregate_root=True)
class Order2(Entity, table="orders2"):
    number: Col[str] = column(unique=True, length=20)


def probe(oid: UUID, order: Order) -> None:
    reveal_type(Order.new(number="A-1"))
    reveal_type(Order.ref(oid))
    reveal_type(Order.where(Order.status < OrderStatus.PENDING))
    reveal_type(Order.stub())
    reveal_type(order.set(Order.status.to(OrderStatus.PAID)))
    reveal_type(Order2.new(number="A-1"))
    reveal_type(Order2.ref(oid))
