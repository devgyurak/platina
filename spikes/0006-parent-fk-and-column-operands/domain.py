"""Spike 0006: the smallest domain the probe lines of #49 and #51 need, on `lib.pyi`.

`Item` is an owned child whose FK is declared with `parent_fk` (#49); `Payment` is a child of a
relation that is not `owned`, whose FK stays an ordinary `fk`. `Order` carries columns of several
value types for the operand lines of #51 (`amount` Decimal, `qty`/`cap` int, `ratio` float,
`guest_id` a nullable `Id[User]`).
"""

from decimal import Decimal
from enum import Enum

from lib import (
    Col,
    Entity,
    Id,
    Rel,
    column,
    embedded,
    fk,
    one_to_many,
    parent_fk,
    pk,
    value,
    version_column,
)


class PaymentMethod(Enum):
    CARD = "card"
    POINT = "point"


@value
class Money:
    amount: Col[Decimal]
    currency: Col[str] = column(default="KRW")


class User(Entity, table="users"):
    id: Col[Id[User]] = pk(generated="uuid7")


class Order(Entity, table="orders", aggregate_root=True):
    id: Col[Id[Order]] = pk(generated="uuid7")
    number: Col[str] = column(unique=True, length=20)
    user_id: Col[Id[User]] = fk(lambda: User)
    guest_id: Col[Id[User] | None] = column(default=None)
    paid_with: Col[PaymentMethod | None] = column(default=None)
    total: Col[Money] = embedded(prefix="total_")
    amount: Col[Decimal] = column()
    qty: Col[int] = column()
    cap: Col[int] = column()
    ratio: Col[float] = column()
    items: Rel[list[Item]] = one_to_many(
        lambda: Item.order_id, owned=True, order_by=lambda: Item.position
    )
    payments: Rel[list[Payment]] = one_to_many(lambda: Payment.order_id)
    version: Col[int] = version_column()


class Item(Entity, table="items"):
    id: Col[Id[Item]] = pk(generated="uuid7")
    order_id: Col[Id[Order]] = parent_fk(lambda: Order)
    sku: Col[str] = column()
    price: Col[Decimal] = column()
    position: Col[int] = column(default=0)


class Payment(Entity, table="payments"):
    id: Col[Id[Payment]] = pk(generated="uuid7")
    order_id: Col[Id[Order]] = fk(lambda: Order)
    amount: Col[Decimal] = column()


class Wallet(Entity, table="wallets"):
    id: Col[Id[Wallet]] = pk(generated="uuid7")
    user_id: Col[Id[User]] = fk(lambda: User)
    balance: Col[Money] = embedded(prefix="balance_")
