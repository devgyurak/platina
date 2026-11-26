"""Addendum for ADR-0010: entities only these probes need (the spike's `domain.py` is unchanged).

- `GOrder` / `GLine` / `GPart`: an owned child (`GLine`) that itself declares an owned relation
  (`GLine.parts`). ADR-0010 makes that a seal error (ownership is one level deep); here it only
  has to type-check, so that `fail_addendum.py` can show what A1's narrowed `update` rejects.
- `MOrder` / `MLine`: A3, the alternative of a type-level marker for owned children (`Part`).
"""

from lib import Col, Entity, Id, Owned, Part, column, owns_many, parent_fk, pk


class GOrder(Entity, table="g_orders", aggregate_root=True):
    id: Col[Id[GOrder]] = pk(generated="uuid7")
    lines: Owned[list[GLine]] = owns_many(lambda: GLine.order_id)


class GLine(Entity, table="g_lines"):
    id: Col[Id[GLine]] = pk(generated="uuid7")
    order_id: Col[Id[GOrder]] = parent_fk(lambda: GOrder)
    quantity: Col[int] = column()
    parts: Owned[list[GPart]] = owns_many(lambda: GPart.line_id)  # seal error under ADR-0010


class GPart(Entity, table="g_parts"):
    id: Col[Id[GPart]] = pk(generated="uuid7")
    line_id: Col[Id[GLine]] = parent_fk(lambda: GLine)
    label: Col[str] = column()


class MOrder(Entity, table="m_orders", aggregate_root=True):
    id: Col[Id[MOrder]] = pk(generated="uuid7")
    note: Col[str] = column()
    lines: Owned[list[MLine]] = owns_many(lambda: MLine.order_id)


class MLine(Part, table="m_lines"):  # A3: an owned child declared on the `Part` base
    id: Col[Id[MLine]] = pk(generated="uuid7")
    order_id: Col[Id[MOrder]] = parent_fk(lambda: MOrder)
    quantity: Col[int] = column()
