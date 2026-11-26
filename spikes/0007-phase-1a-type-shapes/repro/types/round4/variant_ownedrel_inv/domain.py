"""Spike 0002: the shared domain - section 4.2's `billing` extended to a shop with event tickets.

Section 4.2 is kept as written (with spike 0001's decided forms: `Entity` base, `Col[...]` value
fields, `path(...)`) except one change: `Order.user_id` is nullable (guest orders, use case 6), so
`Order.user` is `Rel[User | None]`. Everything else is added for the ten use cases, each entity for
at least one.
"""

from datetime import datetime
from decimal import Decimal
from enum import Enum

from lib import (
    Check,
    Col,
    Entity,
    Finder,
    Id,
    Index,
    Owned,
    Profile,
    Rel,
    Repository,
    column,
    embedded,
    event,
    fk,
    invariant,
    many_to_one,
    one_to_many,
    parent_fk,
    pk,
    server_now,
    value,
    version_column,
)


class OrderStatus(Enum):
    PENDING = "pending"
    PAID = "paid"
    CANCELLED = "cancelled"
    EXPIRED = "expired"


class LineStatus(Enum):
    ACTIVE = "active"
    CANCELLED = "cancelled"


class PaymentMethod(Enum):
    CARD = "card"
    WALLET = "wallet"


class PaymentStatus(Enum):
    REQUESTED = "requested"
    CONFIRMED = "confirmed"
    DECLINED = "declined"


class RefundTarget(Enum):
    WALLET = "wallet"
    PROVIDER = "provider"
    MANUAL = "manual"


class RefundState(Enum):
    CREATED = "created"
    DONE = "done"


class LegSide(Enum):
    DEBIT = "debit"
    CREDIT = "credit"


# --------------------------------------------------------------------------- values (4.2)
@value
class Money:
    amount: Col[Decimal]
    currency: Col[str] = column(default="KRW")


# --------------------------------------------------------------------------- 4.2 billing, extended
class User(Entity, table="users", aggregate_root=True):
    id: Col[Id[User]] = pk(generated="uuid7")
    first_name: Col[str] = column(length=100)
    last_name: Col[str] = column(length=100)
    language: Col[str] = column(default="ko")
    default_address_id: Col[Id[Address] | None] = fk(lambda: Address, default=None)
    addresses: Owned[list[Address]] = one_to_many(lambda: Address.user_id, owned=True)  # [0007]
    # declared only so that use case 3 can read "has this user used this coupon" (see there)
    redemptions: Rel[list[CouponRedemption]] = one_to_many(lambda: CouponRedemption.user_id)
    version: Col[int] = version_column()


class Address(Entity, table="addresses"):
    id: Col[Id[Address]] = pk(generated="uuid7")
    user_id: Col[Id[User]] = parent_fk(lambda: User)  # [0007]
    line1: Col[str] = column()
    city: Col[str] = column()
    country: Col[str] = column(length=2)


class Order(Entity, table="orders", aggregate_root=True):
    id: Col[Id[Order]] = pk(generated="uuid7")
    number: Col[str] = column(unique=True, length=20)
    status: Col[OrderStatus] = column(default=OrderStatus.PENDING, enum_as="text")
    paid_with: Col[PaymentMethod | None] = column(default=None)
    paid_at: Col[datetime | None] = column(default=None)
    total: Col[Money] = embedded(prefix="total_")
    # 4.2 has a required `user_id`; guest orders (use case 6) need it nullable
    user_id: Col[Id[User] | None] = fk(lambda: User, default=None)
    coupon_id: Col[Id[Coupon] | None] = fk(lambda: Coupon, default=None)
    show_id: Col[Id[Show] | None] = fk(lambda: Show, default=None)
    warehouse_group: Col[str] = column(default="default")
    expires_at: Col[datetime] = column()
    expired_at: Col[datetime | None] = column(default=None)
    user: Rel[User | None] = many_to_one(via=lambda: Order.user_id)  # nullable FK
    items: Owned[list[Item]] = one_to_many(  # [0007]
        lambda: Item.order_id, owned=True, order_by=lambda: Item.position
    )
    tickets: Owned[list[Ticket]] = one_to_many(lambda: Ticket.order_id, owned=True)  # [0007]
    payments: Rel[list[Payment]] = one_to_many(lambda: Payment.order_id)
    refunds: Rel[list[Refund]] = one_to_many(lambda: Refund.order_id)
    show: Rel[Show | None] = many_to_one(via=lambda: Order.show_id)
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
    order_id: Col[Id[Order]] = parent_fk(lambda: Order)  # [0007]
    variant_id: Col[Id[Variant]] = fk(lambda: Variant)
    quantity: Col[int] = column()
    price: Col[Money] = embedded(prefix="price_")
    position: Col[int] = column()
    status: Col[LineStatus] = column(default=LineStatus.ACTIVE, enum_as="text")
    allocations: Rel[list[Allocation]] = one_to_many(lambda: Allocation.item_id)


