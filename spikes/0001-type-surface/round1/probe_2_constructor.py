"""Item 2: constructor types from `__set__(self, instance: Never, value: T)`; `new`; required fields."""

from datetime import datetime
from decimal import Decimal
from typing import reveal_type

from domain import Item, Money, Order, OrderPaid, OrderStatus, User
from lib_design import Id


def probe(uid: Id[User], oid: Id[Order], money: Money, now: datetime, order: Order) -> None:
    reveal_type(Order)  # mypy prints the synthesised constructor
    reveal_type(Order.__init__)  # pyright prints the synthesised constructor
    reveal_type(Order.new)

    # positive
    reveal_type(Order.new(number="A-1", total=money, user_id=uid))
    reveal_type(
        Order.new(
            number="A-1",
            total=money,
            user_id=uid,
            status=OrderStatus.PAID,
            paid_with=None,
            paid_at=now,
        )
    )
    reveal_type(OrderPaid(order_id=oid, user_id=uid, total=money, paid_at=now))
    reveal_type(Money(Decimal("1000")))

    # negative (each must be rejected)
    Order.new(number="A-1")  # E1 missing total, user_id
    Order.new(number=1, total=money, user_id=uid)  # E2 int is not str
    Order.new(number="A-1", total=money, user_id=uid, version=3)  # E3 version_column not a param
    Order.new(number="A-1", total=money, user_id=uid, id=oid)  # E4 generated pk not a param
    Order.new(number="A-1", total=money, user_id=uid, created_at=now)  # E5 server_default
    Order.new(number="A-1", total=money, user_id=uid, items=[])  # E6 relation not a param
    Order.new("A-1", money, uid)  # E7 keyword only
    OrderPaid(order_id=oid, user_id=uid, total=money)  # E8 event missing paid_at
    order.status = OrderStatus.PAID  # E9 immutability

    # observations (type-level reach of the design's "one way")
    reveal_type(Order(number="A-1", total=money, user_id=uid))  # the plain constructor also types
    reveal_type(Order.stub(statuss=1))  # stub(**fields: object) is not field-checked
    reveal_type(Item.new(order_id=oid, position=1, price=money))
