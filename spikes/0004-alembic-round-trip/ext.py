"""Spike 0004: Alembic extension - `version` trigger operations and comparator, rename rewrite.

Only Alembic's own extension points are used: `Operations.register_operation` /
`implementation_for`, `renderers.dispatch_for`, a comparator `Plugin` (Alembic 1.18+) and
`process_revision_directives`.
"""

from typing import Any

import sqlalchemy as sa
from alembic.autogenerate import produce_migrations, renderers
from alembic.autogenerate.api import AutogenContext
from alembic.operations import MigrateOperation, Operations, ops
from alembic.runtime.migration import MigrationContext
from alembic.runtime.plugins import Plugin
from alembic.util import DispatchPriority, PriorityDispatchResult

FUNCTION = "platina_bump_version"


# --------------------------------------------------------------------------- operations
@Operations.register_operation("create_version_function")
class CreateVersionFunctionOp(MigrateOperation):
    def __init__(self, body: str) -> None:
        self.body = body

    @classmethod
    def create_version_function(cls, operations: Operations, body: str) -> Any:
        return operations.invoke(cls(body))

    def reverse(self) -> MigrateOperation:
        return DropVersionFunctionOp(self.body)


@Operations.register_operation("drop_version_function")
class DropVersionFunctionOp(MigrateOperation):
    def __init__(self, body: str) -> None:
        self.body = body  # kept for the reverse operation

    @classmethod
    def drop_version_function(cls, operations: Operations, body: str) -> Any:
        return operations.invoke(cls(body))

    def reverse(self) -> MigrateOperation:
        return CreateVersionFunctionOp(self.body)


@Operations.register_operation("replace_version_function")
class ReplaceVersionFunctionOp(MigrateOperation):
    def __init__(self, body: str, old_body: str) -> None:
        self.body, self.old_body = body, old_body

    @classmethod
    def replace_version_function(cls, operations: Operations, body: str, old_body: str) -> Any:
        return operations.invoke(cls(body, old_body))

    def reverse(self) -> MigrateOperation:
        return ReplaceVersionFunctionOp(self.old_body, self.body)


@Operations.register_operation("create_version_trigger")
class CreateVersionTriggerOp(MigrateOperation):
    def __init__(self, table: str, trigger: str) -> None:
        self.table, self.trigger = table, trigger

    @classmethod
    def create_version_trigger(cls, operations: Operations, table: str, trigger: str) -> Any:
        return operations.invoke(cls(table, trigger))

    def reverse(self) -> MigrateOperation:
        return DropVersionTriggerOp(self.table, self.trigger)


@Operations.register_operation("drop_version_trigger")
class DropVersionTriggerOp(MigrateOperation):
    def __init__(self, table: str, trigger: str) -> None:
        self.table, self.trigger = table, trigger

    @classmethod
    def drop_version_trigger(cls, operations: Operations, table: str, trigger: str) -> Any:
        return operations.invoke(cls(table, trigger))

    def reverse(self) -> MigrateOperation:
        return CreateVersionTriggerOp(self.table, self.trigger)


def _function_sql(body: str, *, replace: bool) -> str:
    verb = "CREATE OR REPLACE" if replace else "CREATE"
    return (
        f"{verb} FUNCTION {FUNCTION}() RETURNS trigger LANGUAGE plpgsql AS $platina${body}$platina$"
    )


@Operations.implementation_for(CreateVersionFunctionOp)
def _create_function(operations: Operations, op: CreateVersionFunctionOp) -> None:
    operations.execute(_function_sql(op.body, replace=False))


@Operations.implementation_for(ReplaceVersionFunctionOp)
def _replace_function(operations: Operations, op: ReplaceVersionFunctionOp) -> None:
    operations.execute(_function_sql(op.body, replace=True))


@Operations.implementation_for(DropVersionFunctionOp)
def _drop_function(operations: Operations, op: DropVersionFunctionOp) -> None:
    operations.execute(f"DROP FUNCTION {FUNCTION}()")


@Operations.implementation_for(CreateVersionTriggerOp)
def _create_trigger(operations: Operations, op: CreateVersionTriggerOp) -> None:
    operations.execute(
        f"CREATE TRIGGER {op.trigger} BEFORE UPDATE ON {op.table} "
        f"FOR EACH ROW EXECUTE FUNCTION {FUNCTION}()"
    )