class Wallet(Entity, table="wallets"):
    id: Col[Id[Wallet]] = pk(generated="uuid7")
    user_id: Col[Id[User]] = fk(lambda: User)
    balance: Col[Money] = embedded(prefix="balance_")


class Payment(Entity, table="payments"):
    id: Col[Id[Payment]] = pk(generated="uuid7")
    order_id: Col[Id[Order]] = fk(lambda: Order)
    method: Col[PaymentMethod] = column(enum_as="text")
    amount: Col[Money] = embedded(prefix="amount_")
    status: Col[PaymentStatus] = column(default=PaymentStatus.REQUESTED, enum_as="text")
    partial_refunds: Col[bool] = column(default=True)
    provider_ref: Col[str | None] = column(default=None)


class Refund(Entity, table="refunds"):
    id: Col[Id[Refund]] = pk(generated="uuid7")
    order_id: Col[Id[Order]] = fk(lambda: Order)
    payment_id: Col[Id[Payment] | None] = fk(lambda: Payment, default=None)
    amount: Col[Money] = embedded(prefix="amount_")
    target: Col[RefundTarget] = column(enum_as="text")
    state: Col[RefundState] = column(default=RefundState.CREATED, enum_as="text")


# --------------------------------------------------------------------------- coupons (use case 3)
class Coupon(Entity, table="coupons"):
    id: Col[Id[Coupon]] = pk(generated="uuid7")
    code: Col[str] = column(unique=True, length=32)
    rate: Col[Decimal] = column()
    active: Col[bool] = column(default=True)
    usage_limit: Col[int | None] = column(default=None)
    used: Col[int] = column(default=0)
    single_use: Col[bool] = column(default=False)
    once_per_customer: Col[bool] = column(default=False)
    redemptions: Rel[list[CouponRedemption]] = one_to_many(lambda: CouponRedemption.coupon_id)

    def apply(self, total: Money) -> Money:
        return Money(total.amount * (1 - self.rate), total.currency)


class CouponRedemption(Entity, table="coupon_redemptions"):
    # unique (coupon_id, user_id) - a table-level unique key; 4.2 shows only `column(unique=True)`
    id: Col[Id[CouponRedemption]] = pk(generated="uuid7")
    coupon_id: Col[Id[Coupon]] = fk(lambda: Coupon)
    user_id: Col[Id[User]] = fk(lambda: User)


# --------------------------------------------------------------------------- stock (use case 4)
class Variant(Entity, table="variants"):
    id: Col[Id[Variant]] = pk(generated="uuid7")
    sku: Col[str] = column(unique=True, length=40)
    track_inventory: Col[bool] = column(default=True)
    stocks: Rel[list[Stock]] = one_to_many(lambda: Stock.variant_id)


class Warehouse(Entity, table="warehouses"):
    id: Col[Id[Warehouse]] = pk(generated="uuid7")
    group: Col[str] = column()


class Stock(Entity, table="stocks"):
    # unique (warehouse_id, variant_id)
    id: Col[Id[Stock]] = pk(generated="uuid7")
    warehouse_id: Col[Id[Warehouse]] = fk(lambda: Warehouse)
    variant_id: Col[Id[Variant]] = fk(lambda: Variant)
    quantity: Col[int] = column()
    allocated: Col[int] = column(default=0)
    warehouse: Rel[Warehouse] = many_to_one(via=lambda: Stock.warehouse_id)

    # `Check(lambda: Stock.allocated <= Stock.quantity)` is rejected by both checkers (#51):
    # fail_findings.py


class Allocation(Entity, table="allocations"):
    id: Col[Id[Allocation]] = pk(generated="uuid7")
    item_id: Col[Id[Item]] = fk(lambda: Item)
    stock_id: Col[Id[Stock]] = fk(lambda: Stock)
    quantity: Col[int] = column()
    stock: Rel[Stock] = many_to_one(via=lambda: Allocation.stock_id)


# --------------------------------------------------------------------------- tickets (use cases 5, 7)
class Show(Entity, table="shows"):
    id: Col[Id[Show]] = pk(generated="uuid7")
    name: Col[str] = column()
    min_distance: Col[float] = column(default=0.0)
    distance_within_row: Col[bool] = column(default=False)
    allow_blocked: Col[bool] = column(default=False)
    auto_expire: Col[bool] = column(default=True)
    expire_delay_days: Col[int] = column(default=0)
    seats: Rel[list[Seat]] = one_to_many(lambda: Seat.show_id)


