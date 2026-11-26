"""Use case 10 - payment approval notice (`@process`, job pipeline, external idempotency key).
Requirements R10.1-R10.5.

[0007] Ported from spike 0002 because the spike 0007 stub no longer type-checks it (independent
review of spike 0007): only the statements marked `# [0007]` changed. `Order.payments` is not owned,
so the payment row is written directly. Not mechanical: `decline_payment`'s `order` parameter
was only the receiver of `Order.payments.update(...)`; with the row written directly it is unused,
so the port drops it (and the handler binds the payment only).

Sources: brandur/rocket-rides-atomic `api.rb` (Stripe charge with an idempotency key, `StagedJob`);
dotnet/eShop `OrderStatusChangedToStockConfirmedIntegrationEventHandler.cs`. Rules restated.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Annotated

from domain import (
    AlreadyPaid,
    Money,
    Order,
    OrderPaid,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentRequested,
    PaymentStatus,
    orders,
)
from lib import (
    INJECTED,
    App,
    Bound,
    Changes,
    DomainError,
    Load,
    Now,
    ProcessContext,
    RetryLater,
    emit,
    insert,  # [0007]
    process,
    usecase,
)

app = App(dsn="postgresql://app@primary/shop")


@usecase
def request_card_payment(order: Annotated[Order, orders.payable]) -> Changes:
    if order.status is not OrderStatus.PENDING:
        raise AlreadyPaid(order.id)
    payment = Payment(order_id=order.id, method=PaymentMethod.CARD, amount=order.total)
    return insert(payment) + emit(  # [0007] was `order.set(Order.payments.add(payment))`
        PaymentRequested(order_id=order.id, payment_id=payment.id, amount=order.total)
    )


@dataclass(frozen=True)
class Charge:
    ok: bool
    id: str
    code: str


class GatewayUnavailable(Exception):
    """A transient gateway error (rocket-rides: 503). Whether the job runner treats an arbitrary
    handler exception as "transient" (retry with backoff) is not stated: 4.10 lists connection,
    timeout and 40001-exhausted as transient and domain exceptions as dead-letter."""


class Gateway:
    async def charge(self, amount: Money, *, idempotency_key: str) -> Charge:
        raise NotImplementedError


app.provide(Gateway, Gateway)


@process(on=PaymentRequested)
async def approve_payment(e: PaymentRequested, ctx: ProcessContext, gw: Gateway) -> Bound | None:
    # R10.1/R10.5: one key per event, the same on every redelivery
    res = await gw.charge(e.amount, idempotency_key=ctx.idempotency_key)  # R10.4: may raise
    if res.ok:
        return confirm_payment.bind(
            order=Order.ref(e.order_id), payment=Payment.ref(e.payment_id), provider_ref=res.id
        )
    return decline_payment.bind(payment=Payment.ref(e.payment_id))  # [0007] no `order`


class PaymentMismatch(DomainError, retry_later=RetryLater(max_attempts=3, within="10m")): ...


@usecase
def confirm_payment(
    order: Annotated[Order, Load()],
    payment: Annotated[Payment, Load()],
    provider_ref: str,
    now: Now = INJECTED,
) -> Changes:
    if payment.order_id != order.id:
        raise PaymentMismatch(payment.id)
    if payment.status is not PaymentStatus.REQUESTED:  # R10.5 also holds without this: run_claim
        return Changes()  # an empty `Changes` is not shown in the design
    return (
        order.set(
            Order.status.to(OrderStatus.PAID),
            Order.paid_at.to(now),
            Order.paid_with.to(PaymentMethod.CARD),
        )
        + payment.set(  # [0007] was `Order.payments.update(payment, ...)` inside `order.set`
            Payment.status.to(PaymentStatus.CONFIRMED), Payment.provider_ref.to(provider_ref)
        )
        # R10.3: the notice is a reaction to the committed `OrderPaid` - uc01's `send_receipt`
        # `@process`. `then(...)` would run a *use case*, which cannot send anything.
        + emit(OrderPaid(order_id=order.id, user_id=order.user_id, total=order.total, paid_at=now))
    )


@usecase
def decline_payment(payment: Annotated[Payment, Load()]) -> Changes:  # [0007] `order` dropped
    return payment.set(Payment.status.to(PaymentStatus.DECLINED))  # [0007]


# --------------------------------------------------------------------------- 4.12 unit tests
NOW = datetime(2026, 11, 25)


def test_confirm_marks_order_paid_and_emits() -> None:
    order = Order.stub(status=OrderStatus.PENDING, total=Money(Decimal("1000")))
    payment = Payment.stub(order_id=order.id, status=PaymentStatus.REQUESTED)
    r = confirm_payment(order, payment, "ch_1", now=NOW)
    assert r.updated(order)[Order.status] == OrderStatus.PAID
    assert r.updated(payment)[Payment.status] == PaymentStatus.CONFIRMED
    assert r.events == [
        OrderPaid(order_id=order.id, user_id=order.user_id, total=order.total, paid_at=NOW)
    ]


# A `@process` handler is an async function with external I/O; 4.12 shows no test shape for it.
# Called directly with a fake gateway, its result is an opaque `Bound`: which use case and which
# arguments it describes cannot be asserted with the stub's surface.
async def test_approval_describes_confirm() -> None:
    class FakeGateway(Gateway):
        async def charge(self, amount: Money, *, idempotency_key: str) -> Charge:
            return Charge(ok=True, id="ch_1", code="")

    class FakeContext(ProcessContext):
        @property
        def idempotency_key(self) -> str:
            return "job-1"

    e = PaymentRequested(
        order_id=Order.stub().id, payment_id=Payment.stub().id, amount=Money(Decimal("1"))
    )
    bound = await approve_payment(e, FakeContext(), FakeGateway())
    assert bound is not None
