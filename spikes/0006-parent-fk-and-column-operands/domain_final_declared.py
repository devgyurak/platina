"""Design sections 4.2-4.6 transcribed onto `lib_final.pyi` (round 2, P-C).

Deviations from the design text, all from the maintainer's decisions: `class Order(Entity,
table=...)` (ADR-0003), value fields declared `Col[...]` and embedded paths written
`Order.total.path(Money.amount)` (ADR-0004), and `Decimal(0)` in the check (L5 is open).
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Annotated

from lib import (
    INJECTED,
    Changes,
    Check,
    Col,
    Entity,
    Finder,
    Id,
    Index,
    Load,
    Now,
    Profile,
    Rel,
    Repository,
    Select,
    chain,
    column,
    count,
    dto,
    embedded,
    emit,
    event,
    fk,
    invariant,
    many_to_one,
    one_to_many,
    pk,
    query,
    select,
    server_now,
    step,
    usecase,
    value,
    version_column,
)


class OrderStatus(Enum):
    PENDING = "pending"
    PAID = "paid"
    EXPIRED = "expired"


class PaymentMethod(Enum):
    CARD = "card"
    WALLET = "wallet"


class AlreadyPaid(Exception): ...


class InsufficientBalance(Exception): ...


# --------------------------------------------------------------------------- 4.2
@value
class Money:
    amount: Col[Decimal]
    currency: Col[str] = column(default="KRW")


class User(Entity, table="users"):
    id: Col[Id[User]] = pk(generated="uuid7")
    name: Col[str] = column(length=100)


class Order(Entity, table="orders", aggregate_root=True):
    id: Col[Id[Order]] = pk(generated="uuid7")
    number: Col[str] = column(unique=True, length=20)
    status: Col[OrderStatus] = column(default=OrderStatus.PENDING, enum_as="text")
    paid_with: Col[PaymentMethod | None] = column(default=None)
    paid_at: Col[datetime | None] = column(default=None)
    total: Col[Money] = embedded(prefix="total_")
    user_id: Col[Id[User]] = fk(lambda: User)
    user: Rel[User] = many_to_one(via=lambda: Order.user_id)
    items: Rel[list[Item]] = one_to_many(
        lambda: Item.order_id, owned=True, order_by=lambda: Item.position
    )
    version: Col[int] = version_column()
    created_at: Col[datetime] = column(server_default=server_now())

    class Meta:
        indexes = (Index(lambda: (Order.user_id, Order.created_at.desc())),)
        checks = (Check(lambda: Order.total.path(Money.amount) >= Decimal(0)),)

    @invariant(fields=lambda: (Order.status, Order.total))
    def paid_requires_total(self) -> bool:
        return self.status is not OrderStatus.PAID or self.total.amount > 0


class Item(Entity, table="items"):
    id: Col[Id[Item]] = pk(generated="uuid7")
    order_id: Col[Id[Order]] = fk(lambda: Order)
    position: Col[int] = column()
    price: Col[Money] = embedded(prefix="price_")


class Wallet(Entity, table="wallets"):
    id: Col[Id[Wallet]] = pk(generated="uuid7")
    user_id: Col[Id[User]] = fk(lambda: User)
    balance: Col[Money] = embedded(prefix="balance_")


class Coupon(Entity, table="coupons"):
    id: Col[Id[Coupon]] = pk(generated="uuid7")
    rate: Col[Decimal] = column()
    used: Col[bool] = column(default=False)

    def apply(self, total: Money) -> Money:
        return Money(total.amount * (1 - self.rate), total.currency)


@event(aggregate=lambda: OrderPaid.order_id)
class OrderPaid:
    order_id: Col[Id[Order]]
    user_id: Col[Id[User]]
    total: Col[Money]
    paid_at: Col[datetime]


@event(aggregate=lambda: OrderExpired.order_id)
class OrderExpired:
    order_id: Col[Id[Order]]


# --------------------------------------------------------------------------- 4.3
@dto
class OrderSummary:
    id: Id[Order]
    number: str
    total: Decimal
    item_count: int


class OrderRepo(Repository[Order]):
    by_number = Finder(Order.number)

    payable = Profile(Order.items, Order.user)
    with_item_count = Profile(Order.items.count())
    for_update = Profile(Order.items, lock="for_update")

    @query
    def summaries(self, user_id: Id[User], limit: int = 20) -> Select[OrderSummary]:
        return (
            select(
                OrderSummary,
                id=Order.id,
                number=Order.number,
                total=Order.total.path(Money.amount),
                item_count=count(Item.id),
            )
            .join(Order.items, outer=True)
            .where(Order.user_id == user_id)
            .group_by(Order.id)
            .order_by(Order.created_at.desc())
            .limit(limit)
        )

    def expire_older_than(self, cutoff: datetime) -> Changes:
        return (
            Order.where(Order.status == OrderStatus.PENDING, Order.created_at < cutoff)
            .set(Order.status.to(OrderStatus.EXPIRED))
            .emit_each(OrderExpired, order_id=Order.id)
        )


class WalletRepo(Repository[Wallet]):
    by_user = Finder(Wallet.user_id)


orders, wallets = OrderRepo(), WalletRepo()

# --------------------------------------------------------------------------- 4.5
type PayableOrder = Annotated[Order, orders.payable]
type ChargeableWallet = Annotated[Wallet, Load()]


@usecase
def pay(order: PayableOrder, wallet: ChargeableWallet, now: Now = INJECTED) -> Changes:
    if order.status is not OrderStatus.PENDING:
        raise AlreadyPaid(order.id)
    if wallet.balance < order.total:
        raise InsufficientBalance(wallet.id)
    return (
        order.set(Order.status.to(OrderStatus.PAID), Order.paid_at.to(now))
        + wallet.set(Wallet.balance.path(Money.amount).add(-order.total.amount))
        + emit(OrderPaid(order_id=order.id, user_id=order.user_id, total=order.total, paid_at=now))
    )


# --------------------------------------------------------------------------- 4.6
@step
def apply_coupon(order: Order, coupon: Coupon) -> Changes:
    return order.set(Order.total.to(coupon.apply(order.total))) + coupon.set(Coupon.used.to(True))


@usecase
def checkout(
    order: PayableOrder,
    coupon: Annotated[Coupon, Load()],
    wallet: ChargeableWallet,
    now: Now = INJECTED,
) -> Changes:
    with chain(order, wallet) as (c, order, wallet):
        c.run(apply_coupon, order, coupon)
        c.run(pay, order, wallet, now)
    return c.changes
