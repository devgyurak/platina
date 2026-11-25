"""Spike 0004: catalog snapshot of one schema, taken with `search_path` set to that schema."""

from typing import Any

import psycopg

QUERIES: dict[str, str] = {
    "tables": """
        SELECT c.relname, c.relkind::text, c.relispartition,
               pg_get_partkeydef(c.oid), pg_get_expr(c.relpartbound, c.oid),
               (SELECT p.relname FROM pg_inherits i JOIN pg_class p ON p.oid = i.inhparent
                 WHERE i.inhrelid = c.oid)
          FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = %(s)s AND c.relkind IN ('r', 'p') AND c.relname <> 'alembic_version'
    """,
    "columns": """
        SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull,
               pg_get_expr(d.adbin, d.adrelid)
          FROM pg_attribute a
          JOIN pg_class c ON c.oid = a.attrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
          LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
         WHERE n.nspname = %(s)s AND c.relkind IN ('r', 'p') AND a.attnum > 0
           AND NOT a.attisdropped AND c.relname <> 'alembic_version'
    """,
    "constraints": """
        SELECT c.relname, con.conname, con.contype::text, pg_get_constraintdef(con.oid)
          FROM pg_constraint con
          JOIN pg_class c ON c.oid = con.conrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = %(s)s AND c.relname <> 'alembic_version'
    """,
    "indexes": """
        SELECT c.relname, i.relname, pg_get_indexdef(i.oid)
          FROM pg_index x
          JOIN pg_class i ON i.oid = x.indexrelid
          JOIN pg_class c ON c.oid = x.indrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = %(s)s AND c.relname <> 'alembic_version'
    """,
    "triggers": """
        SELECT c.relname, t.tgname, pg_get_triggerdef(t.oid)
          FROM pg_trigger t
          JOIN pg_class c ON c.oid = t.tgrelid
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = %(s)s AND NOT t.tgisinternal
    """,
    "functions": """
        SELECT p.proname, pg_get_function_identity_arguments(p.oid), p.prosrc
          FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
         WHERE n.nspname = %(s)s
    """,
}

Snapshot = dict[str, list[tuple[Any, ...]]]


def snapshot(conn: psycopg.Connection[Any], schema: str) -> Snapshot:
    conn.execute(f"SET search_path TO {schema}")
    out: Snapshot = {}
    for section, sql in QUERIES.items():
        rows = conn.execute(sql, {"s": schema}).fetchall()
        out[section] = sorted(
            tuple(v.replace(f"{schema}.", "") if isinstance(v, str) else v for v in row)
            for row in rows
        )
    conn.execute("RESET search_path")
    return out


def diff(actual: Snapshot, expected: Snapshot) -> list[str]:
    lines: list[str] = []
    for section in QUERIES:
        a, e = set(actual.get(section, [])), set(expected.get(section, []))
        lines.extend(f"  - {section} missing: {row}" for row in sorted(e - a, key=repr))
        lines.extend(f"  + {section} extra:   {row}" for row in sorted(a - e, key=repr))
    return lines


def render(snap: Snapshot, sections: tuple[str, ...] = tuple(QUERIES)) -> str:
    lines: list[str] = []
    for section in sections:
        lines.append(f"  [{section}]")
        lines.extend(f"    {row}" for row in snap[section])
    return "\n".join(lines)
