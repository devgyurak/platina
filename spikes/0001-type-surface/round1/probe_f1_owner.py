"""Follow-up F1: owner-typed columns - `Order.total.path(Money.amount)` checked, owner of `.set`."""

from decimal import Decimal
from typing import reveal_type

from lib_owner import Col, Entity, Finder, Repository, column, value


@value
class Money:
    amount: Col[Decimal]
    currency: Col[str]


@value
class Rate:
    amount: Col[Decimal]


class Order(Entity, table="orders"):
    number: Col[str] = column()
    total: Col[Money] = column()


class Wallet(Entity, table="wallets"):
    balance: Col[Money] = column()


class OrderRepo(Repository[Order]):
    by_number = Finder(Order.number)
    wrong = Finder(Wallet.balance)  # O1 another entity's column in Repository[Order]


orders = OrderRepo()


def probe(order: Order, wallet: Wallet, m: Money) -> None:
    reveal_type(Order.number)
    reveal_type(order.number)
    reveal_type(Money.amount)
    reveal_type(m.amount)
    reveal_type(Money(amount=Decimal("1"), currency="KRW"))
    reveal_type(Order.new(number="A-1", total=m))
    reveal_type(Order.total.path(Money.amount))
    reveal_type(Wallet.balance.path(Money.amount).add(Decimal("-1")))
    reveal_type(Order.total.path(Money.amount) >= Decimal(0))
    order.set(Order.number.to("A-2"), Order.total.path(Money.amount).to(Decimal("1")))
    wallet.set(Wallet.balance.path(Money.amount).add(Decimal("-1")))
    reveal_type(OrderRepo.by_number)
    reveal_type(orders.by_number("A-1"))
    reveal_type(orders.wrong)

    Order.total.path(Rate.amount)  # N1 a field of another value class
    Order.total.path(Wallet.balance)  # N2 an entity field
    order.set(Wallet.balance.to(m))  # N3 an operation of another entity
    order.set(Wallet.balance.path(Money.amount).add(Decimal("1")))  # N4 same, through a path
    Order.number.path(Money.amount)  # N5 path on a non-embedded column
    Order.total.path(Money.amount).add("1")  # N6 wrong delta type
