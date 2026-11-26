"""Spike 0006, observations O1-O4, O6, O7 outside the decision tables: lines both checkers accept."""

from decimal import Decimal
from typing import assert_type

from domain import Money, Order, Payment, PaymentMethod, Wallet
from lib import Changes, Load, Pred, SetChange


def takes_wide(predicate: Pred[Order | Wallet], /) -> None: ...
def takes_any(predicate: Pred[object], /) -> None: ...


def pred_variance() -> None:
    # O1: Pred[O] is covariant - a narrower predicate is accepted where a wider one is expected.
    takes_wide(Order.qty <= Order.cap)
    takes_any(Wallet.user_id == Order.user_id)


def value_on_the_left() -> None:
    # O2: the reflected operator of the column answers.
    assert_type(Decimal(0) <= Order.amount, Pred[Order])


def paths() -> None:
    # O3: an embedded path is a column of the root.
    assert_type(Order.total.path(Money.amount) >= Decimal(0), Pred[Order])  # 4.2's check
    assert_type(Order.amount >= Order.total.path(Money.amount), Pred[Order])
    assert_type(
        Order.total.path(Money.amount) == Wallet.balance.path(Money.amount), Pred[Order | Wallet]
    )


def takes_narrow(predicate: Pred[Order], /) -> None: ...


def under_an_expected_type() -> None:
    # O4: a same-entity column comparison under an expected Pred[Order].
    takes_narrow(Order.amount >= Order.total.path(Money.amount))
    assert_type(Order.where(Order.qty <= Order.cap, Order.amount >= Decimal(0)), SetChange[Order])


def load_when() -> None:
    # O6: 4.7's expression form outside `Annotated` (both checkers check it).
    assert_type(
        Load.when(Order.paid_with == PaymentMethod.POINT, match=Wallet.user_id == Order.user_id),
        Load,
    )


def wrong_parent_non_owned(order: Order, other: Order) -> None:
    # O7: spike 0002 probe_accepted.py item 6 is still writable for a non-owned child (#60).
    p = Payment(order_id=other.id, amount=Decimal(1))
    assert_type(order.set(Order.payments.add(p)), Changes)
