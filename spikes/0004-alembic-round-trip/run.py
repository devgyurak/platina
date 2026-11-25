"""Spike 0004 driver.

    uv run python spikes/0004-alembic-round-trip/run.py setup
    uv run python spikes/0004-alembic-round-trip/run.py all            # every config x scenario
    uv run python spikes/0004-alembic-round-trip/run.py <config> <scenario> [<naming>]
    uv run python spikes/0004-alembic-round-trip/run.py teardown

Environment: SPIKE_DB (default spike0004), SPIKE_PG (default
postgresql://platina:platina@localhost:26432). Output: stdout and results/<config>-<naming>/.
"""

import os
import re
import shutil
import sys
import traceback
from pathlib import Path
from typing import Any

import psycopg
import sqlalchemy as sa
from alembic import command
from alembic.autogenerate import produce_migrations
from alembic.config import Config
from alembic.runtime.migration import MigrationContext

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import catalog  # noqa: E402
import ext  # noqa: E402
from registry import version_ddl  # noqa: E402
from scenarios import SCENARIOS, Scenario  # noqa: E402

PG = os.environ.get("SPIKE_PG", "postgresql://platina:platina@localhost:26432")
DB = os.environ.get("SPIKE_DB", "spike0004")
if DB in ("platina", "postgres"):
    raise SystemExit("refusing to run in the shared database")
URL = f"{PG}/{DB}"
SA_URL = URL.replace("postgresql://", "postgresql+psycopg://")
RESULTS = HERE / "results"
CONFIGS = ("stock", "baseline", "ckplugin")


def admin(sql: str) -> None:
    with psycopg.connect(f"{PG}/postgres", autocommit=True) as conn:
        conn.execute(sql)  # type: ignore[arg-type]


def reset(conn: psycopg.Connection[Any], schema: str) -> None:
    conn.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")
    conn.execute(f"CREATE SCHEMA {schema}")


def build_reference(md: sa.MetaData, after: list[str]) -> catalog.Snapshot:
    """The intended state, created directly (create_all + the registry's trigger DDL) in `ref`."""
    engine = sa.create_engine(SA_URL)
    with engine.begin() as conn:
        conn.exec_driver_sql("DROP SCHEMA IF EXISTS ref CASCADE")
        conn.exec_driver_sql("CREATE SCHEMA ref")
        conn.exec_driver_sql("SET search_path TO ref")
        md.create_all(conn)
    engine.dispose()
    with psycopg.connect(URL, autocommit=True) as pconn:
        pconn.execute("SET search_path TO ref")
        for stmt in [*version_ddl(md), *after]:
            pconn.execute(stmt)  # type: ignore[arg-type]
        return catalog.snapshot(pconn, "ref")


def alembic_config(config: str, versions: Path, md: sa.MetaData, dry_run: bool) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(HERE / "alembic_env"))
    cfg.set_main_option("version_locations", str(versions))
    cfg.set_main_option("path_separator", "os")
    cfg.attributes.update({"config": config, "url": SA_URL, "metadata": md, "dry_run": dry_run})
    return cfg


def bodies(path: Path) -> str:
    text = path.read_text()
    m = re.search(
        r"def upgrade\(\) -> None:\n(.*?)\n\ndef downgrade\(\) -> None:\n(.*)", text, re.S
    )
    assert m, text
    return f"  upgrade():\n{m.group(1)}\n  downgrade():\n{m.group(2).rstrip()}"


def dry_run(config: str, versions: Path, md: sa.MetaData, head: str = "head") -> str:
    cfg = alembic_config(config, versions, md, dry_run=True)
    command.revision(cfg, message="dry", autogenerate=True, rev_id="dry", head=head)
    log = cfg.attributes.get("rewrite_log", [])
    rendered = cfg.attributes["rendered"]
    return (f"  (rewrite: {log})\n" if log else "") + "  " + rendered.replace("\n", "\n  ")


