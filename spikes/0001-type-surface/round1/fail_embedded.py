"""Item 4: the design form and the misuse each alternative must reject."""

from decimal import Decimal

from domain import Money, Order, Wallet
from lib_design import Check, Entity
from lib_embedded_variants import ACol, Additive, Emb, PCol, embedded_a, embedded_e, embedded_p
from lib_embedded_variants import value as value_c


class OrderB(Entity, table="orders_b"):
    total: PCol[Money] = embedded_p(prefix="total_")


@value_c
class MoneyC:
    amount: PCol[Decimal]


class OrderC(Entity, table="orders_c"):
    total: Emb[MoneyC] = embedded_e(prefix="total_")


@value_c
class MoneyD(Additive[Decimal]):
    amount: Decimal


class WalletD(Entity, table="wallets_d"):
    balance: ACol[MoneyD] = embedded_a(prefix="balance_")


# fmt: off
def design_form() -> None:
    _ = Order.total.amount  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType, attr-defined]: Column[Money] has no amount
    Wallet.balance.add(Decimal("1"))  # expect-error[reportArgumentType, arg-type]: Column[Money].add takes a Money
    Check(lambda: Order.total.amount >= 0)  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownLambdaType, attr-defined]: 4.2 Meta.checks


def b2_getter() -> None:
    OrderB.total.at(lambda m: m.rate)  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownLambdaType, attr-defined]: Money has no rate
    OrderB.total.at(lambda m: m.amount).add("1")  # expect-error[reportArgumentType, arg-type]: str is not Decimal


def c_value_class() -> None:
    OrderC.total.to(MoneyC(amount=Decimal("1")))  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, attr-defined]: without a Value base, type[MoneyC] has no to


def d_declared_delta() -> None:
    WalletD.balance.add_delta(Decimal("-1"))  # expect-error[reportAttributeAccessIssue, reportUnknownMemberType, misc, arg-type]: Column is contravariant, the delta type cannot be extracted
# fmt: on
