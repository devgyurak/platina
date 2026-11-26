"""Spike 0007 type reproduction, round 5: lines both checkers must accept."""

from typing import assert_type

from domain import Item, Order, OrderStatus
from lib import Changes, Pred, Relation, RowSet, count, select


def r17(preds: list[Pred[Order]]) -> Changes:  # R17: an unpacked list may be empty at run time
    rows = Order.where(*preds)
    assert_type(rows, RowSet[Order])
    return rows.delete() + Order.where(*preds).set(Order.status.to(OrderStatus.EXPIRED))


def two() -> RowSet[Order]:
    return Order.where(Order.status == OrderStatus.PENDING, Order.number == "A1")


def relation_where_unchanged() -> None:
    assert_type(
        Order.items.where(), Relation[Order, Item]
    )  # a relation's where: no predicate needed


class Row:
    n: int


query = select(Row, n=count(Order.id)).where()  # the query path: unchanged