def compare_now(config: str, md: sa.MetaData) -> str:
    """Autogenerate against a database that is not at head (after a downgrade): Alembic's
    `revision` refuses that, so the same comparison runs through `produce_migrations`."""
    engine = sa.create_engine(SA_URL)
    with engine.connect() as conn:
        ctx = MigrationContext.configure(
            conn,
            opts={
                "target_metadata": md,
                "autogenerate_plugins": ext.plugins_for(config),
                "compare_type": True,
                "render_item": ext.render_item,
            },
        )
        script = produce_migrations(ctx, md)
        log = ext.rewrite_renames(ctx, md, script) if config != "stock" else []
        up = script.upgrade_ops
        assert up is not None
        text = "EMPTY" if up.is_empty() else ext.render_ops(ctx, md, up)
    engine.dispose()
    return (f"  (rewrite: {log})\n" if log else "") + "  " + text.replace("\n", "\n  ")


def run_scenario(config: str, sc: Scenario, naming: str, out: list[str]) -> list[dict[str, Any]]:
    def say(line: str = "") -> None:
        out.append(line)
        print(line, flush=True)

    summary: list[dict[str, Any]] = []
    versions = RESULTS / f"{config}-{naming}" / sc.name / "versions"
    shutil.rmtree(versions, ignore_errors=True)
    versions.mkdir(parents=True)
    with psycopg.connect(URL, autocommit=True) as conn:
        reset(conn, "public")
        reset(conn, "ref")
    say(f"=== {config} / naming={naming} / {sc.name}: {sc.item}")
    snaps: list[catalog.Snapshot] = []
    world: list[str] = []  # DDL run outside migrations; it persists, so the reference keeps it
    applied: list[int] = []
    for i, st in enumerate(sc.states):
        row: dict[str, Any] = {"state": st.label}
        # A fresh MetaData for every Alembic call, as one CLI process per command would have:
        # Alembic's check-constraint operations re-attach copies to the declared table.
        md = st.build(naming)
        say(f"--- {st.label}")
        if st.dry_only:
            say("autogenerate (dry run, not applied):")
            say(dry_run(config, versions, md))
            row.update(detected=None, second="(dry only)")
            summary.append(row)
            continue
        cfg = alembic_config(config, versions, md, dry_run=False)
        try:
            command.revision(cfg, message=st.label, autogenerate=True, rev_id=f"{i:02d}")
        except Exception as exc:
            say(f"REVISION FAILED: {exc!r}")
            row.update(error=f"revision: {exc}")
            summary.append(row)
            break
        log = cfg.attributes.get("rewrite_log", [])
        row["detected"] = not cfg.attributes["empty"]
        say(
            f"revision {i:02d} ({'operations' if row['detected'] else 'EMPTY'}){' rewrite: ' + str(log) if log else ''}"
        )
        say(bodies(next(versions.glob(f"{i:02d}_*.py"))))
        try:
            command.upgrade(cfg, "head")
        except Exception as exc:
            say(f"UPGRADE FAILED: {''.join(traceback.format_exception_only(exc)).strip()}")
            row.update(error=f"upgrade: {exc}")
            summary.append(row)
            break
        applied.append(i)
        with psycopg.connect(URL, autocommit=True) as conn:
            for stmt in st.after:
                conn.execute(stmt)  # type: ignore[arg-type]
        if st.world:
            pre = dry_run(config, versions, st.build(naming))
            row["second_pre"] = "EMPTY" if pre.strip() == "EMPTY" else "OPS"
            say("second autogenerate, before the statements run outside migrations:")
            say(pre)
            say("statements outside migrations: " + "; ".join(st.world))
            with psycopg.connect(URL, autocommit=True) as conn:
                for stmt in st.world:
                    conn.execute(stmt)  # type: ignore[arg-type]
            world.extend(st.world)
        second = dry_run(config, versions, st.build(naming))
        row["second"] = "EMPTY" if second.strip() == "EMPTY" else "OPS"
        say("second autogenerate:")
        say(second)
        with psycopg.connect(URL, autocommit=True) as conn:
            snap = catalog.snapshot(conn, "public")
            for sql in st.probe:
                say(f"probe {sql}: {conn.execute(sql).fetchall()}")  # type: ignore[arg-type]
        snaps.append(snap)
        ref = build_reference(st.build(naming), world)
        d = catalog.diff(snap, ref)
        row["ref"] = "MATCH" if not d else f"{len(d)} diffs"
        say("catalog (public):")
        say(catalog.render(snap))
        say("catalog vs reference (direct creation): " + ("MATCH" if not d else "DIFFERENT"))
        for line in d:
            say(line)
        summary.append(row)
    # downgrade one revision at a time
    for pos in range(len(applied) - 1, -1, -1):
        i = applied[pos]
        target = summary[i]
        cfg = alembic_config(config, versions, sc.states[i].build(naming), dry_run=False)
        say(f"--- downgrade -1 (undo {sc.states[i].label})")
        try:
            command.downgrade(cfg, "-1")
        except Exception as exc:
            say(f"DOWNGRADE FAILED: {''.join(traceback.format_exception_only(exc)).strip()}")
            target["down"] = "FAILED"
            break
        with psycopg.connect(URL, autocommit=True) as conn:
            snap = catalog.snapshot(conn, "public")
        if pos == 0:
            expected: catalog.Snapshot = {k: [] for k in catalog.QUERIES}
            label = "empty schema"
        else:
            expected = snaps[pos - 1]
            label = f"snapshot after {sc.states[applied[pos - 1]].label}"
        d = catalog.diff(snap, expected)
        target["down"] = "MATCH" if not d else f"{len(d)} diffs"
        say(f"catalog vs {label}: " + ("MATCH" if not d else "DIFFERENT"))
        for line in d:
            say(line)
        if pos > 0:
            prev = sc.states[applied[pos - 1]].build(naming)
            say("autogenerate against the previous declaration:")
            say(compare_now(config, prev))
    return summary


