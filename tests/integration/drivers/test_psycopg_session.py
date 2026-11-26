"""``session()`` on real PostgreSQL: release on every path, discard after a lost connection or a
cancellation, per-driver adapters, and ``SessionUnavailable`` (ADR-0012).

The default pool holds one connection, so the next session reuses the connection the previous
one released - or a new one when it was discarded. psycopg_pool cleans up a connection returned
in a transaction itself, with a WARNING; ``pool_warnings`` pins that the driver's release did it
first, so the pool never has to.
"""

import asyncio

import psycopg
import pytest
from psycopg_pool import PoolClosed

from platina.drivers.interface import Completed, SessionUnavailable, StatementResult
from tests.support.cancellation import cancel_driver_open, cancel_pipeline_waiting_on_lock
from tests.support.database import ITEM_IDS, create_items, fetch_plain
from tests.support.drivers import (
    Interrupted,
    backend_pid,
    child_adapters,
    fail_inside_session,
    leave_after_the_backend_died,
    pool_warnings,
    register_upper_text,
    run_in_session,
    session_pid,
    upper_text_adapters,
)
from tests.support.statements import BEGIN, SQL, TERMINATE_OWN_BACKEND, insert_item

UNREACHABLE_DSN = "postgresql://platina:platina@localhost:1/platina"
SELECT_TEXT = SQL("SELECT 'abc'::text")

# --------------------------------------------------------------------------- release


def test_session_left_with_an_open_transaction_rolls_it_back(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    run_in_session(driver, [BEGIN, insert_item(2)])
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,)]


def test_session_after_one_left_with_an_open_transaction_starts_outside_it(driver, database_dsn):
    # given: the uncommitted row 2 would be visible inside the old transaction
    create_items(database_dsn)
    run_in_session(driver, [BEGIN, insert_item(2)])
    # when
    reply = run_in_session(driver, [SQL(ITEM_IDS)])
    # then
    assert reply == Completed((StatementResult("SELECT 1", 1, ((1,),)),))


@pytest.mark.parametrize(
    "statements",
    [
        pytest.param([BEGIN, insert_item(2)], id="open-transaction"),
        pytest.param([BEGIN, insert_item(1)], id="aborted-transaction"),
    ],
)
def test_session_left_in_a_transaction_leaves_the_pool_nothing_to_clean(
    driver, database_dsn, caplog, statements
):
    # given
    create_items(database_dsn)
    # when
    run_in_session(driver, statements)
    # then
    assert pool_warnings(caplog.records) == []


def test_session_left_by_an_exception_leaves_the_pool_nothing_to_clean(
    driver, database_dsn, caplog
):
    # given
    create_items(database_dsn)
    # when
    with pytest.raises(Interrupted):
        fail_inside_session(driver, [BEGIN, insert_item(2)], Interrupted("use case raised"))
    # then
    assert pool_warnings(caplog.records) == []


def test_session_after_an_aborted_transaction_reuses_the_connection(driver, database_dsn):
    # given
    create_items(database_dsn)
    with driver.session() as session:
        aborted_pid = backend_pid(session)
        session.pipeline([BEGIN, insert_item(1)])
    # when
    with driver.session() as session:
        pid = backend_pid(session)
        reply = session.pipeline([BEGIN, insert_item(2)])
    # then
    assert (pid, type(reply)) == (aborted_pid, Completed)


def test_session_left_by_an_exception_reraises_that_exception(driver, database_dsn):
    # given
    create_items(database_dsn)
    error = Interrupted("use case raised")
    # when / then
    with pytest.raises(Interrupted) as raised:
        fail_inside_session(driver, [BEGIN, insert_item(2)], error)
    assert raised.value is error


def test_session_left_by_an_exception_rolls_back(driver, database_dsn):
    # given
    create_items(database_dsn)
    with pytest.raises(Interrupted):
        fail_inside_session(driver, [BEGIN, insert_item(2)], Interrupted("use case raised"))
    # when
    rows = fetch_plain(database_dsn, ITEM_IDS)
    # then
    assert rows == [(1,)]


def test_session_left_by_an_exception_returns_its_connection(database_dsn, drivers):
    # given: one connection at most, a short wait - a connection not given back times out
    driver = drivers.open(database_dsn, max_size=1, timeout=2.0)
    create_items(database_dsn)
    raised_pid = session_pid(driver)
    with pytest.raises(Interrupted):
        fail_inside_session(driver, [BEGIN, insert_item(2)], Interrupted("use case raised"))
    # when
    pid = session_pid(driver)
    # then
    assert pid == raised_pid


