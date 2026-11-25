"""Item 4: what does type-check for embedded paths and value-object increments."""

from decimal import Decimal
from typing import assert_type

from domain import Coupon, Money
from lib_design import Column, Entity, Op
from lib_embedded_variants import Emb, PathColumn, PCol, Value, embedded_e, embedded_p
from lib_embedded_variants import value as value_c


class OrderB(Entity, table="orders_b"):
    total: PCol[Money] = embedded_p(prefix="total_")


@value_c
class MoneyC(Value):
    amount: PCol[Decimal]
    currency: PCol[str]


class OrderC(Entity, table="orders_c"):
    total: Emb[MoneyC] = embedded_e(prefix="total_")


def b1_path() -> None:
    assert_type(Money.amount, Decimal)  # a plain value-class attribute on the class
    assert_type(OrderB.total.path(Money.amount), Column[Decimal])
    # observation: a field of another class is accepted and gives a nonsense type
    assert_type(OrderB.total.path(Coupon.rate), Column[Column[Decimal]])


def b2_getter() -> None:
    assert_type(OrderB.total.at(lambda m: m.amount), Column[Decimal])
    assert_type(OrderB.total.at(lambda m: m.amount).add(Decimal("-1")), Op)


def c_value_class(order: OrderC) -> None:
    assert_type(OrderC.total, type[MoneyC])
    assert_type(OrderC.total.amount, PathColumn[Decimal])
    assert_type(order.total.amount, Decimal)
    assert_type(OrderC.total.to(MoneyC(amount=Decimal("1"), currency="KRW")), Op)
    assert_type(OrderC.total.amount.add(Decimal("-1")), Op)
    # observation: the class leaks - this constructs a value at the type level
    assert_type(OrderC.total(amount=Decimal("1"), currency="KRW"), MoneyC)
