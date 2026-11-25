"""P-C: design 11.8 `fail_misuse` and the round-2 misuse lines, with the observed codes."""

from uuid import UUID

from domain_final import (
    Coupon,
    Item,
    Money,
    Order,
    OrderExpired,
    OrderPaid,
    OrderStatus,
    User,
    Wallet,
    apply_coupon,
    orders,
    pay,
    wallets,
)
from lib_final import Id


class Rate:
    pass


def misuse(
    oid: UUID, uid: Id[User], order: Order, item: Item, o: Order, c: Coupon, m: Money
) -> None:
    w: Wallet = wallets.by_user(uid)
    # fmt: off
    # design 11.8
    pay.bind(order=oid, wallet=w)                 # expect-error[reportArgumentType, arg-type]: UUID is not Order
    pay.bind(ordr=Order.ref(oid), wallet=w)       # expect-error[reportCallIssue, call-arg]: parameter name typo
    order.set(Order.status.to(123))               # expect-error[reportArgumentType, arg-type]: int is not OrderStatus
    order.status = OrderStatus.PAID               # expect-error[reportAttributeAccessIssue, misc, arg-type]: snapshots are immutable
    order.items.append(item)                      # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: Sequence has no append
    apply_coupon(o, c) + pay(o, w)                # expect-error[reportOperatorIssue, reportUnusedExpression, operator]: + not allowed between StepResults
    orders.by_number(42)                          # expect-error[reportArgumentType, arg-type]: Finder[Order, str]
    Order(number="A-1")                           # expect-error[reportCallIssue, call-arg]: required fields total, user_id missing
    # owner propagation (P-A)
    order.set(Wallet.balance.to(m))               # expect-error[reportArgumentType, arg-type]: an operation of another entity
    Order.total.path(Wallet.balance)              # expect-error[reportArgumentType, arg-type]: not a field of Money
    Order.items.update(item, Order.status.to(OrderStatus.PAID))  # expect-error[reportArgumentType, arg-type]: parent op in a child update
    Order.items.update(item, Wallet.balance.to(m))  # expect-error[reportArgumentType, arg-type]: other entity's op in a child update
    w.set(Order.items.add(item))                  # expect-error[reportArgumentType, arg-type]: another entity's relation op
    Order.where(Wallet.user_id == uid)            # expect-error[reportArgumentType, arg-type]: another entity's predicate
    Order.where(Order.status == OrderStatus.PENDING).set(Wallet.balance.to(m))  # expect-error[reportArgumentType, arg-type]: set-change op of another entity
    Order.items.add(c)                            # expect-error[reportArgumentType, arg-type]: wrong child type
    Order.new(number="A-1")                       # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: there is no new
    # emit_each takes columns of the set change's own entity (added after the round-2 reproduction)
    Order.where(Order.status == OrderStatus.PENDING).emit_each(OrderExpired, order_id=Wallet.id)  # expect-error[reportArgumentType, arg-type]: another entity's column
    Order.where(Order.status == OrderStatus.PENDING).emit_each(OrderPaid, order_id=Order.id, user_id=Wallet.user_id)  # expect-error[reportArgumentType, arg-type]: mixed owners
    # fmt: on
