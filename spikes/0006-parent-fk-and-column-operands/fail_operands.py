"""Spike 0006, part B (#51): the comparison misuse lines, with the observed codes.

Each rejected comparison stands in an `assert` statement. pyright strict adds another code to
every other use of an expression that failed to type (`reportUnusedExpression` on a bare
expression, `reportUnknownVariableType` on an assignment or a `return`, `reportUnknownArgumentType`
on a call argument); in an `assert` both checkers report the operator code alone, and an accepted
comparison reports nothing (spike 0006, Method).
"""

from decimal import Decimal

from domain import Order, Wallet


def misuse() -> None:
    # fmt: off
    assert Order.amount >= 0  # expect-error[reportOperatorIssue, operator]: B2 no numeric widening to Decimal
    assert Order.amount >= 1.5  # expect-error[reportOperatorIssue, operator]: B3 float is not Decimal
    assert Order.amount >= "1"  # expect-error[reportOperatorIssue, operator]: B3 str is not Decimal
    assert Order.qty >= Decimal(1)  # expect-error[reportOperatorIssue, operator]: B3 Decimal is not int
    assert Wallet.user_id == Order.number  # expect-error[reportOperatorIssue, operator]: B8 Id[User] column against a str column
    assert Order.qty == Order.amount  # expect-error[reportOperatorIssue, operator]: B9 int column against a Decimal column
    assert Order.amount >= Order.qty  # expect-error[reportOperatorIssue, operator]: B9 Decimal column against an int column
    Order.where(Order.user_id == Wallet.user_id)  # expect-error[reportArgumentType, arg-type]: B12 a predicate over Order | Wallet
    Order.where(Wallet.user_id == Order.user_id)  # expect-error[reportArgumentType, arg-type]: B12 a predicate over Wallet | Order
    # fmt: on
