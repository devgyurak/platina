"""Use case 1 - payment (idempotency key, run ID). Requirements R1.1-R1.7 in the write-up.

Source: brandur/rocket-rides-atomic `api.rb` `POST /rides`; control: dotnet/eShop
`IdentifiedCommandHandler.cs`. Rules restated, no code copied.
"""

from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from domain import (
    AlreadyPaid,
    InsufficientBalance,
    Money,
    Order,
    OrderPaid,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    User,
    Wallet,
    orders,
    wallets,
)
from lib import (
    INJECTED,
    Add,
    App,
    Bound,
    Changes,
    Id,
    Load,
    Now,
    ProcessContext,
    emit,
    process,
    usecase,
)

app = App(dsn="postgresql://app@primary/shop")

type PayableOrder = Annotated[Order, orders.payable]
type ChargeableWallet = Annotated[Wallet, Load()]


@usecase
def pay(order: PayableOrder, wallet: ChargeableWallet, now: Now = INJECTED) -> Changes:
    if order.status is not OrderStatus.PENDING:
        raise AlreadyPaid(order.id)
    if wallet.balance < order.total:
        raise InsufficientBalance(wallet.id)
    # R1.6: the payment row. A new non-root entity is inserted through a relation of a loaded
    # parent (`Order.payments`, not owned); the parent key is passed by hand (#49).
    payment = Payment(
        order_id=order.id,
        method=PaymentMethod.WALLET,
        amount=order.total,
        status=PaymentStatus.CONFIRMED,
    )
    return (
        order.set(
            Order.status.to(OrderStatus.PAID),
            Order.paid_at.to(now),
            Order.paid_with.to(PaymentMethod.WALLET),
            Order.payments.add(payment),
        )
        + wallet.set(Wallet.balance.path(Money.amount).add(-order.total.amount))  # 9.5
        + emit(OrderPaid(order_id=order.id, user_id=order.user_id, total=order.total, paid_at=now))
    ).returning(payment.id)  # R1.4


# R1.7: the receipt is external I/O, so it is a `@process` on the committed event, not `then`
class Mailer:
    async def send_receipt(self, order_id: UUID, idempotency_key: str) -> None: ...


@process(on=OrderPaid)
async def send_receipt(e: OrderPaid, ctx: ProcessContext, mailer: Mailer) -> Bound | None:
    await mailer.send_receipt(e.order_id, idempotency_key=ctx.idempotency_key)
    return None


# --------------------------------------------------------------------------- call site (R1.1-R1.5)
async def post_pay_narrowed(order_id: UUID, user_id: Id[User], idempotency_key: str) -> UUID:
    result = await app.run(
        pay.bind(order=Order.ref(order_id), wallet=wallets.by_user(user_id)),
        idempotency_key=idempotency_key,
    )
    value = result.value
    if not isinstance(value, UUID):  # the only typed way back from `returning(...)`
        raise TypeError(value)
    return value


# --------------------------------------------------------------------------- 4.12 unit tests
NOW = datetime(2026, 11, 25)


def test_pay_moves_balance_and_records_payment() -> None:
    order = Order.stub(status=OrderStatus.PENDING, total=Money(Decimal("1000")))
    wallet = Wallet.stub(balance=Money(Decimal("5000")))
    r = pay(order, wallet, now=NOW)
    assert r.updated(wallet)[Wallet.balance] == Add(Decimal("-1000"))
    [payment] = r.inserted(Payment)  # its ID comes from the deterministic test sequence
    assert payment.amount == Money(Decimal("1000"))
    assert r.value == payment.id
    assert r.events == [
        OrderPaid(order_id=order.id, user_id=order.user_id, total=order.total, paid_at=NOW)
    ]