@Operations.implementation_for(DropVersionTriggerOp)
def _drop_trigger(operations: Operations, op: DropVersionTriggerOp) -> None:
    operations.execute(f"DROP TRIGGER {op.trigger} ON {op.table}")


@renderers.dispatch_for(CreateVersionFunctionOp)
def _render_create_function(ctx: AutogenContext, op: CreateVersionFunctionOp) -> str:
    return f"op.create_version_function(body={op.body!r})"


@renderers.dispatch_for(DropVersionFunctionOp)
def _render_drop_function(ctx: AutogenContext, op: DropVersionFunctionOp) -> str:
    return f"op.drop_version_function(body={op.body!r})"


@renderers.dispatch_for(ReplaceVersionFunctionOp)
def _render_replace_function(ctx: AutogenContext, op: ReplaceVersionFunctionOp) -> str:
    return f"op.replace_version_function(body={op.body!r}, old_body={op.old_body!r})"


@renderers.dispatch_for(CreateVersionTriggerOp)
def _render_create_trigger(ctx: AutogenContext, op: CreateVersionTriggerOp) -> str:
    return f"op.create_version_trigger({op.table!r}, {op.trigger!r})"


@renderers.dispatch_for(DropVersionTriggerOp)
def _render_drop_trigger(ctx: AutogenContext, op: DropVersionTriggerOp) -> str:
    return f"op.drop_version_trigger({op.table!r}, {op.trigger!r})"


# --------------------------------------------------------------------------- comparator plugin
def _db_state(ctx: AutogenContext) -> tuple[str | None, dict[str, str]]:
    conn = ctx.connection
    assert conn is not None
    body = conn.execute(
        sa.text(
            "SELECT p.prosrc FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
            "WHERE n.nspname = current_schema() AND p.proname = :f"
        ),
        {"f": FUNCTION},
    ).scalar()
    rows = conn.execute(
        sa.text(
            "SELECT c.relname, t.tgname FROM pg_trigger t "
            "JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = current_schema() AND NOT t.tgisinternal "
            "AND t.tgname LIKE 'platina_version_%'"
        )
    ).all()
    return body, {r[0]: r[1] for r in rows}


def _desired(ctx: AutogenContext) -> tuple[str | None, dict[str, str]]:
    md = ctx.metadata
    assert isinstance(md, sa.MetaData)
    return md.info.get("platina_version_body"), dict(md.info.get("platina_version_triggers", {}))


def _compare_drops(
    ctx: AutogenContext, upgrade_ops: ops.UpgradeOps, schemas: set[str | None]
) -> PriorityDispatchResult:
    """FIRST: drops and replacements run before table and column operations."""
    db_body, db_triggers = _db_state(ctx)
    want_body, want_triggers = _desired(ctx)
    for table, trigger in sorted(db_triggers.items()):
        if want_triggers.get(table) != trigger:
            upgrade_ops.ops.append(DropVersionTriggerOp(table, trigger))
    if db_body is not None and want_body is None:
        upgrade_ops.ops.append(DropVersionFunctionOp(db_body))
    elif db_body is not None and want_body is not None and db_body != want_body:
        upgrade_ops.ops.append(ReplaceVersionFunctionOp(want_body, db_body))
    return PriorityDispatchResult.CONTINUE


def _compare_creates(
    ctx: AutogenContext, upgrade_ops: ops.UpgradeOps, schemas: set[str | None]
) -> PriorityDispatchResult:
    """LAST: creations run after the tables exist."""
    db_body, db_triggers = _db_state(ctx)
    want_body, want_triggers = _desired(ctx)
    if want_body is not None and db_body is None:
        upgrade_ops.ops.append(CreateVersionFunctionOp(want_body))
    for table, trigger in sorted(want_triggers.items()):
        if db_triggers.get(table) != trigger:
            upgrade_ops.ops.append(CreateVersionTriggerOp(table, trigger))
    return PriorityDispatchResult.CONTINUE


