"""Round 5 own probe (a): owned= (the rejected alternative) given constants, per checker."""

from typing import Final

from domain import Item
from lib import Col, Entity, Id, Owned, Rel, one_to_many, pk


def flag() -> bool:
    return True


ANNOTATED: bool = True
BARE = True
FINAL: Final = True
FLAG: bool = flag()


class Parent(Entity, table="parents"):
    id: Col[Id[Parent]] = pk(generated="uuid7")
    a: Owned[list[Item]] = one_to_many(lambda: Item.order_id, owned=ANNOTATED)  # line 21
    b: Owned[list[Item]] = one_to_many(lambda: Item.order_id, owned=BARE)  # line 22
    c: Owned[list[Item]] = one_to_many(lambda: Item.order_id, owned=FINAL)  # line 23
    d: Owned[list[Item]] = one_to_many(lambda: Item.order_id, owned=FLAG)  # line 24
    e: Rel[list[Item]] = one_to_many(lambda: Item.order_id, owned=ANNOTATED)  # line 25
    f: Rel[list[Item]] = one_to_many(lambda: Item.order_id, owned=FLAG)  # line 26
