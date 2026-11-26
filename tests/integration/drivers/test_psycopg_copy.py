"""``copy_in`` on real PostgreSQL: COPY between a pipelined BEGIN and COMMIT (ADR-0012)."""

from unittest.mock import ANY

from platina.drivers.interface import Completed, DatabaseFault, Failed, Lost, StatementResult
from tests.support.database import (
    ITEM_IDS,
    create_items,
    create_percent_column,
    fetch_plain,
    terminate_backend,
)
from tests.support.drivers import backend_pid
from tests.support.statements import (
    BEGIN,
    COMMIT,
    ROLLBACK,
    ROLLBACK_RESULT,
    SQL,
    TERMINATE_OWN_BACKEND,
    fault_of,
)

COPY_ITEMS = SQL("COPY items (id, qty) FROM STDIN")


def test_copy_in_completes_with_the_copy_result(driver, database_dsn):
    # given
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN])
        # when
        reply = session.copy_in(COPY_ITEMS, [(2, 1), (3, 1), (4, 1)])
    # then
    assert reply == Completed((StatementResult("COPY 3", 3, ()),))


def test_copy_in_rows_are_committed_by_the_following_commit(driver, database_dsn):
    # given
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN])
        session.copy_in(COPY_ITEMS, [(2, 1), (3, 1), (4, 1)])
        # when
        session.pipeline([COMMIT])
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,), (2,), (3,), (4,)]


def test_copy_in_without_rows_completes_with_copy_0(driver, database_dsn):
    # given
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN])
        # when
        reply = session.copy_in(COPY_ITEMS, [])
    # then
    assert reply == Completed((StatementResult("COPY 0", 0, ()),))


def test_copy_in_escaped_percent_in_an_identifier_reaches_the_server_once(driver, database_dsn):
    # given: the column is called a%b; compiled SQL writes a literal % as %%
    create_percent_column(database_dsn)
    with driver.session() as session:
        # when
        reply = session.copy_in(SQL('COPY odd (id, "a%%b") FROM STDIN'), [(1, "x")])
    # then
    assert reply == Completed((StatementResult("COPY 1", 1, ()),))


def test_copy_in_violating_a_unique_key_fails_at_zero(driver, database_dsn):
    # given: id 1 exists
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN])
        # when
        reply = session.copy_in(COPY_ITEMS, [(2, 1), (1, 1)])
    # then
    assert reply == Failed((), ANY)


def test_copy_in_unique_violation_names_the_constraint(driver, database_dsn):
    # given
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN])
        # when
        reply = session.copy_in(COPY_ITEMS, [(2, 1), (1, 1)])
    # then
    assert fault_of(reply) == DatabaseFault("23505", ANY, "items_pkey", "items", "public", ANY)


def test_copy_in_after_a_failed_copy_rollback_completes(driver, database_dsn):
    # given
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN])
        session.copy_in(COPY_ITEMS, [(2, 1), (1, 1)])
        # when
        reply = session.pipeline([ROLLBACK])
    # then
    assert reply == Completed((ROLLBACK_RESULT,))


def test_copy_in_failed_copy_aborts_the_transaction(driver, database_dsn):
    # given
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN])
        session.copy_in(COPY_ITEMS, [(2, 1), (1, 1)])
        # when
        reply = session.pipeline([COMMIT])
    # then
    assert reply == Completed((ROLLBACK_RESULT,))


def test_copy_in_unadaptable_value_fails_at_zero_without_sqlstate(driver, database_dsn):
    # given
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN])
        # when
        reply = session.copy_in(COPY_ITEMS, [(2, object())])
    # then
    assert (reply, fault_of(reply).sqlstate) == (Failed((), ANY), None)


def test_copy_in_after_an_unadaptable_value_rollback_completes(driver, database_dsn):
    # given
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN])
        session.copy_in(COPY_ITEMS, [(2, object())])
        # when
        reply = session.pipeline([ROLLBACK])
    # then
    assert reply == Completed((ROLLBACK_RESULT,))


def test_copy_in_on_a_connection_already_lost_is_lost(driver, database_dsn):
    # given: the pipeline lost the connection, and the driver closed it
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([TERMINATE_OWN_BACKEND])
        # when
        reply = session.copy_in(COPY_ITEMS, [(2, 1)])
    # then
    assert reply == Lost((), ANY)


def test_copy_in_on_a_backend_terminated_from_outside_is_lost(driver, database_dsn):
    # given: the client has not noticed yet - the copy finds out
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN])
        terminate_backend(database_dsn, backend_pid(session))
        # when
        reply = session.copy_in(COPY_ITEMS, [(2, 1)])
    # then
    assert reply == Lost((), ANY)
