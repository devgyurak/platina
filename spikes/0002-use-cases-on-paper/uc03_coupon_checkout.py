"""Use case 3 - coupon then payment (`chain`). Requirements R3.1-R3.7.

Source: saleor/saleor `checkout/complete_checkout.py` (`_increase_checkout_voucher_usage`,
`_process_payment`), `discount/utils/voucher.py` `increase_voucher_usage`. Rules restated.
"""

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
from lib import INJECTED, Add, App, Changes, Id, Load, Now, Op, chain, step, usecase
from uc01_payment import ChargeableWallet, PayableOrder, pay

app = App(dsn="postgresql://app@primary/shop")

# R3.3 needs "has this user redeemed this coupon": one row by (coupon_id, user_id), or its absence.
# There is no Finder over two columns and no parameterised partial load
# (`Coupon.redemptions.where(CouponRedemption.user_id == <the order's user>)`), so the use case
# loads all redemptions of the user through a relation declared only for this.
type RedeemingUser = Annotated[User, Load(User.redemptions)]


@step
def apply_coupon(order: Order, coupon: Coupon, user: User) -> Changes:
    if order.user_id != user.id:
        raise CouponNotApplicable(coupon.id)
    if not coupon.active:  # R3.1
        raise CouponNotApplicable(coupon.id)
    ops: list[Op[Coupon]] = []
    if coupon.usage_limit is not None:  # R3.2: read and increment of one row
        if coupon.used >= coupon.usage_limit:
            raise CouponNotApplicable(coupon.id)
        ops.append(Coupon.used.add(1))
    if coupon.once_per_customer:  # R3.3
        if any(r.coupon_id == coupon.id for r in user.redemptions):
            raise CouponNotApplicable(coupon.id)
        ops.append(Coupon.redemptions.add(CouponRedemption(coupon_id=coupon.id, user_id=user.id)))
    if coupon.single_use:  # R3.4
        ops.append(Coupon.active.to(False))
    return order.set(
        Order.total.to(coupon.apply(order.total)), Order.coupon_id.to(coupon.id)
    ) + coupon.set(*ops)


@usecase
def checkout(
    order: PayableOrder,
    coupon: Annotated[Coupon, Load()],
    user: RedeemingUser,
    wallet: ChargeableWallet,
    now: Now = INJECTED,
) -> Changes:
    with chain(order, wallet) as (c, order, wallet):
        c.run(apply_coupon, order, coupon, user)
        c.run(pay, order, wallet, now)  # R3.5/R3.6: one transaction, a failed pay rolls back all
    return c.changes


# --------------------------------------------------------------------------- call site
async def post_checkout(order_id: UUID, user_id: Id[User], code: str, key: str) -> None:
    await app.run(
        checkout.bind(
            order=Order.ref(order_id),
            coupon=coupons.by_code(code),
            user=User.ref(user_id),
            wallet=wallets.by_user(user_id),
        ),
        idempotency_key=key,
    )


# --------------------------------------------------------------------------- 4.12 unit tests
NOW = datetime(2026, 11, 25)


def test_checkout_charges_discounted_total_and_counts_usage() -> None:
    user = User.stub(redemptions=[])
    order = Order.stub(status=OrderStatus.PENDING, total=Money(Decimal("1000")), user_id=user.id)
    coupon = Coupon.stub(rate=Decimal("0.1"), usage_limit=10, used=3, once_per_customer=True)
    wallet = Wallet.stub(balance=Money(Decimal("5000")))
    r = checkout(order, coupon, user, wallet, now=NOW)
    assert r.updated(wallet)[Wallet.balance] == Add(Decimal("-900"))
    assert r.updated(coupon)[Coupon.used] == Add(1)
    assert len(r.inserted(CouponRedemption)) == 1


def test_second_use_by_the_same_customer_is_rejected() -> None:
    coupon = Coupon.stub(once_per_customer=True)
    user = User.stub(redemptions=[CouponRedemption.stub(coupon_id=coupon.id)])
    order = Order.stub(user_id=user.id)
    with pytest.raises(CouponNotApplicable):
        checkout(order, coupon, user, Wallet.stub(), now=NOW)
