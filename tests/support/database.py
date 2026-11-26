"""Real-PostgreSQL helpers for the integration tests (design section 11.5).

Every test gets a database of its own on the shared server (``PLATINA_TEST_DSN``, default the
docker-compose database of ``make db-up``) and creates the tables it needs in it. Nothing here
touches another database: the server is shared with other sessions.

These helpers use plain psycopg connections, never the driver under test, so what they report
(``fetch_plain``) is what a separate client sees: committed data only, read with psycopg's global
adapters.
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any, Final, LiteralString

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

DEFAULT_DSN: Final = "postgresql://platina:platina@localhost:26432/platina"

ITEM_IDS: Final = "SELECT id FROM items ORDER BY id"


def server_dsn() -> str:
    """The maintenance connection string: ``PLATINA_TEST_DSN`` or the docker-compose database."""
    return os.environ.get("PLATINA_TEST_DSN", DEFAULT_DSN)


@contextmanager
def fresh_database(server: str) -> Iterator[str]:
    """Create an empty database with a unique name, yield its conninfo, drop it ``WITH (FORCE)``."""
    dbname = f"platina_test_{uuid.uuid4().hex}"
    name = sql.Identifier(dbname)
    with psycopg.connect(server, autocommit=True) as conn:
        conn.execute(sql.SQL("CREATE DATABASE {}").format(name))
    try:
        yield make_conninfo(server, dbname=dbname)
    finally:
        with psycopg.connect(server, autocommit=True) as conn:
            conn.execute(sql.SQL("DROP DATABASE IF EXISTS {} WITH (FORCE)").format(name))


def execute(dsn: str, *statements: LiteralString) -> None:
    """Run setup statements on a new plain connection, each committed on its own."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        for statement in statements:
            conn.execute(statement)


def fetch_plain(dsn: str, query: LiteralString) -> list[tuple[Any, ...]]:
    """The rows a new plain psycopg connection sees: committed data, global adapters."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        return conn.execute(query).fetchall()


def create_items(dsn: str) -> None:
    """``items (id PK, qty CHECK > 0)`` with the committed row ``(1, 1)``.

    Constraint names: ``items_pkey`` (23505), ``items_qty_check`` (23514).
    """
    execute(
        dsn,
        "CREATE TABLE items (id int PRIMARY KEY, qty int NOT NULL CHECK (qty > 0))",
        "INSERT INTO items (id, qty) VALUES (1, 1)",
    )


def create_allocations(dsn: str) -> None:
    """``items`` (``create_items``) and ``allocations (id PK, item_id FK -> items)``.

    Constraint name: ``allocations_item_id_fkey`` (23503).
    """
    create_items(dsn)
    execute(
        dsn,
        "CREATE TABLE allocations (id int PRIMARY KEY, item_id int NOT NULL REFERENCES items (id))",
    )


def create_deferred_keys(dsn: str) -> None:
    """``keys (id)`` whose unique constraint ``keys_id_key`` is checked only at ``COMMIT``."""
    execute(
        dsn,
        "CREATE TABLE keys (id int, CONSTRAINT keys_id_key UNIQUE (id) "
        "DEFERRABLE INITIALLY DEFERRED)",
    )


def create_days(dsn: str) -> None:
    """``days (d date)``: ``'infinity'`` is a valid date that psycopg cannot load (``DataError``)."""
    execute(dsn, "CREATE TABLE days (d date NOT NULL)")


def create_percent_column(dsn: str) -> None:
    """``odd (id, "a%b")``: a quoted identifier with ``%``, written ``%%`` in compiled SQL."""
    execute(dsn, 'CREATE TABLE odd (id int PRIMARY KEY, "a%b" text)')


def terminate_backend(dsn: str, pid: int) -> None:
    """Terminate backend ``pid`` from a separate connection and wait (up to 5 s) until it exited."""
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT pg_terminate_backend(%s, 5000)", (pid,))
