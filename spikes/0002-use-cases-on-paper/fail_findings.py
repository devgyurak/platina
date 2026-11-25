"""Lines the use cases needed (or the design shows) that both checkers reject.

Each line carries the codes observed (`tools/typetests.py`); the use case files are clean and
point here.
"""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from domain import (
    Order,
    OrderExpired,
    OrderStatus,
    Payment,
    PaymentMethod,
    Show,
    Stock,
    User,
    Wallet,
    wallets,
)
from lib import App, Changes, Check, Id, Load, usecase
from uc01_payment import pay
from uc02_refund import refund_wallet

app = App(dsn="postgresql://app@primary/shop")


# fmt: off
# --- use case 1, R1.4: the value of `Changes.returning(v)` comes back as `object`
async def post_pay(order_id: UUID, user_id: Id[User], key: str) -> Id[Payment]:
    result = await app.run(pay.bind(order=Order.ref(order_id), wallet=wallets.by_user(user_id)), idempotency_key=key)
    return result.value  # expect-error[reportReturnType, return-value]: `result.value` is `object`


# --- use case 2 / design 4.7: the expression form of a dependent load (H2, #51). Written outside
# `Annotated` on purpose: inside `Annotated[...]` metadata mypy does not check the expression at
# all (probe_annotated_metadata.py), so only pyright would report it there.
refund_wallet_when = Load.when(Order.paid_with == PaymentMethod.WALLET, match=Wallet.user_id == Order.user_id)  # expect-error[reportOperatorIssue, reportUnknownArgumentType, operator]: #51 column-to-column


# --- use case 2 / design 4.7: a dependent-load parameter without a default. `bind` has the use
# case's signature (ParamSpec), so the caller must pass what the runner is to load. 4.7's
# `refund(order, wallet)` has this shape; the design does not say how a caller omits `wallet`.
@usecase
def refund_like_4_7(order: Annotated[Order, Load(Order.items)], wallet: Annotated[Wallet | None, Load.after(refund_wallet)]) -> Changes:
    raise NotImplementedError


def call_refund_like_4_7(oid: UUID) -> None:
    refund_like_4_7.bind(order=Order.ref(oid))  # expect-error[reportCallIssue, call-arg]: `wallet` is a required bind argument


# --- use case 4: a check between two columns of one row (#51)
stock_check = Check(lambda: Stock.allocated <= Stock.quantity)  # expect-error[reportOperatorIssue, reportUnknownLambdaType, operator]: #51 column-to-column


# --- use case 7: the set change of 4.3 / 4.8 for R7.1-R7.5
def expire_due_set_change(now: datetime) -> Changes:
    return (
        Order.where(
            Order.status == OrderStatus.PENDING,
            Order.expires_at < now,
            Show.auto_expire == True,  # expect-error[reportArgumentType, arg-type]: R7.1 a predicate over the order's show is `Pred[Show]`  # noqa: E712
        )
        # R7.1 `expires_at + show.expire_delay_days < now`: no column arithmetic, no join
        # R7.5 "at most 100": no limit on a set change
        .set(Order.status.to(OrderStatus.EXPIRED), Order.expired_at.to(now), unsafe_bypass="expiry never sets PAID")  # 4.13: `@invariant` on `Order.status`
        .emit_each(OrderExpired, order_id=Order.id)
        # R7.3 coupon usage and stock allocations of each expired order: rows of other tables
        # R7.4 the number of expired rows: a set change returns no value to the use case
    )
# fmt: on
