"""Round 4 own probe (e): owned= given a bool that is not a literal, per checker."""

from domain import Item
from lib import Col, Entity, Id, Owned, Rel, one_to_many, pk


def flag() -> bool:
    return True


FLAG: bool = flag()


class Parent(Entity, table="parents"):
    id: Col[Id[Parent]] = pk(generated="uuid7")
    a: Owned[list[Item]] = one_to_many(lambda: Item.order_id, owned=FLAG)  # line 16
    b: Rel[list[Item]] = one_to_many(lambda: Item.order_id, owned=FLAG)  # line 17


unannotated = one_to_many(lambda: Item.order_id, owned=FLAG)  # line 20: no declared type
