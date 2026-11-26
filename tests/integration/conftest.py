"""Integration fixtures: a database per test on the shared PostgreSQL server, the drivers.

Every test under ``tests/integration`` is marked ``integration``. The template database and
xdist (design section 11.5) come with #20; until then each test starts from an empty database.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from platina.drivers.interface import SessionSource
from tests.support.database import fresh_database, server_dsn
from tests.support.drivers import Drivers, Variant, open_drivers

_HERE = Path(__file__).parent


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    for item in items:
        if _HERE in item.path.parents:
            item.add_marker(pytest.mark.integration)


@pytest.fixture
def database_dsn() -> Iterator[str]:
    """The conninfo of a fresh, empty database of this test's own; dropped afterwards."""
    with fresh_database(server_dsn()) as dsn:
        yield dsn


@pytest.fixture(params=["sync", "async"])
def drivers(request: pytest.FixtureRequest, database_dsn: str) -> Iterator[Drivers]:
    """Opens drivers of one variant (each test runs with both); all closed when the test ends.

    It depends on ``database_dsn`` so that pytest tears it down first: every driver is closed
    before the test's database is dropped, whatever order a test lists its fixtures in.
    """
    variant: Variant = request.param
    with open_drivers(variant) as opened:
        yield opened


@pytest.fixture
def driver(database_dsn: str, drivers: Drivers) -> SessionSource:
    """A driver on this test's database, default pool settings (one connection)."""
    return drivers.open(database_dsn)
