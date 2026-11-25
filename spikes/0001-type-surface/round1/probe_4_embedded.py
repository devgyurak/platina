"""Item 4: embedded paths and value-object operations."""

from decimal import Decimal
from typing import reveal_type

from domain import Coupon, Money, Order, Wallet
from lib_design import Check, Entity
from lib_embedded_variants import (
    ACol,
    Additive,
    Emb,
    PCol,
    Value,
    embedded_a,
    embedded_e,
    embedded_p,
)
from lib_embedded_variants import value as value_c

# ---- (a) the design form, Money as in 4.2 (plain annotations), total: Col[Money]
reveal_type(Order.total)
reveal_type(Money.amount)  # what a plain value-class attribute is on the class
_ = Order.total.amount  # A1 design: Column[Decimal] expected
Wallet.balance.add(Decimal("1"))  # A2 design: value-object increment by a Decimal
Check(lambda: Order.total.amount >= 0)  # A3 design 4.2 Meta.checks


# ---- (b) path helpers on a Column subclass
class OrderB(Entity, table="orders_b"):
    total: PCol[Money] = embedded_p(prefix="total_")


reveal_type(OrderB.total.path(Money.amount))  # b1
reveal_type(OrderB.total.path(Coupon.rate))  # b1 negative: not a Money field, is it rejected?
reveal_type(OrderB.total.at(lambda m: m.amount))  # b2
OrderB.total.at(lambda m: m.rate)  # b2 negative: Money has no rate
reveal_type(OrderB.total.at(lambda m: m.amount).add(Decimal("-1")))  # b2 increment
OrderB.total.at(lambda m: m.amount).add("1")  # b2 increment negative


# ---- (c) embedded descriptor returning the value class; value fields declared Col[...]
@value_c
class MoneyC:
    amount: PCol[Decimal]
    currency: PCol[str]


class OrderC(Entity, table="orders_c"):
    total: Emb[MoneyC] = embedded_e(prefix="total_")


def probe_c(order: OrderC) -> None:
    reveal_type(OrderC.total)
    reveal_type(OrderC.total.amount)  # design syntax Order.total.amount
    reveal_type(order.total.amount)
    reveal_type(MoneyC(amount=Decimal("1"), currency="KRW"))
    OrderC.total.to(MoneyC(amount=Decimal("1"), currency="KRW"))  # C1 whole-value write
    reveal_type(OrderC.total(amount=Decimal("1"), currency="KRW"))  # C2 the class leaks


# ---- (d) declared delta type: Wallet.balance.add_delta(Decimal)
@value_c
class MoneyD(Additive[Decimal]):
    amount: Decimal
    currency: str = "KRW"


class WalletD(Entity, table="wallets_d"):
    balance: ACol[MoneyD] = embedded_a(prefix="balance_")


reveal_type(WalletD.balance.add_delta(Decimal("-1")))
WalletD.balance.add_delta("1")  # D1 negative


# ---- (c') as (c), with a Value base class supplying `to` on the class
@value_c
class MoneyC2(Value):
    amount: PCol[Decimal]
    currency: PCol[str]


class OrderC2(Entity, table="orders_c2"):
    total: Emb[MoneyC2] = embedded_e(prefix="total_")


reveal_type(OrderC2.total.amount)
reveal_type(OrderC2.total.to(MoneyC2(amount=Decimal("1"), currency="KRW")))
reveal_type(OrderC2.total.amount.add(Decimal("-1")))
