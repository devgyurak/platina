"""Spike 0004: probes outside the main loop.

    uv run python spikes/0004-alembic-round-trip/probes.py

P1 (H6) a primary key / unique constraint on a partitioned table without the partition key.
P2 (H9) the naive rename rewrite: stock AlterColumnOp(modify_name) / RenameTableOp + reverse().
P3 an alternative for item 5 (evaluated, not chosen): an `include_name` filter that hides
   partitions (`pg_class.relispartition`) from autogenerate.
"""

import os
import sys
from pathlib import Path
from typing import Any

import psycopg
import sqlalchemy as sa
from alembic.autogenerate import produce_migrations
from alembic.operations import ops
from alembic.runtime.migration import MigrationContext

sys.path.insert(0, str(Path(__file__).resolve().parent))

import ext
from registry import XID8
from scenarios import PARTITIONS, internal, r_column, r_table

PG = os.environ.get("SPIKE_PG", "postgresql://platina:platina@localhost:26432")
DB = os.environ.get("SPIKE_DB", "spike0004")
URL = f"{PG}/{DB}"
ENGINE = sa.create_engine(URL.replace("postgresql://", "postgresql+psycopg://"))


def reset() -> None:
    with psycopg.connect(URL, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS public CASCADE")
        conn.execute("CREATE SCHEMA public")


def p1() -> None:
    print("=== P1 (H6): partitioned table, key without the partition column")
    for kind in ("primary key", "unique"):
        reset()
        md = sa.MetaData()
        cols: list[Any] = [
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("xid", XID8(), nullable=False),
            sa.Column("seq", sa.Integer(), nullable=False),
        ]
        key = (
            sa.PrimaryKeyConstraint("xid", "seq")
            if kind == "primary key"
            else sa.UniqueConstraint("xid", "seq")
        )
        sa.Table("outbox", md, *cols, key, postgresql_partition_by="RANGE (created_at)")
        try:
            md.create_all(ENGINE)
            print(f"{kind} (xid, seq): created")
        except sa.exc.DBAPIError as exc:
            print(f"{kind} (xid, seq): {type(exc.orig).__name__}: {str(exc.orig).strip()}")


def _naive(context: MigrationContext, md: sa.MetaData, script: ops.MigrationScript) -> None:
    up = script.upgrade_ops
    assert isinstance(up, ops.UpgradeOps)
    for mto in [o for o in up.ops if isinstance(o, ops.ModifyTableOps)]:
        drops = {o.column_name: o for o in mto.ops if isinstance(o, ops.DropColumnOp)}
        new: list[Any] = []
        for o in mto.ops:
            if isinstance(o, ops.AddColumnOp) and o.column.info.get("renamed_from") in drops:
                old = o.column.info["renamed_from"]
                new.append(
                    ops.AlterColumnOp(
                        mto.table_name,
                        old,
                        modify_name=o.column.name,
                        existing_type=drops[old].to_column().type,
                    )
                )
            elif not (isinstance(o, ops.DropColumnOp) and o.column_name in drops):
                new.append(o)
        mto.ops = new
    creates = {o.table_name: o for o in up.ops if isinstance(o, ops.CreateTableOp)}
    tdrops = {o.table_name: o for o in up.ops if isinstance(o, ops.DropTableOp)}
    for name, create in creates.items():
        old = md.tables[name].info.get("renamed_from")
        if old in tdrops:
            up.ops = [o for o in up.ops if o not in (create, tdrops[old])]
            up.ops.insert(0, ops.RenameTableOp(old, name))


def p2() -> None:
    print("=== P2 (H9): stock operations' reverse() after a naive rename rewrite")
    for label, before, after in (
        ("column rename", r_column(0), r_column(1)),
        ("table rename", r_table(0), r_table(1)),
    ):
        reset()
        before("columns").create_all(ENGINE)
        md = after("columns")
        with ENGINE.connect() as conn:
            ctx = MigrationContext.configure(conn, opts={"target_metadata": md})
            script = produce_migrations(ctx, md)
            _naive(ctx, md, script)
            up = script.upgrade_ops
            assert isinstance(up, ops.UpgradeOps)
            print(
                f"-- {label}: upgrade {[o.to_diff_tuple() if not isinstance(o, (ops.ModifyTableOps, ops.RenameTableOp)) else _show(o) for o in up.ops]}"
            )
            try:
                down = up.reverse()
                print(f"   reverse(): {[_show(o) for o in down.ops]}")
            except NotImplementedError as exc:
                print(f"   reverse(): NotImplementedError {exc!r}")


def _show(o: Any) -> Any:
    if isinstance(o, ops.ModifyTableOps):
        return [_show(x) for x in o.ops]
    if isinstance(o, ops.AlterColumnOp):
        return f"alter_column({o.table_name}.{o.column_name}, new_column_name={o.modify_name})"
    if isinstance(o, ops.RenameTableOp):
        return f"rename_table({o.table_name} -> {o.new_table_name})"
    return type(o).__name__


def p3() -> None:
    print("=== P3 (alternative for item 5): include_name filter hiding partitions")
    reset()
    internal(0)("columns").create_all(ENGINE)
    with psycopg.connect(URL, autocommit=True) as conn:
        for stmt in PARTITIONS:
            conn.execute(stmt)  # type: ignore[arg-type]
        partitions = {
            r[0]
            for r in conn.execute(
                "SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
                "WHERE n.nspname = 'public' AND c.relispartition"
            )
        }

    def include_name(name: str | None, type_: str, parent: dict[str, Any]) -> bool:
        return not (type_ == "table" and name in partitions)

    for step in (0, 1):
        md = internal(step)("columns")
        with ENGINE.connect() as conn:
            ctx = MigrationContext.configure(
                conn,
                opts={
                    "target_metadata": md,
                    "include_name": include_name,
                    "autogenerate_plugins": ext.plugins_for("baseline"),
                },
            )
            script = produce_migrations(ctx, md)
            up = script.upgrade_ops
            assert isinstance(up, ops.UpgradeOps)
            print(f"-- declaration S{step}: {[_tuple(o) for o in up.ops] or 'EMPTY'}")


def _tuple(o: Any) -> Any:
    if isinstance(o, ops.ModifyTableOps):
        return [_tuple(x) for x in o.ops]
    diff = o.to_diff_tuple()
    return (diff[0], getattr(diff[-1], "name", diff[-1]))


if __name__ == "__main__":
    p1()
    p2()
    p3()
    reset()
