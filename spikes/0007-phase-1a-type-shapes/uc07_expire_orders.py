"""Use case 7 (spike 0002) in the spike 0007 shapes - expire unpaid orders. Requirements R7.1-R7.7.

Changed from spike 0002: the three levels R7.3 needs are one nested path (#59 point 1) instead of
the flat `Profile(Order.items, Item.allocations, Allocation.stock, ...)` that type-checked but was
ambiguous; the allocations are deleted directly (#57 / #60 point 4: `Item.allocations` is not
owned, so `Order.items.update(item, Item.allocations.remove(a))` is no longer a form). The query
path, the scheduler loop and the `@process` handler are unchanged from spike 0002 and left out.
"""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated

from domain import Allocation, Coupon, Item, Money, Order, OrderExpired, OrderStatus, Show, Stock
from lib import INJECTED, Add, Changes, Load, Now, Profile, emit, usecase

releasable = Profile(Order.items.load(Item.allocations.load(Allocation.stock)), Order.show)
type ExpirableOrder = Annotated[Order, releasable]


def used_coupon(order: Order) -> Coupon | None:
    return Coupon.ref(order.coupon_id) if order.coupon_id is not None else None


coupon_load = Load.after(used_coupon)
type UsedCoupon = Annotated[Coupon | None, coupon_load]


@usecase
def expire_order(
    order: ExpirableOrder, coupon: UsedCoupon = INJECTED, now: Now = INJECTED
) -> Changes:
    if order.status is not OrderStatus.PENDING:  # R7.6
        return Changes().returning(False)
    show = order.show
    if show is None or not show.auto_expire:  # R7.1
        return Changes().returning(False)
    if now < order.expires_at + timedelta(days=show.expire_delay_days):
        return Changes().returning(False)
    changes = order.set(Order.status.to(OrderStatus.EXPIRED), Order.expired_at.to(now))  # R7.2
    for item in order.items:  # R7.3
        for a in item.allocations:
            changes += a.delete() + a.stock.set(Stock.allocated.add(-a.quantity))
    if coupon is not None:
        changes += coupon.set(Coupon.used.to(max(coupon.used - 1, 0)))
    return (changes + emit(OrderExpired(order_id=order.id))).returning(True)


# --------------------------------------------------------------------------- 4.12 unit tests
NOW = datetime(2026, 11, 26)


def test_expiry_releases_allocations_and_coupon() -> None:
    stock = Stock.stub(allocated=5)
    alloc = Allocation.stub(quantity=2, stock=stock)
    show = Show.stub(auto_expire=True, expire_delay_days=0)
    order = Order.stub(
        status=OrderStatus.PENDING,
        expires_at=NOW - timedelta(hours=1),
        items=[Item.stub(allocations=[alloc])],
        show=show,
        total=Money(Decimal("10")),
    )
    r = expire_order(order, Coupon.stub(used=1), now=NOW)
    assert r.updated(order)[Order.status] == OrderStatus.EXPIRED
    assert r.updated(stock)[Stock.allocated] == Add(-2)
    assert r.removed(alloc)
    assert r.events == [OrderExpired(order_id=order.id)]