def setup(plugin: Plugin) -> None:
    plugin.add_autogenerate_comparator(_compare_drops, "schema", priority=DispatchPriority.FIRST)
    plugin.add_autogenerate_comparator(_compare_creates, "schema", priority=DispatchPriority.LAST)


PLUGIN_NAME = "platina.version_trigger"
Plugin.setup_plugin_from_module(__import__(__name__), PLUGIN_NAME)


# --------------------------------------------------------------------------- rename rewrite
class RenameColumnOp(ops.AlterColumnOp):
    """`AlterColumnOp` whose reverse swaps the names (the stock reverse drops `modify_name`)."""

    def reverse(self) -> RenameColumnOp:
        assert self.modify_name is not None
        kw: dict[str, Any] = {
            "schema": self.schema,
            "existing_nullable": self.existing_nullable,
            "modify_name": self.column_name,
        }
        if self.modify_type is not None:
            kw["existing_type"] = self.modify_type
            kw["modify_type"] = self.existing_type
        else:
            kw["existing_type"] = self.existing_type
        return RenameColumnOp(self.table_name, self.modify_name, **kw)


class RenameTableOp(ops.RenameTableOp):
    """`RenameTableOp` with a reverse (the stock one has none)."""

    def reverse(self) -> RenameTableOp:
        return RenameTableOp(self.new_table_name, self.table_name, schema=self.schema)


@renderers.dispatch_for(RenameTableOp)
def _render_rename_table(ctx: AutogenContext, op: RenameTableOp) -> str:
    # Alembic has no renderer for RenameTableOp: autogenerate never emits one.
    return f"op.rename_table({op.table_name!r}, {op.new_table_name!r})"


def _reverse_modify(mto: ops.ModifyTableOps) -> ops.ModifyTableOps:
    """Reverse with column renames first (the stock reverse puts them last, after constraint
    operations that refer to the old column names)."""
    renames = [op for op in mto.ops if isinstance(op, RenameColumnOp)]
    others = [op for op in mto.ops if not isinstance(op, RenameColumnOp)]
    return ops.ModifyTableOps(
        mto.table_name,
        [*(op.reverse() for op in reversed(renames)), *(op.reverse() for op in reversed(others))],
        schema=mto.schema,
    )


def _reverse(op: Any) -> Any:
    return _reverse_modify(op) if isinstance(op, ops.ModifyTableOps) else op.reverse()


def render_item(type_: str, obj: Any, ctx: AutogenContext) -> Any:
    """Import the module of the spike's user-defined types (Alembic renders `registry.XID8()`
    but adds no import for it)."""
    if type_ == "type" and type(obj).__module__ == "registry":
        ctx.imports.add("import registry")
    return False


def _type_sql(t: Any, dialect: Any) -> str:
    return str(t.compile(dialect=dialect))


def _rewrite_columns(mto: ops.ModifyTableOps, dialect: Any, log: list[str]) -> None:
    drops = {op.column_name: op for op in mto.ops if isinstance(op, ops.DropColumnOp)}
    new_ops: list[Any] = []
    consumed: set[str] = set()
    for op in mto.ops:
        if isinstance(op, ops.AddColumnOp):
            old = op.column.info.get("renamed_from")
            if old and old in drops:
                old_col = drops[old].to_column()
                kw: dict[str, Any] = {
                    "schema": mto.schema,
                    "existing_type": old_col.type,
                    "existing_nullable": old_col.nullable,
                    "modify_name": op.column.name,
                }
                if _type_sql(old_col.type, dialect) != _type_sql(op.column.type, dialect):
                    kw["modify_type"] = op.column.type
                new_ops.append(RenameColumnOp(mto.table_name, old, **kw))
                consumed.add(old)
                log.append(f"column rename {mto.table_name}.{old} -> {op.column.name}")
                continue
        new_ops.append(op)
    kept = [
        op
        for op in new_ops
        if not (isinstance(op, ops.DropColumnOp) and op.column_name in consumed)
    ]
    # Renames first: later operations (indexes, constraints) refer to the new names.
    mto.ops = [
        *(op for op in kept if isinstance(op, RenameColumnOp)),
        *(op for op in kept if not isinstance(op, RenameColumnOp)),
    ]