def test_session_whose_rollback_fails_on_release_discards_the_connection(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when: leaving runs the release's ROLLBACK on a dead connection - and raises nothing
    terminated_pid = leave_after_the_backend_died(driver, database_dsn, [BEGIN, insert_item(2)])
    # then: the next session works, on a new connection
    assert session_pid(driver) != terminated_pid


def test_session_whose_rollback_fails_on_release_commits_nothing(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    leave_after_the_backend_died(driver, database_dsn, [BEGIN, insert_item(2)])
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,)]


def test_session_reuses_the_released_connection(driver):
    # given
    first_pid = session_pid(driver)
    # when
    pid = session_pid(driver)
    # then
    assert pid == first_pid


# --------------------------------------------------------------------------- discard


def test_session_after_a_lost_connection_gets_a_new_backend(driver):
    # given: leaving the session after Lost raises nothing
    with driver.session() as session:
        lost_pid = backend_pid(session)
        session.pipeline([TERMINATE_OWN_BACKEND])
    # when
    pid = session_pid(driver)
    # then
    assert pid != lost_pid


def test_async_pipeline_cancelled_while_running_raises_cancelled_error(database_dsn):
    # when
    scenario = cancel_pipeline_waiting_on_lock(database_dsn)
    # then
    assert type(scenario.outcome) is asyncio.CancelledError


def test_async_session_after_a_cancelled_pipeline_runs_statements(database_dsn):
    # when
    scenario = cancel_pipeline_waiting_on_lock(database_dsn)
    # then
    assert scenario.next_reply == Completed((StatementResult("SELECT 1", 1, ((1,),)),))


def test_async_session_after_a_cancelled_pipeline_reuses_the_cancelled_connection(database_dsn):
    # when: psycopg cancels the query on the server and drains it, leaving the connection idle
    scenario = cancel_pipeline_waiting_on_lock(database_dsn)
    # then: so the release returns it to the pool rather than discarding it (psycopg 3.3 fact)
    assert scenario.next_pid == scenario.cancelled_pid


def test_async_driver_open_cancelled_while_connecting_raises_cancelled_error():
    # when
    scenario = cancel_driver_open()
    # then
    assert type(scenario.outcome) is asyncio.CancelledError


def test_async_driver_open_cancelled_while_connecting_closes_the_pool():
    # when
    scenario = cancel_driver_open()
    # then: an open pool would make session() wait for its timeout instead
    assert type(scenario.session_error_cause()) is PoolClosed


# --------------------------------------------------------------------------- adapters


def test_session_uses_the_loaders_registered_on_the_driver_adapters(database_dsn, drivers):
    # given
    configured = drivers.open(database_dsn, adapters=upper_text_adapters())
    # when
    reply = run_in_session(configured, [SELECT_TEXT])
    # then
    assert reply == Completed((StatementResult("SELECT 1", 1, (("ABC",),)),))


def test_session_ignores_loaders_registered_after_the_driver_was_built(database_dsn, drivers):
    # given: min_size=0, so the session's connection is made after the registration - a
    # connection copies its map when it connects, so only a map copied at construction hides it
    adapters = child_adapters()
    configured = drivers.open(database_dsn, min_size=0, max_size=1, adapters=adapters)
    register_upper_text(adapters)
    # when
    reply = run_in_session(configured, [SELECT_TEXT])
    # then
    assert reply == Completed((StatementResult("SELECT 1", 1, (("abc",),)),))


def test_session_driver_adapters_leave_the_global_adapters_unchanged(database_dsn, drivers):
    # given
    configured = drivers.open(database_dsn, adapters=upper_text_adapters())
    run_in_session(configured, [SELECT_TEXT])
    # when
    rows = fetch_plain(database_dsn, "SELECT 'abc'::text")
    # then
    assert rows == [("abc",)]


# --------------------------------------------------------------------------- unavailable


def test_driver_opened_on_an_unreachable_server_raises_session_unavailable(drivers):
    # when / then: opening waits for min_size=1 connection, at most the timeout
    with pytest.raises(SessionUnavailable) as raised:
        drivers.open(UNREACHABLE_DSN, timeout=0.5)
    assert isinstance(raised.value.fault.cause, psycopg.Error)


def test_session_on_an_unreachable_server_raises_session_unavailable(drivers):
    # given: no connection at open (min_size=0), a short wait for one
    unreachable = drivers.open(UNREACHABLE_DSN, min_size=0, max_size=1, timeout=0.5)
    # when / then
    with pytest.raises(SessionUnavailable) as raised, unreachable.session():
        pass
    assert isinstance(raised.value.fault.cause, psycopg.Error)
    assert raised.value.fault.sqlstate is None
