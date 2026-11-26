"""Spike 0007, rounds 4-5: `owned=` given a constant instead of a literal. Run per checker.

The overloads of `one_to_many` (the rejected `owned=` alternative) select on `Literal[True]` /
`Literal[False]`. Two kinds of constant:
- initialised from a call (`FLAG: bool = flag()`, G0-G2): both checkers reject it (round 4);
- initialised from a literal (`ANNOTATED: bool = True`, `BARE = True`, G3-G4; the independent
  review's case, round 5): pyright narrows it to the literal and accepts it, mypy rejects it.
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


ANNOTATED: bool = True
BARE = True


class G3(Entity, table="g3", aggregate_root=True):
    id: Col[Id[G3]] = pk()
    items: Owned[list[Item]] = one_to_many(
        lambda: Item.order_id, owned=ANNOTATED
    )  # G3 annotated, literal init


class G4(Entity, table="g4", aggregate_root=True):
    id: Col[Id[G4]] = pk()
    items: Owned[list[Item]] = one_to_many(
        lambda: Item.order_id, owned=BARE
    )  # G4 bare, literal init
