"""Use case 3 (spike 0002) in the spike 0007 shapes - coupon then payment. Requirements R3.1-R3.7.

Changed from spike 0002: R3.3's "has this user redeemed this coupon" is a row-set load (#59
point 2) instead of the whole `User.redemptions` relation, and the redemption row is written with
`insert` (#60 point 4: `Coupon.redemptions` is not owned, so it has no `add`). R3.5 is use case 1's
`pay`, imported as spike 0002 did (ported to `insert(Payment(...))`, `uc01_payment.py`).
"""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Annotated
from uuid import UUID

import pytest
from domain import (
    Coupon,
    CouponNotApplicable,
    CouponRedemption,
    Money,
    Order,
    OrderStatus,
    User,
    Wallet,
    coupons,
    wallets,
)
from lib import (
    INJECTED,
    Add,
    App,
    Changes,
    Id,
    Load,
    Now,
    Op,
    RowSet,
    chain,
    insert,
    step,
    usecase,
)
from uc01_payment import ChargeableWallet, PayableOrder, pay

app = App(dsn="postgresql://app@primary/shop")


# R3.3: one row by (coupon, user), or none. Arguments bind to the use case's `coupon` and `user`.
def redemption_of(coupon: Coupon, user: User) -> RowSet[CouponRedemption]:
    return CouponRedemption.where(
        CouponRedemption.coupon_id == coupon.id, CouponRedemption.user_id == user.id
    )


prior_redemption = Load.after(redemption_of)  # a named value: checked by both (probe_annotated.py)
type PriorRedemption = Annotated[Sequence[CouponRedemption], prior_redemption]


@step
def apply_coupon(
    order: Order, coupon: Coupon, user: User, prior: Sequence[CouponRedemption]
) -> Changes:
    if order.user_id != user.id or not coupon.active:  # R3.1
        raise CouponNotApplicable(coupon.id)
    ops: list[Op[Coupon]] = []
    if coupon.usage_limit is not None:  # R3.2
        if coupon.used >= coupon.usage_limit:
            raise CouponNotApplicable(coupon.id)
        ops.append(Coupon.used.add(1))
    if coupon.once_per_customer and prior:  # R3.3: an empty row set means "never redeemed"
        raise CouponNotApplicable(coupon.id)
    if coupon.single_use:  # R3.4
        ops.append(Coupon.active.to(False))
    changes = order.set(
        Order.total.to(coupon.apply(order.total)), Order.coupon_id.to(coupon.id)
    ) + coupon.set(*ops)
    if coupon.once_per_customer:
        changes += insert(CouponRedemption(coupon_id=coupon.id, user_id=user.id))
    return changes


@usecase
def checkout(
    order: PayableOrder,
    coupon: Annotated[Coupon, Load()],
    user: Annotated[User, Load()],
    wallet: ChargeableWallet,
    prior: PriorRedemption = INJECTED,  # #48: a dependent load defaults to INJECTED
    now: Now = INJECTED,
) -> Changes:
    with chain(order, wallet) as (c, order, wallet):
        c.run(apply_coupon, order, coupon, user, prior)
        c.run(pay, order, wallet, now)  # R3.5 / R3.6: use case 1's rules
    return c.changes


# --------------------------------------------------------------------------- call site
async def post_checkout(order_id: UUID, user_id: Id[User], code: str, key: str) -> None:
    await app.run(
        checkout.bind(  # `prior` and `now` are left out (#48)
            order=Order.ref(order_id),
            coupon=coupons.by_code(code),
            user=User.ref(user_id),
            wallet=wallets.by_user(user_id),
        ),
        idempotency_key=key,
    )


# --------------------------------------------------------------------------- 4.12 unit tests
NOW = datetime(2026, 11, 26)


def test_checkout_counts_usage_and_records_the_redemption() -> None:
    user = User.stub()
    order = Order.stub(status=OrderStatus.PENDING, total=Money(Decimal("1000")), user_id=user.id)
    coupon = Coupon.stub(rate=Decimal("0.1"), usage_limit=10, used=3, once_per_customer=True)
    wallet = Wallet.stub(balance=Money(Decimal("5000")))
    r = checkout(order, coupon, user, wallet, prior=[], now=NOW)  # a direct call passes all (#48)
    assert r.updated(wallet)[Wallet.balance] == Add(Decimal("-900"))
    assert r.updated(coupon)[Coupon.used] == Add(1)
    assert len(r.inserted(CouponRedemption)) == 1


def test_second_use_by_the_same_customer_is_rejected() -> None:
    coupon, user = Coupon.stub(once_per_customer=True), User.stub()
    prior = [CouponRedemption.stub(coupon_id=coupon.id, user_id=user.id)]
    with pytest.raises(CouponNotApplicable):
        checkout(Order.stub(user_id=user.id), coupon, user, Wallet.stub(), prior=prior, now=NOW)
