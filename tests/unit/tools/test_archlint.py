import pytest

from tests.support.guards import lint_src_module
from tools.guards.archlint import applies_to, module_of

CORE = "src/platina/core/engine/run.py"
SQL = "src/platina/sql/compiler/base.py"
SHELL = "src/platina/runners/async_.py"
DRIVERS = "src/platina/drivers/psycopg/pool.py"
MIGRATE = "src/platina/migrate/metadata.py"


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("import psycopg\n", ["A101"]),
        ("import anyio\n", ["A101"]),
        ("from asyncio import sleep\n", ["A101"]),
        ("import threading\n", ["A101"]),
        ("import time\n", ["A101"]),
        ("import random\n", ["A101"]),
        ("import os\n", ["A101"]),
        ("from importlib import import_module\n", ["A101"]),
        ("from sqlalchemy import MetaData\n", ["A101"]),
        ("import logging\n", ["A101"]),
        ("from pathlib import Path\n", ["A101"]),
        ("import sqlite3\n", ["A101"]),
        ("import sys\n", ["A101"]),
        ("from dataclasses import dataclass\n", []),
        ("from uuid import UUID\n", []),
        ("from graphlib import TopologicalSorter\n", []),
        ("from platina.core.expr import nodes\n", []),
        ("from .commands import Begin\n", []),
    ],
    ids=[
        "driver",
        "anyio",
        "asyncio",
        "threading",
        "time",
        "random",
        "os",
        "importlib",
        "sqlalchemy",
        "logging",
        "pathlib",
        "sqlite3",
        "sys",
        "dataclasses-ok",
        "uuid-type-ok",
        "graphlib-ok",
        "platina-ok",
        "relative-ok",
    ],
)
def test_sans_io_core_imports_are_checked(source, expected):
    # when
    codes = lint_src_module(source, path=CORE)
    # then
    assert codes == expected


def test_sql_package_is_part_of_the_sans_io_core():
    # given
    source = "import psycopg\n"
    # when
    codes = lint_src_module(source, path=SQL)
    # then
    assert codes == ["A101"]


@pytest.mark.parametrize(
    ("source", "path", "expected"),
    [
        ("import psycopg\n", SHELL, ["A102"]),
        ("from psycopg_pool import AsyncConnectionPool\n", SHELL, ["A102"]),
        ("import psycopg\n", DRIVERS, []),
        ("import sqlalchemy\n", SHELL, ["A103"]),
        ("from alembic import command\n", DRIVERS, ["A103"]),
        ("import sqlalchemy\n", MIGRATE, []),
        ("import asyncio\n", SHELL, ["A104"]),
        ("import trio\n", MIGRATE, ["A104"]),
        ("import asyncio\n", DRIVERS, []),
        ("import anyio\n", SHELL, []),
    ],
    ids=[
        "psycopg-in-runner",
        "pool-in-runner",
        "psycopg-in-drivers-ok",
        "sqlalchemy-in-runner",
        "alembic-in-drivers",
        "sqlalchemy-in-migrate-ok",
        "asyncio-in-runner",
        "trio-anywhere",
        "asyncio-in-drivers-ok",
        "anyio-in-runner-ok",
    ],
)
def test_shell_zones_confine_external_libraries(source, path, expected):
    # when
    codes = lint_src_module(source, path=path)
    # then
    assert codes == expected


@pytest.mark.parametrize(
    "source",
    [
        "async def run():\n    pass\n",
        "def run(x):\n    return [y async for y in x]\n",
        "async def run(x):\n    await x\n",
    ],
    ids=["async-def", "async-comprehension", "await"],
)
def test_async_code_in_core_is_reported(source):
    # when
    codes = lint_src_module(source, path=CORE)
    # then
    assert "A105" in codes


def test_async_code_in_shell_is_allowed():
    # given
    source = "async def run(x):\n    await x\n"
    # when
    codes = lint_src_module(source, path=SHELL)
    # then
    assert codes == []


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("from datetime import datetime\nnow = datetime.now()\n", ["A106"]),
        ("import datetime\ntoday = datetime.date.today()\n", ["A106"]),
        ("print('debug')\n", ["A106"]),
        ("data = open('x').read()\n", ["A106"]),
        ("eval('1')\n", ["A106"]),
        ("import datetime as dt\nnow = dt.datetime.now()\n", ["A106"]),
        ("from datetime import datetime as D\nnow = D.now()\n", ["A106"]),
        ("import uuid\nnew_id = uuid.uuid7()\n", ["A106"]),
        ("from uuid import uuid4 as fresh\nnew_id = fresh()\n", ["A106"]),
        ("from datetime import datetime\nwhen = datetime(2026, 11, 24)\n", []),
        ("def f(stage, d):\n    return stage.compile(d)\n", []),
    ],
    ids=[
        "datetime-now",
        "date-today",
        "print",
        "open",
        "eval",
        "module-alias-now",
        "class-alias-now",
        "uuid7",
        "uuid4-alias",
        "datetime-literal-ok",
        "method-ok",
    ],
)
def test_hidden_effects_in_core_are_reported(source, expected):
    # when
    codes = lint_src_module(source, path=CORE)
    # then
    assert codes == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/platina/core/engine/run.py", "platina.core.engine.run"),
        ("src/platina/core/__init__.py", "platina.core"),
        ("src/platina/__init__.py", "platina"),
        ("src/platina/core/snapshot/descriptors.pyi", "platina.core.snapshot.descriptors"),
    ],
)
def test_module_name_is_derived_from_the_path(path, expected):
    # when
    module = module_of(path)
    # then
    assert module == expected


@pytest.mark.parametrize(
    ("path", "expected"),
    [
        ("src/platina/core/plan/load.py", True),
        ("src/platina/py.typed", False),
        ("tests/unit/core/test_plan.py", False),
        ("tools/guards/archlint.py", False),
    ],
)
def test_only_platina_sources_are_checked(path, expected):
    # when
    result = applies_to(path)
    # then
    assert result is expected


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "import uuid\nfrom dataclasses import field\nx = field(default_factory=uuid.uuid7)\n",
            ["A106"],
        ),
        (
            "from datetime import datetime\nfrom dataclasses import field\nx = field(default_factory=datetime.now)\n",
            ["A106"],
        ),
        ("import datetime as dt\nclock = dt.date.today\n", ["A106"]),
        ("import uuid\nmake_id = uuid.uuid4\nnew_id = make_id()\n", ["A106"]),
        ("from uuid import uuid7 as fresh\nfactory = fresh\n", ["A106"]),
        ("import uuid\nnew_id = uuid.uuid7()\n", ["A106"]),
        ("from dataclasses import field\nx = field(default_factory=list)\n", []),
        ("def f(schedule):\n    return schedule.today\n", []),
    ],
    ids=[
        "uuid7-default-factory",
        "datetime-now-default-factory",
        "module-alias-today-reference",
        "uuid4-assigned-then-called",
        "aliased-uuid7-reference",
        "call-reported-once",
        "list-default-factory-ok",
        "unrelated-today-attribute-ok",
    ],
)
def test_clock_and_id_functions_referenced_in_core_are_reported(source, expected):
    # when
    codes = lint_src_module(source, path=CORE)
    # then
    assert codes == expected
