"""Spike 0007 type reproduction, round 4: lines both checkers must accept."""

from collections.abc import Sequence
from typing import assert_type

from domain import Item, Order, Stock, Variant
from lib import Check, Load, Pred, Profile, Relation, RelColumn


# (a) spike 0006's overloads on all six operators, column against column of one entity
def a() -> None:
    assert_type(Stock.allocated <= Stock.quantity, Pred[Stock])
    assert_type(Stock.allocated < Stock.quantity, Pred[Stock])
    assert_type(Stock.allocated >= Stock.quantity, Pred[Stock])
    assert_type(Stock.allocated > Stock.quantity, Pred[Stock])
    assert_type(Stock.allocated == Stock.quantity, Pred[Stock])
    assert_type(Stock.allocated != Stock.quantity, Pred[Stock])
    assert_type(Stock.quantity >= Item.quantity, Pred[Stock | Item])  # two owners


stock_check = Check(lambda: Stock.allocated <= Stock.quantity)


# (b) relations are load paths
def b() -> None:
    assert_type(Order.items.load(Item.allocations), Relation[Order, Item])
    assert_type(Stock.warehouse.load(), RelColumn[Stock, Warehouse_])


nested = Profile(Order.items.load(Item.allocations), Order.show)


# (c) the list form takes any Sequence[E]
def variants_tuple(order: Order) -> tuple[Variant, ...]:
    return tuple(Variant.ref(i.variant_id) for i in order.items)


def variants_seq(order: Order) -> Sequence[Variant]:
    return [Variant.ref(i.variant_id) for i in order.items]


tuple_load = Load.after(variants_tuple, Variant.stocks)
seq_load = Load.after(variants_seq, Variant.stocks.load(Stock.warehouse))

from domain import Warehouse as Warehouse_  # noqa: E402