def rewrite_renames(
    context: MigrationContext, md: sa.MetaData, script: ops.MigrationScript
) -> list[str]:
    """Turn drop+add into renames where the metadata carries a `renamed_from` hint.

    Builds the downgrade itself: Alembic's `AlterColumnOp.reverse()` loses `modify_name` and
    `RenameTableOp` has no `reverse()` (hypothesis H9, probed in `probes.py`).
    """
    log: list[str] = []
    upgrade = script.upgrade_ops
    assert isinstance(upgrade, ops.UpgradeOps)
    dialect = context.dialect
    creates = {op.table_name: op for op in upgrade.ops if isinstance(op, ops.CreateTableOp)}
    drops = {op.table_name: op for op in upgrade.ops if isinstance(op, ops.DropTableOp)}
    head: list[Any] = []  # [modify old table..., rename old -> new] per renamed table
    head_down: list[Any] = []
    removed: set[int] = set()
    for new_name, create in creates.items():
        table = md.tables[new_name]
        old = table.info.get("renamed_from")
        if not old or old not in drops:
            continue
        # Second pass: compare the database's old table with the declared table under the old
        # name, so column, index and constraint differences come out against the old name.
        md_old = sa.MetaData(naming_convention=md.naming_convention, info=dict(md.info))
        # All declared tables are copied (so foreign keys resolve) plus the renamed table once
        # more under its old name; only the old name's operations are taken.
        for t in md.tables.values():
            t.to_metadata(md_old)
        table.to_metadata(md_old, name=old)
        second = produce_migrations(context, md_old)
        modify = [
            op
            for op in second.upgrade_ops.ops  # type: ignore[union-attr]
            if isinstance(op, ops.ModifyTableOps) and op.table_name == old
        ]
        for mto in modify:
            _rewrite_columns(mto, dialect, log)
        rename = RenameTableOp(old, new_name)
        head.extend([*modify, rename])
        head_down.extend([rename.reverse(), *(_reverse_modify(m) for m in reversed(modify))])
        removed.update({id(create), id(drops[old])})
        log.append(f"table rename {old} -> {new_name} (+{sum(len(m.ops) for m in modify)} ops)")
    rest = [op for op in upgrade.ops if id(op) not in removed]
    for op in rest:
        if isinstance(op, ops.ModifyTableOps):
            _rewrite_columns(op, dialect, log)
    upgrade.ops = [*head, *rest]
    downgrade = script.downgrade_ops
    assert isinstance(downgrade, ops.DowngradeOps)
    # Renames first in both directions: a foreign key follows the table by OID, so other
    # tables' constraint operations can then refer to the name that exists at that point.
    downgrade.ops = [*head_down, *reversed([_reverse(op) for op in rest])]
    return log


# --------------------------------------------------------------------------- env.py hook
def render_ops(context: MigrationContext, md: sa.MetaData, up: ops.UpgradeOps) -> str:
    """Render operations as `alembic revision` would (harness only; uses Alembic internals)."""
    from alembic.autogenerate import render

    ctx = AutogenContext(context, metadata=md, opts=dict(context.opts))
    return render._indent(render._render_cmd_body(up, ctx))


def plugins_for(config: str) -> list[str]:
    plugins = ["alembic.autogenerate.*"]
    if config != "stock":
        plugins.append(PLUGIN_NAME)
    if config == "ckplugin":
        plugins.append("alembic.ext.checkconstraint_byname")
    return plugins


def directives_hook(attributes: dict[str, Any]) -> Any:
    def process_revision_directives(
        context: MigrationContext, revision: Any, directives: list[ops.MigrationScript]
    ) -> None:
        script = directives[0]
        md = attributes["metadata"]
        if attributes.get("rename_rewrite", True):
            attributes.setdefault("rewrite_log", []).extend(rewrite_renames(context, md, script))
        upgrade = script.upgrade_ops
        assert isinstance(upgrade, ops.UpgradeOps)
        attributes["empty"] = upgrade.is_empty()
        if attributes.get("dry_run"):
            attributes["rendered"] = (
                "EMPTY" if upgrade.is_empty() else render_ops(context, md, upgrade)
            )
            directives[:] = []

    return process_revision_directives