def run(config: str, sc: Scenario, naming: str) -> list[dict[str, Any]]:
    out: list[str] = []
    try:
        return run_scenario(config, sc, naming, out)
    finally:
        target = RESULTS / f"{config}-{naming}" / f"{sc.name}.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("\n".join(out) + "\n")


def main(argv: list[str]) -> None:
    if argv[:1] == ["setup"]:
        admin(f"CREATE DATABASE {DB}")
        return
    if argv[:1] == ["teardown"]:
        admin(f"DROP DATABASE IF EXISTS {DB} WITH (FORCE)")
        return
    jobs: list[tuple[str, Scenario, str]] = []
    if argv[:1] == ["all"]:
        for config in CONFIGS:
            for sc in SCENARIOS:
                namings = sc.namings if config != "stock" else ("columns",)
                jobs.extend((config, sc, n) for n in namings)
    else:
        by_name = {s.name: s for s in SCENARIOS}
        naming = argv[2] if len(argv) > 2 else "columns"
        jobs.append((argv[0], by_name[argv[1]], naming))
    table: list[str] = []
    for config, sc, naming in jobs:
        for row in run(config, sc, naming):
            table.append(
                f"| {config} | {naming} | {sc.name} | {row['state']} | {row.get('detected')} | "
                f"{row.get('second_pre', '')}{' / ' if 'second_pre' in row else ''}{row.get('second')} | {row.get('ref')} | {row.get('down')} | {row.get('error', '')} |"
            )
    header = (
        "| config | naming | scenario | state | revision has ops | second autogenerate | "
        "catalog vs reference | downgrade restores | error |\n|---|---|---|---|---|---|---|---|---|"
    )
    print("\n" + header + "\n" + "\n".join(table))
    (RESULTS / "summary.md").write_text(header + "\n" + "\n".join(table) + "\n")


if __name__ == "__main__":
    main(sys.argv[1:])
