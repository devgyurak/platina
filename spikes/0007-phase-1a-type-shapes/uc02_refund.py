"""Use case 2 - cancellation with refund (dependent loads). Requirements R2.1-R2.7.

[0007] Ported from spike 0002 because the spike 0007 stub no longer type-checks it (architect
review of spike 0007): only the statements marked `# [0007]` changed (a wrapped statement
carries the marker on its first line).

Source: pretix/pretix `services/orders.py` `_cancel_order`, `_try_auto_refund`,
`models/orders.py` `propose_auto_refunds`, `OrderRefund`. Rules restated, no code copied.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from domain import (
    CannotCancel,
    Coupon,
    FeeTooHigh,
    Item,
    LineStatus,
    Money,
    Order,
    OrderCancelled,
    OrderStatus,
    Payment,
    PaymentMethod,
    PaymentStatus,
    Refund,
    RefundRequested,
    RefundTarget,
    Wallet,
    wallets,
)
from lib import (
    INJECTED,
    Add,
    App,
    Bound,
    Changes,
    Load,
    Now,
    Op,
    ProcessContext,
    RelOp,  # [0007]
    emit,
    insert,  # [0007]
    process,
    usecase,
)

app = App(dsn="postgresql://app@primary/shop")

PAYMENT_TERM = timedelta(days=3)  # porting choice: the source computes a new payment deadline

type CancellableOrder = Annotated[Order, Load(Order.items, Order.payments, Order.refunds)]

# --- the design's expression form (4.7) was rejected by both checkers (H2, #51); under #51's  # [0007]
# [0007] decided overloads both accept it (pass_shapes.py S7) - not rewritten here (ported only)


# --- the function form (4.7) holds
def refund_wallet(order: Order) -> Wallet | None:
    # reads the order's loaded payments: the function runs after stage 1
    paid_by_wallet = any(p.method is PaymentMethod.WALLET for p in order.payments)
    if not paid_by_wallet or order.user_id is None:
        return None
    return wallets.by_user(order.user_id)


def order_coupon(order: Order) -> Coupon | None:
    return Coupon.ref(order.coupon_id) if order.coupon_id is not None else None


type RefundWallet = Annotated[Wallet | None, Load.after(refund_wallet)]
type UsedCoupon = Annotated[Coupon | None, Load.after(order_coupon)]


def choose_payments(
    payments: list[Payment], refunds: list[Refund], amount: Decimal
) -> list[tuple[Payment, Decimal]]:
    """R2.5, the source's greedy rule over what is left on each payment (its amount minus the
    refunds already made against it): exact match, else the smallest larger partially refundable
    payment, else the largest smaller one; repeat."""
    left_on = {
        p.id: p.amount.amount
        - sum((r.amount.amount for r in refunds if r.payment_id == p.id), Decimal(0))
        for p in payments
    }
    left, chosen = amount, list[tuple[Payment, Decimal]]()
    pool = [p for p in payments if left_on[p.id] > 0]
    while left > 0 and pool:
        exact = [p for p in pool if left_on[p.id] == left]
        larger = sorted(
            (p for p in pool if left_on[p.id] > left and p.partial_refunds),
            key=lambda p: left_on[p.id],
        )
        smaller = sorted(
            (p for p in pool if left_on[p.id] < left), key=lambda p: left_on[p.id], reverse=True
        )
        pick = exact[0] if exact else larger[0] if larger else smaller[0] if smaller else None
        if pick is None:
            break
        part = min(left, left_on[pick.id])
        chosen.append((pick, part))
        pool.remove(pick)
        left -= part
    return chosen


@usecase
def cancel_order(
    order: CancellableOrder,
    fee: Money | None,
    wallet: RefundWallet = INJECTED,  # see the call site: without a default, `bind` requires it
    coupon: UsedCoupon = INJECTED,
    now: Now = INJECTED,
) -> Changes:
    # R2.1 - "at least one item" counts active items (a fee cancellation leaves them cancelled)
    allowed = (OrderStatus.PENDING, OrderStatus.PAID, OrderStatus.EXPIRED)
    active = [i for i in order.items if i.status is LineStatus.ACTIVE]
    if order.status not in allowed or not active:
        raise CannotCancel(order.id)
    paid = sum(
        (p.amount.amount for p in order.payments if p.status is PaymentStatus.CONFIRMED),
        Decimal(0),
    )
    refunded = sum((r.amount.amount for r in order.refunds), Decimal(0))
    # R2.2
    ops: list[Op[Order] | RelOp[Order]] = [  # [0007] a relation operation is not an Op
        Order.items.update(item, Item.status.to(LineStatus.CANCELLED)) for item in active
    ]
    if fee is not None:
        if fee.amount > order.total.amount:
            raise FeeTooHigh(order.id)
        new_total = fee
        ops.append(Order.total.to(fee))
        if paid - refunded < fee.amount:  # payments do not cover the fee: back to pending
            ops += [Order.status.to(OrderStatus.PENDING), Order.expires_at.to(now + PAYMENT_TERM)]
    else:
        new_total = Money(Decimal(0), order.total.currency)
        ops += [Order.status.to(OrderStatus.CANCELLED), Order.total.to(new_total)]
    changes = emit(OrderCancelled(order_id=order.id, fee=new_total))
    # R2.3: "minus one, never below zero" is a read-modify-write; `.add(-1)` cannot floor at 0
    if coupon is not None:
        changes += coupon.set(Coupon.used.to(max(coupon.used - 1, 0)))
    # R2.4
    outstanding = paid - refunded - new_total.amount
    # R2.5 - the source's greedy rule over every confirmed payment; each chosen part is refunded
    # the way it was paid: wallet parts to the wallet, card parts through the provider
    currency = order.total.currency
    confirmed = [p for p in order.payments if p.status is PaymentStatus.CONFIRMED]
    chosen = choose_payments(confirmed, list(order.refunds), outstanding) if outstanding > 0 else []
    to_wallet = Decimal(0)
    for payment, part in chosen:
        if payment.method is PaymentMethod.WALLET:
            to_wallet += part
            changes += insert(  # [0007] was `ops.append(Order.refunds.add(...))`: not owned
                Refund(
                    order_id=order.id,
                    payment_id=payment.id,
                    amount=Money(part, currency),
                    target=RefundTarget.WALLET,
                )
            )
            continue
        refund = Refund(
            order_id=order.id,
            payment_id=payment.id,
            amount=Money(part, currency),
            target=RefundTarget.PROVIDER,
        )
        changes += insert(refund)  # [0007] was `ops.append(Order.refunds.add(refund))`
        changes += emit(
            RefundRequested(
                order_id=order.id, refund_id=refund.id, payment_id=payment.id, amount=refund.amount
            )
        )
    if to_wallet > 0:
        if wallet is None:
            raise CannotCancel(order.id)  # a wallet payment without a wallet: data error
        changes += wallet.set(Wallet.balance.path(Money.amount).add(to_wallet))  # 9.5
    remainder = outstanding - sum((part for _, part in chosen), Decimal(0))
    if remainder > 0:
        changes += insert(  # [0007] was `ops.append(Order.refunds.add(...))`
            Refund(order_id=order.id, amount=Money(remainder, currency), target=RefundTarget.MANUAL)
        )
    return order.set(*ops) + changes


# R2.6: the provider call after commit
class Provider:
    async def refund(self, payment_id: UUID, amount: Money, idempotency_key: str) -> bool:
        raise NotImplementedError


@process(on=RefundRequested)
async def execute_refund(e: RefundRequested, ctx: ProcessContext, pg: Provider) -> Bound | None:
    await pg.refund(e.payment_id, e.amount, idempotency_key=ctx.idempotency_key)
    return mark_refund_done.bind(refund=Refund.ref(e.refund_id))


@usecase
def mark_refund_done(refund: Annotated[Refund, Load()]) -> Changes:
    from domain import RefundState

    return refund.set(Refund.state.to(RefundState.DONE))


# --------------------------------------------------------------------------- call site
async def post_cancel(order_id: UUID) -> None:
    await app.run(cancel_order.bind(order=Order.ref(order_id), fee=None))


# --------------------------------------------------------------------------- 4.12 unit tests
NOW = datetime(2026, 11, 25)


def test_wallet_payment_is_refunded_to_the_wallet() -> None:
    item = Item.stub(status=LineStatus.ACTIVE)
    payment = Payment.stub(
        method=PaymentMethod.WALLET, status=PaymentStatus.CONFIRMED, amount=Money(Decimal("1000"))
    )
    order = Order.stub(
        status=OrderStatus.PAID,
        paid_with=PaymentMethod.WALLET,
        total=Money(Decimal("1000")),
        items=[item],
        payments=[payment],
        refunds=[],
    )
    wallet = Wallet.stub(balance=Money(Decimal("0")))
    r = cancel_order(order, None, wallet, None, now=NOW)
    assert r.updated(wallet)[Wallet.balance] == Add(Decimal("1000"))
    [refund] = r.inserted(Refund)
    assert (refund.target, refund.amount) == (RefundTarget.WALLET, Money(Decimal("1000")))