class Seat(Entity, table="seats"):
    id: Col[Id[Seat]] = pk(generated="uuid7")
    show_id: Col[Id[Show]] = fk(lambda: Show)
    row: Col[str] = column()
    number: Col[int] = column()
    x: Col[float] = column()
    y: Col[float] = column()
    blocked: Col[bool] = column(default=False)
    show: Rel[Show] = many_to_one(via=lambda: Seat.show_id)
    tickets: Rel[list[Ticket]] = one_to_many(lambda: Ticket.seat_id)
    holds: Rel[list[SeatHold]] = one_to_many(lambda: SeatHold.seat_id)


class SeatHold(Entity, table="seat_holds"):
    id: Col[Id[SeatHold]] = pk(generated="uuid7")
    seat_id: Col[Id[Seat]] = fk(lambda: Seat)
    user_id: Col[Id[User]] = fk(lambda: User)
    expires_at: Col[datetime] = column()


class Ticket(Entity, table="tickets"):
    id: Col[Id[Ticket]] = pk(generated="uuid7")
    order_id: Col[Id[Order]] = parent_fk(lambda: Order)  # [0007]
    seat_id: Col[Id[Seat]] = fk(lambda: Seat)
    status: Col[LineStatus] = column(default=LineStatus.ACTIVE, enum_as="text")
    order: Rel[Order] = many_to_one(via=lambda: Ticket.order_id)


# --------------------------------------------------------------------------- ledger (use case 8)
class Account(Entity, table="accounts"):
    id: Col[Id[Account]] = pk(generated="uuid7")
    balance: Col[Money] = embedded(prefix="balance_")
    allow_overdraft: Col[bool] = column(default=False)


class Transfer(Entity, table="transfers", aggregate_root=True):
    id: Col[Id[Transfer]] = pk(generated="uuid7")
    amount: Col[Money] = embedded(prefix="amount_")
    legs: Owned[list[Leg]] = one_to_many(lambda: Leg.transfer_id, owned=True)  # [0007]


class Leg(Entity, table="legs"):
    id: Col[Id[Leg]] = pk(generated="uuid7")
    transfer_id: Col[Id[Transfer]] = parent_fk(lambda: Transfer)  # [0007]
    account_id: Col[Id[Account]] = fk(lambda: Account)
    side: Col[LegSide] = column(enum_as="text")
    amount: Col[Money] = embedded(prefix="amount_")


# --------------------------------------------------------------------------- events
@event(aggregate=lambda: OrderPaid.order_id)
class OrderPaid:
    order_id: Col[Id[Order]]
    user_id: Col[Id[User] | None]
    total: Col[Money]
    paid_at: Col[datetime]


@event(aggregate=lambda: OrderExpired.order_id)
class OrderExpired:
    order_id: Col[Id[Order]]


@event(aggregate=lambda: OrderCancelled.order_id)
class OrderCancelled:
    order_id: Col[Id[Order]]
    fee: Col[Money]


@event(aggregate=lambda: PaymentRequested.order_id)
class PaymentRequested:
    order_id: Col[Id[Order]]
    payment_id: Col[Id[Payment]]
    amount: Col[Money]


@event(aggregate=lambda: RefundRequested.order_id)
class RefundRequested:
    order_id: Col[Id[Order]]
    refund_id: Col[Id[Refund]]
    payment_id: Col[Id[Payment]]
    amount: Col[Money]


# --------------------------------------------------------------------------- repositories
class OrderRepo(Repository[Order]):
    by_number = Finder(Order.number)
    payable = Profile(Order.items, Order.user)
    with_items = Profile(Order.items)


class WalletRepo(Repository[Wallet]):
    by_user = Finder(Wallet.user_id)


class CouponRepo(Repository[Coupon]):
    by_code = Finder(Coupon.code)


class VariantRepo(Repository[Variant]):
    by_sku = Finder(Variant.sku)


orders, wallets, coupons, variants = OrderRepo(), WalletRepo(), CouponRepo(), VariantRepo()


# --------------------------------------------------------------------------- domain errors
class DomainFailure(Exception): ...


class AlreadyPaid(DomainFailure): ...


class InsufficientBalance(DomainFailure): ...


class CannotCancel(DomainFailure): ...


class FeeTooHigh(DomainFailure): ...


class CouponNotApplicable(DomainFailure): ...


class InsufficientStock(DomainFailure):
    def __init__(self, short_items: list[Id[Item]]) -> None:
        super().__init__(short_items)
        self.short_items = short_items


class SeatUnavailable(DomainFailure): ...


class CannotMerge(DomainFailure): ...


class InvalidTransfer(DomainFailure): ...


class InsufficientFunds(DomainFailure): ...


class InvalidAddress(DomainFailure): ...


class TooManyAddresses(DomainFailure): ...
