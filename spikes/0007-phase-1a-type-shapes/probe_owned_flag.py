"""Spike 0007, round 4: `owned=` given a `bool` that is not a literal. Run per checker.

The overloads of `one_to_many` select on `Literal[True]` / `Literal[False]`; a plain `bool`
matches neither. Independent review observation: pyright accepts it, mypy rejects it.
"""

from domain import Item
from lib import Col, Entity, Id, Owned, Rel, one_to_many, pk


def flag() -> bool:
    return True


FLAG: bool = flag()

unannotated = one_to_many(lambda: Item.order_id, owned=FLAG)  # G0 no declared type


class G1(Entity, table="g1", aggregate_root=True):
    id: Col[Id[G1]] = pk()
    items: Owned[list[Item]] = one_to_many(lambda: Item.order_id, owned=FLAG)  # G1 declared Owned


class G2(Entity, table="g2", aggregate_root=True):
    id: Col[Id[G2]] = pk()
    items: Rel[list[Item]] = one_to_many(lambda: Item.order_id, owned=FLAG)  # G2 declared Rel
