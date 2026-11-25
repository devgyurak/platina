"""Design 11.8 `tests/typing/fail_misuse.py`, transcribed; codes are the observed ones."""

from uuid import UUID

from domain import (
    Coupon,
    Item,
    Order,
    OrderStatus,
    User,
    Wallet,
    apply_coupon,
    orders,
    pay,
    wallets,
)
from lib_design import Id


def misuse(oid: UUID, uid: Id[User], order: Order, item: Item, o: Order, c: Coupon) -> None:
    w: Wallet = wallets.by_user(uid)
    # fmt: off
    pay.bind(order=oid, wallet=w)                 # expect-error[reportArgumentType, arg-type]: UUID is not Order
    pay.bind(ordr=Order.ref(oid), wallet=w)       # expect-error[reportCallIssue, call-arg]: parameter name typo
    order.set(Order.status.to(123))               # expect-error[reportArgumentType, arg-type]: int is not OrderStatus
    order.status = OrderStatus.PAID               # expect-error[reportAttributeAccessIssue, arg-type]: snapshots are immutable (__set__ instance is Never)
    order.items.append(item)                      # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: Sequence has no append
    apply_coupon(o, c) + pay(o, w)                # expect-error[reportOperatorIssue, reportUnusedExpression, operator]: + not allowed between StepResults
    orders.by_number(42)                          # expect-error[reportArgumentType, arg-type]: Finder[Order, str]
    Order.new(number="A-1")                       # expect-error[reportCallIssue, call-arg]: required fields total, user_id missing
    # fmt: on
