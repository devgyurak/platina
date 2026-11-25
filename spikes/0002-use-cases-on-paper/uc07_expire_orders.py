"""Use case 7 - expire unpaid orders (set change, `emit_each`). Requirements R7.1-R7.7.

Sources: pretix/pretix `services/orders.py` `expire_orders`, `mark_order_expired`,
`models/orders.py` `payment_term_expire_date`; saleor/saleor `order/tasks.py` `_expire_orders`.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated
from uuid import UUID

from domain import (
    Allocation,
    Coupon,
    Item,
    Money,
    Order,
    OrderExpired,
    OrderStatus,
    Show,
    Stock,
)
from lib import (
    INJECTED,
    Add,
    App,
    Bound,
    Changes,
    Load,
    Now,
    ProcessContext,
    Profile,
    Select,
    dto,
    emit,
    process,
    query,
    select,
    usecase,
)

app = App(dsn="postgresql://app@primary/shop")


# --------------------------------------------------------------------------- (a) one set change
# The form 4.3 / 4.8 show cannot state R7.1/R7.3/R7.4/R7.5: see fail_findings.py (use case 7).


# --------------------------------------------------------------------------- (b) one use case per order
# The source's own shape (pretix: one transaction per order): a query picks the candidates on the
# query path, the scheduler runs one use case per order, and the use case re-checks everything.
@dto
class ExpiryCandidate:
    id: UUID


class ExpiryQueries:
    @query
    def due(self, now: datetime, limit: int = 100) -> Select[ExpiryCandidate]:  # R7.5
        # the show's settings and the delay are evaluated again in the use case; this query only
        # narrows (a join on Show is a query, so it may reference both entities)
        return (
            select(ExpiryCandidate, id=Order.id)
            .join(Order.show)
            .where(Order.status == OrderStatus.PENDING, Order.expires_at < now)
            .limit(limit)
        )


expiry = ExpiryQueries()

# R7.3 needs the order's items, their allocations and each allocation's stock: three levels.
# Written as a nested path (not shown by the design), plus the coupon through `Load.after`.
releasable = Profile(Order.items, Item.allocations, Allocation.stock, Order.show)
type ExpirableOrder = Annotated[Order, releasable]


def used_coupon(order: Order) -> Coupon | None:
    return Coupon.ref(order.coupon_id) if order.coupon_id is not None else None


@usecase
def expire_order(
    order: ExpirableOrder,
    coupon: Annotated[Coupon | None, Load.after(used_coupon)] = INJECTED,
    now: Now = INJECTED,
) -> Changes:
    if order.status is not OrderStatus.PENDING:  # R7.6 (paid in the meantime)
        return Changes().returning(False)  # an empty `Changes` is not shown in the design
    show = order.show
    if show is None or not show.auto_expire:  # R7.1
        return Changes().returning(False)
    if now < order.expires_at + timedelta(days=show.expire_delay_days):
        return Changes().returning(False)
    changes = order.set(  # R7.2
        Order.status.to(OrderStatus.EXPIRED),
        Order.expired_at.to(now),
        *(
            Order.items.update(item, Item.allocations.remove(a))
            for item in order.items
            for a in item.allocations
        ),
    )
    for item in order.items:  # R7.3
        for a in item.allocations:
            changes += a.stock.set(Stock.allocated.add(-a.quantity))
    if coupon is not None:
        changes += coupon.set(Coupon.used.to(max(coupon.used - 1, 0)))
    return (changes + emit(OrderExpired(order_id=order.id))).returning(True)


async def expire_batch(now: datetime) -> int:
    """R7.4: the count exists only in the scheduler, summed over the runs' `returning(...)`
    values (typed `object`)."""
    expired = 0
    for c in await app.query(expiry.due(now)):
        result = await app.run(expire_order.bind(order=Order.ref(c.id)))
        expired += result.value is True
    return expired


# R7.7
class Notifier:
    async def order_expired(self, order_id: UUID, idempotency_key: str) -> None: ...


@process(on=OrderExpired)
async def notify_expired(e: OrderExpired, ctx: ProcessContext, n: Notifier) -> Bound | None:
    await n.order_expired(e.order_id, idempotency_key=ctx.idempotency_key)
    return None


# --------------------------------------------------------------------------- 4.12 unit tests
NOW = datetime(2026, 11, 25)


def test_expiry_releases_allocations_and_coupon() -> None:
    stock = Stock.stub(allocated=5)
    alloc = Allocation.stub(quantity=2, stock=stock)
    item = Item.stub(allocations=[alloc])
    show = Show.stub(auto_expire=True, expire_delay_days=0)
    order = Order.stub(
        status=OrderStatus.PENDING,
        expires_at=NOW - timedelta(hours=1),
        items=[item],
        show=show,
        total=Money(Decimal("10")),
    )
    coupon = Coupon.stub(used=1)
    r = expire_order(order, coupon, now=NOW)
    assert r.updated(order)[Order.status] == OrderStatus.EXPIRED
    assert r.updated(stock)[Stock.allocated] == Add(-2)
    assert r.removed(alloc)
    assert r.events == [OrderExpired(order_id=order.id)]
