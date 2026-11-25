"""F3 pinned: the misuse lines of `probe_f3_delta.py`, with the codes each checker reports."""

from decimal import Decimal

from lib_delta import Additive, Col


class Money(Additive[Decimal]):
    amount: Decimal


class Wallet:
    balance: Col[Money]
    count: Col[int]


# fmt: off
def f3() -> None:
    Wallet.balance.add("1")  # expect-error[reportCallIssue, reportArgumentType, call-overload]: neither the delta (Decimal) nor a Money
    Wallet.count.add("1")  # expect-error[reportArgumentType, arg-type]: str is not int (the first overload does not apply to an int column)
    Wallet.balance.to(Decimal("1"))  # expect-error[reportArgumentType, arg-type]: to takes the whole Money
# fmt: on
