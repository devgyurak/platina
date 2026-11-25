"""Design 11.8 `tests/typing/pass_composition.py`, transcribed; only the scaffolding is added."""

from typing import assert_type
from uuid import UUID

from domain import Money, Order, OrderStatus, OrderSummary, User, Wallet, orders, pay, wallets
from lib_design import App, Changes, Column, ConsistencyToken, Id, chain

app = App(dsn="postgresql://app@primary/shop")


async def composition(oid: UUID, uid: Id[User], order: Order, wallet: Wallet, money: Money) -> None:
    result = await app.run(pay.bind(order=Order.ref(oid), wallet=wallets.by_user(uid)))
    assert_type(result.token, ConsistencyToken)
    rows = await app.query(orders.summaries(user_id=uid))
    assert_type(rows, list[OrderSummary])
    assert_type(Order.status, Column[OrderStatus])
    assert_type(order.status, OrderStatus)
    with chain(order, wallet) as (c, o2, w2):
        assert_type(o2, Order)
        assert_type(w2, Wallet)
    assert_type(c.changes, Changes)
    new = Order.new(number="A-1", total=money, user_id=uid)  # required-field check
    assert_type(new, Order)
