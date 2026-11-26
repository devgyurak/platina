"""Spike 0007 type reproduction, round 5: lines both checkers must reject."""

from domain import Money, Order, OrderStatus
from lib import Entity


def f(m: Money) -> None:
    # fmt: off
    Order.where()  # expect-error[reportCallIssue, call-arg]: F32 no predicate
    Order.where().delete()  # expect-error[reportCallIssue, reportUnknownMemberType, call-arg]: F33 no predicate
    Order.where().set(Order.total.to(m))  # expect-error[reportCallIssue, reportUnknownMemberType, call-arg]: F34 no predicate
    Entity.where()  # expect-error[reportCallIssue, call-arg]: H1 the base class too
    Order.where(pred=Order.status == OrderStatus.PENDING)  # expect-error[reportCallIssue, call-arg]: H2 pred is positional-only
    # fmt: on
