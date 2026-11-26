"""Spike 0006, observations O1-O4, O6, O7 outside the decision tables: lines both checkers reject.

Rejected comparisons stand in an `assert` statement (see `fail_operands.py`). The `Load.when` line
passes a rejected comparison as an argument, so pyright adds `reportUnknownArgumentType` there.
"""

from decimal import Decimal

from domain import Item, Money, Order, PaymentMethod, Wallet
from lib import Load, Pred


def misuse(order: Order, other: Order) -> None:
    # fmt: off
    _narrow: Pred[Order] = Wallet.user_id == Order.user_id  # expect-error[reportAssignmentType, assignment]: O1/O4 a two-owner predicate is not Pred[Order]
    assert 0 <= Order.amount  # expect-error[reportOperatorIssue, operator]: O2 int on the left of a Decimal column  # noqa: SIM300 - the value on the left is the probe
    assert Order.total.path(Money.amount) >= 0  # expect-error[reportOperatorIssue, operator]: O3 design 11.8's line, no widening on a path
    assert Order.total.path(Money.currency) == Order.amount  # expect-error[reportOperatorIssue, operator]: O3 str path against a Decimal column
    Load.when(Order.paid_with == PaymentMethod.POINT, match=Wallet.user_id == Order.number)  # expect-error[reportOperatorIssue, reportUnknownArgumentType, operator]: O6 a mismatched match outside Annotated
    order.set(Order.items.add(Item(order_id=other.id, sku="A", price=Decimal(1))))  # expect-error[reportCallIssue, call-arg]: O7 another parent's key on an owned child
    # fmt: on
