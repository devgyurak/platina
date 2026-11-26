"""Spike 0004 reproduction: an independent driver (database, Alembic calls, catalog, diffs).

Only the subject under test is imported from the spike: `registry.py`, `ext.py`, `alembic_env/`.
"""

import re
import sys
import warnings
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import psycopg
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import produce_migrations
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

SPIKE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SPIKE))

import ext  # noqa: E402
import registry  # noqa: E402

DB = "spike0004_repro"
PG = "postgresql://platina:platina@localhost:26432"
SA_URL = f"postgresql+psycopg://platina:platina@localhost:26432/{DB}"
# Generated migrations are intermediate files: kept out of the tracked tree (ruff would lint them).
VERSIONS = Path(
    "/private/tmp/claude-502/-Users-igyulag-Develop-platina/"
    "f01ff33f-bf83-483a-acc6-1ae975af4036/scratchpad/repro-versions"
)


def create_db() -> None:
    with psycopg.connect(f"{PG}/postgres", autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
        c.execute(f"CREATE DATABASE {DB}")


def drop_db() -> list[str]:
    with psycopg.connect(f"{PG}/postgres", autocommit=True) as c:
        c.execute(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
        return [r[0] for r in c.execute("SELECT datname FROM pg_database ORDER BY 1")]


def sql(stmt: str, schema: str = "public") -> list[tuple[Any, ...]]:
    with psycopg.connect(f"{PG}/{DB}", autocommit=True, options=f"-c search_path={schema}") as c:
        cur = c.execute(stmt)
        return cur.fetchall() if cur.description else []


def reset(schema: str) -> None:
    sql(f"DROP SCHEMA IF EXISTS {schema} CASCADE; CREATE SCHEMA {schema}", "public")


# --------------------------------------------------------------------------- catalog
CATALOG = {
    "table": """SELECT c.relname, c.relkind::text, pg_get_partkeydef(c.oid),
        pg_get_expr(c.relpartbound, c.oid),
        (SELECT p.relname FROM pg_inherits i JOIN pg_class p ON p.oid = i.inhparent
          WHERE i.inhrelid = c.oid)
        FROM pg_class c WHERE c.relnamespace = current_schema()::regnamespace
        AND c.relkind IN ('r', 'p') AND c.relname <> 'alembic_version'""",
    "column": """SELECT c.relname || '.' || a.attname, format_type(a.atttypid, a.atttypmod),
        a.attnotnull, pg_get_expr(d.adbin, d.adrelid)
        FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
        LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
        WHERE c.relnamespace = current_schema()::regnamespace AND c.relkind IN ('r', 'p')
        AND c.relname <> 'alembic_version' AND a.attnum > 0 AND NOT a.attisdropped""",
    "colorder": """SELECT c.relname, string_agg(a.attname, ',' ORDER BY a.attnum)
        FROM pg_attribute a JOIN pg_class c ON c.oid = a.attrelid
        WHERE c.relnamespace = current_schema()::regnamespace AND c.relkind IN ('r', 'p')
        AND c.relname <> 'alembic_version' AND a.attnum > 0 AND NOT a.attisdropped
        GROUP BY c.relname""",
    "constraint": """SELECT c.relname || '.' || con.conname, con.contype::text,
        pg_get_constraintdef(con.oid)
        FROM pg_constraint con JOIN pg_class c ON c.oid = con.conrelid
        WHERE c.relnamespace = current_schema()::regnamespace AND c.relname <> 'alembic_version'""",
    "index": """SELECT i.relname, pg_get_indexdef(i.oid)
        FROM pg_index x JOIN pg_class i ON i.oid = x.indexrelid
        JOIN pg_class c ON c.oid = x.indrelid
        WHERE c.relnamespace = current_schema()::regnamespace AND c.relname <> 'alembic_version'""",
    "trigger": """SELECT c.relname || '.' || t.tgname, pg_get_triggerdef(t.oid)
        FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
        WHERE c.relnamespace = current_schema()::regnamespace AND NOT t.tgisinternal""",
    "function": """SELECT p.proname, p.prosrc FROM pg_proc p
        WHERE p.pronamespace = current_schema()::regnamespace""",
}


def _norm(kind: str, schema: str, row: tuple[Any, ...]) -> tuple[Any, ...]:
    """pg_get_indexdef/pg_get_triggerdef qualify the table with its schema; drop it."""
    if kind not in ("index", "trigger"):
        return row
    return tuple(re.sub(rf" ON (ONLY )?{schema}\.", r" ON \1", str(v)) for v in row)


def snapshot(schema: str) -> dict[str, dict[str, Any]]:
    return {
        kind: {r[0]: _norm(kind, schema, r[1:]) for r in sql(q, schema)}
        for kind, q in CATALOG.items()
    }


def diff(a: dict[str, dict[str, Any]], b: dict[str, dict[str, Any]]) -> list[str]:
    out = []
    for kind in CATALOG:
        for key in sorted(set(a[kind]) | set(b[kind])):
            va, vb = a[kind].get(key), b[kind].get(key)
            if va != vb:
                out.append(f"{kind} {key}: {va!r} != {vb!r}")
    return out


def show(snap: dict[str, dict[str, Any]], kinds: tuple[str, ...]) -> list[str]:
    return [f"{k} {n}: {v}" for k in kinds for n, v in sorted(snap[k].items())]


# --------------------------------------------------------------------------- scenario model
@dataclass
class State:
    label: str
    md: Callable[[str], sa.MetaData]  # naming -> fresh MetaData
    before: list[str] = field(default_factory=list)  # SQL run in public before autogenerate
    outside: list[str] = field(default_factory=list)  # SQL run in public and ref after upgrade
    probe: list[str] = field(default_factory=list)  # SQL whose rows are printed after upgrade
    show: tuple[str, ...] = ("constraint", "index", "trigger", "function", "table")
    dry_only: bool = False  # autogenerate only (no revision, no upgrade)


@dataclass
class Scenario:
    name: str
    states: list[State]
    probe_down: list[str] = field(default_factory=list)


def _cfg(config: str, md: sa.MetaData | None, versions: Path, dry: bool) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(SPIKE / "alembic_env"))
    cfg.set_main_option("version_locations", str(versions))
    cfg.set_main_option("path_separator", "os")
    cfg.attributes.update(
        config=config, url=SA_URL, metadata=md if md is not None else sa.MetaData(), dry_run=dry
    )
    return cfg


def _bodies(path: str) -> str:
    text = Path(path).read_text()
    m = re.search(r"def upgrade\(\) -> None:\n(.*?)\ndef downgrade\(\) -> None:\n(.*)", text, re.S)
    assert m is not None
    strip = "\n".join(
        ln
        for ln in (m.group(1) + "\n--- downgrade:\n" + m.group(2)).splitlines()
        if ln.strip() and '"""' not in ln
    )
    return strip


def dry(config: str, md: sa.MetaData, versions: Path) -> str:
    cfg = _cfg(config, md, versions, dry=True)
    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        command.revision(cfg, autogenerate=True, message="dry")
    for x in w:
        print(f"    [warning] {x.message}")
    return cfg.attributes["rendered"]


def compare_now(config: str, md: sa.MetaData) -> str:
    """Autogenerate without a revision (works when the database is not at head)."""
    engine = sa.create_engine(SA_URL)
    with engine.connect() as conn, warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        ctx = MigrationContext.configure(
            conn,
            opts={
                "compare_type": True,
                "autogenerate_plugins": ext.plugins_for(config),
                "target_metadata": md,
                "alembic_module_prefix": "op.",
                "sqlalchemy_module_prefix": "sa.",
                "user_module_prefix": None,
            },
        )
        script = produce_migrations(ctx, md)
        if config != "stock":
            ext.rewrite_renames(ctx, md, script)
        up = script.upgrade_ops
        assert up is not None
        out = "EMPTY" if up.is_empty() else ext.render_ops(ctx, md, up)
    engine.dispose()
    return out


def make_ref(md: sa.MetaData, outside: list[str]) -> list[str]:
    reset("ref")
    engine = sa.create_engine(SA_URL, connect_args={"options": "-c search_path=ref"})
    try:
        with engine.begin() as conn:
            md.create_all(conn)
            for s in registry.version_ddl(md):
                conn.exec_driver_sql(s.replace("%", "%%"))  # no parameters: escape for psycopg
            for s in outside:
                conn.exec_driver_sql(s)
    except Exception as e:
        return [f"REF CREATE FAILED: {type(e).__name__}: {str(e).splitlines()[0]}"]
    finally:
        engine.dispose()
    return []


def run(sc: Scenario, config: str, naming: str) -> None:
    print(f"\n######## {sc.name} config={config} naming={naming}")
    reset("public")
    versions = VERSIONS / f"{config}-{naming}" / sc.name
    versions.mkdir(parents=True, exist_ok=True)
    for f in versions.glob("*.py"):
        f.unlink()
    pre_snaps: list[dict[str, dict[str, Any]]] = []
    applied: list[State] = []
    outside_all: list[str] = []
    for st in sc.states:
        print(f"\n=== state {st.label}")
        for s in st.before:
            print(f"  before: {s} -> {sql(s)}")
        if st.dry_only:
            print("  autogenerate (dry only):")
            print("    " + dry(config, st.md(naming), versions).replace("\n", "\n    "))
            continue
        pre = snapshot("public")
        cfg = _cfg(config, st.md(naming), versions, dry=False)
        with warnings.catch_warnings(record=True) as w:
            warnings.simplefilter("always")
            script = command.revision(cfg, autogenerate=True, message=st.label)
        for x in w:
            print(f"    [warning] {x.message}")
        assert script is not None
        assert not isinstance(script, list)
        print("  generated (upgrade / downgrade):")
        print("    " + _bodies(script.path).replace("\n", "\n    "))
        try:
            command.upgrade(_cfg(config, None, versions, dry=False), "head")
        except Exception as e:
            print(f"  UPGRADE FAILED: {type(e).__name__}: {str(e).splitlines()[0]}")
            Path(script.path).unlink()
            continue
        pre_snaps.append(pre)
        applied.append(st)
        print("  second autogenerate: " + dry(config, st.md(naming), versions))
        for s in st.outside:
            print(f"  outside migrations: {s}")
            sql(s)
            outside_all.append(s)
        if st.outside:
            print("  autogenerate after outside DDL: " + dry(config, st.md(naming), versions))
        snap = snapshot("public")
        print("  catalog:")
        for line in show(snap, st.show):
            print("    " + line)
        err = make_ref(st.md(naming), outside_all)
        d = err or diff(snap, snapshot("ref"))
        print("  vs direct create in ref: " + ("MATCH" if not d else "DIFFER"))
        for line in d:
            print("    " + line)
        for s in st.probe:
            try:
                print(f"  probe: {s} -> {sql(s)}")
            except psycopg.Error as e:
                print(f"  probe: {s} -> {type(e).__name__}: {str(e).splitlines()[0]}")
    print("\n=== downgrades")
    for i in range(len(applied) - 1, -1, -1):
        try:
            command.downgrade(_cfg(config, None, versions, dry=False), "-1")
        except Exception as e:
            msg = str(e).splitlines()[0]
            print(f"  downgrade {applied[i].label}: DOWNGRADE FAILED: {type(e).__name__}: {msg}")
            break
        d = diff(snapshot("public"), pre_snaps[i])
        label = applied[i].label
        print(
            f"  downgrade {label}: catalog vs before its upgrade: "
            + ("MATCH" if not d else "DIFFER")
        )
        for line in d:
            print("    " + line)
        older = applied[i - 1].md(naming) if i > 0 else sa.MetaData()
        print("    autogenerate vs older declaration: " + compare_now(config, older))
        for s in sc.probe_down:
            try:
                print(f"    probe: {s} -> {sql(s)}")
            except psycopg.Error as e:
                print(f"    probe: {s} -> {type(e).__name__}: {str(e).splitlines()[0]}")
