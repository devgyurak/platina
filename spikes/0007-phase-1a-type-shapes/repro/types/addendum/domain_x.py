"""Addendum repro (type-reviewer): entities for A1 (a grandchild) and A3 (a `Part` child).

GOrder owns GLine, and GLine - an owned child - declares `owns_many` itself. ADR-0010's seal rule
rejects that declaration at seal time; the types let it through, which is what A1 probes.
MOrder owns MLine, declared on the `Part` base (A3).
"""

from lib import Col, Entity, Id, Owned, Part, column, owns_many, parent_fk, pk


class GOrder(Entity, table="g_orders", aggregate_root=True):
    id: Col[Id[GOrder]] = pk(generated="uuid7")
    number: Col[str] = column()
    lines: Owned[list[GLine]] = owns_many(lambda: GLine.order_id)


class GLine(Entity, table="g_lines"):
    id: Col[Id[GLine]] = pk(generated="uuid7")
    order_id: Col[Id[GOrder]] = parent_fk(lambda: GOrder)
    quantity: Col[int] = column()
    parts: Owned[list[GPart]] = owns_many(lambda: GPart.line_id)  # seal error, not a type error


class GPart(Entity, table="g_parts"):
    id: Col[Id[GPart]] = pk(generated="uuid7")
    line_id: Col[Id[GLine]] = parent_fk(lambda: GLine)
    sku: Col[str] = column()


class MOrder(Entity, table="m_orders", aggregate_root=True):
    id: Col[Id[MOrder]] = pk(generated="uuid7")
    number: Col[str] = column()
    lines: Owned[list[MLine]] = owns_many(lambda: MLine.order_id)


class MLine(Part, table="m_lines"):
    id: Col[Id[MLine]] = pk(generated="uuid7")
    order_id: Col[Id[MOrder]] = parent_fk(lambda: MOrder)
    quantity: Col[int] = column()
