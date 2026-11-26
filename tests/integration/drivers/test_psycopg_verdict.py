"""One rule for what a pipeline reports (``_common.verdict``, ADR-0012): never misreport a
committed run, whatever fails and wherever - a caller's loader, a caller's dumper, a statement
psycopg cannot run in a pipeline.

The invariant test judges every reply against what a separate connection sees
(``tests.support.invariants``); the others pin the replies of the paths the reviews found.
"""

from unittest.mock import ANY

import pytest

from platina.drivers.interface import Completed, Failed, Lost, StatementResult
from tests.support.database import ITEM_IDS, create_items, fetch_plain
from tests.support.drivers import (
    Unsendable,
    failing_uuid_adapters,
    pipeline_capturing,
    raising_uuid_loader_adapters,
    run_capturing,
    run_in_session,
    session_pid,
    unsendable_dumper_adapters,
)
from tests.support.invariants import UUID, item_committed, uuid_scenario, violated_invariant
from tests.support.statements import (
    BEGIN,
    BEGIN_RESULT,
    COMMIT,
    COMMIT_RESULT,
    DIVIDE_BY_ZERO,
    INSERT_RESULT,
    ROLLBACK,
    ROLLBACK_RESULT,
    SELECT_ONE,
    SQL,
    commit_status,
    fault_of,
    insert_item,
)

UNSENDABLE = SQL("SELECT %s", (Unsendable(),))

# --------------------------------------------------------------------------- invariant


@pytest.mark.parametrize("trailing", [0, 2000], ids=["short", "plus-2000"])
@pytest.mark.parametrize("position", ["only", "before-commit", "after-commit", "last"])
@pytest.mark.parametrize("error", ["ValueError", "DataError"])
@pytest.mark.parametrize("where", ["init", "load"])
def test_pipeline_with_a_failing_loader_never_misreports_the_commit(
    database_dsn, drivers, where, error, position, trailing
):
    # given
    create_items(database_dsn)
    configured = drivers.open(database_dsn, adapters=failing_uuid_adapters(where, error))
    scenario = uuid_scenario(position, trailing)
    # when
    outcome = run_capturing(configured, scenario.statements)
    # then
    assert violated_invariant(outcome, scenario, committed=item_committed(database_dsn)) is None


# --------------------------------------------------------------------------- loader constructor


def test_pipeline_loader_constructor_raising_a_psycopg_error_is_lost(database_dsn, drivers):
    # given: the uuid statement ran, then setting up its result failed with psycopg.DataError;
    # the COMMIT after it ran too - a Failed at 2 would claim it did not
    create_items(database_dsn)
    configured = drivers.open(database_dsn, adapters=failing_uuid_adapters("init", "DataError"))
    # when
    reply = run_in_session(configured, [BEGIN, insert_item(2), UUID, COMMIT])
    # then
    assert (type(reply), commit_status(reply)) == (Lost, None)


def test_pipeline_loader_constructor_raising_a_psycopg_error_keeps_the_commit(
    database_dsn, drivers
):
    # given
    create_items(database_dsn)
    configured = drivers.open(database_dsn, adapters=failing_uuid_adapters("init", "DataError"))
    # when
    run_in_session(configured, [BEGIN, insert_item(2), UUID, COMMIT])
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,), (2,)]


def test_pipeline_lost_after_a_loader_constructor_error_closes_the_connection(
    database_dsn, drivers
):
    # given: the loader's error surfaces while 2000 statements are still being sent
    configured = drivers.open(database_dsn, adapters=raising_uuid_loader_adapters())
    first_pid = session_pid(configured)
    # when
    run_in_session(configured, [UUID, *([SELECT_ONE] * 2000)])
    # then
    assert session_pid(configured) != first_pid


def test_pipeline_after_a_lost_one_in_the_same_session_is_lost(database_dsn, drivers):
    # given
    configured = drivers.open(database_dsn, adapters=raising_uuid_loader_adapters())
    with configured.session() as session:
        session.pipeline([UUID, *([SELECT_ONE] * 2000)])
        # when
        reply = session.pipeline([SELECT_ONE])
    # then
    assert reply == Lost((), ANY)


# --------------------------------------------------------------------------- dumper


def test_pipeline_dumper_error_alone_propagates(database_dsn, drivers):
    # given: a caller's dumper raising is a programming error, raised before its statement ran
    create_items(database_dsn)
    configured = drivers.open(database_dsn, adapters=unsendable_dumper_adapters())
    # when / then
    with pytest.raises(ValueError, match="dumper failed"):
        run_in_session(configured, [BEGIN, insert_item(2), UNSENDABLE, COMMIT])


def test_pipeline_after_a_propagated_dumper_error_the_transaction_is_open(database_dsn, drivers):
    # given: the statements before the dumper's ran; nothing aborted the transaction
    create_items(database_dsn)
    configured = drivers.open(database_dsn, adapters=unsendable_dumper_adapters())
    with configured.session() as session:
        pipeline_capturing(session, [BEGIN, insert_item(2), UNSENDABLE, COMMIT])
        # when
        reply = session.pipeline([SQL(ITEM_IDS), ROLLBACK])
    # then
    assert reply == Completed((StatementResult("SELECT 2", 2, ((1,), (2,))), ROLLBACK_RESULT))


def test_pipeline_server_error_before_a_dumper_error_is_failed_at_the_server_error(
    database_dsn, drivers
):
    # given: 22012 at 2, then the dumper raising ValueError at 3
    create_items(database_dsn)
    configured = drivers.open(database_dsn, adapters=unsendable_dumper_adapters())
    statements = [BEGIN, insert_item(2), DIVIDE_BY_ZERO, UNSENDABLE, COMMIT]
    # when
    reply = run_in_session(configured, statements)
    # then
    assert (reply, fault_of(reply).sqlstate) == (
        Failed((BEGIN_RESULT, INSERT_RESULT), ANY),
        "22012",
    )


def test_pipeline_server_error_before_a_dumper_error_keeps_the_connection(database_dsn, drivers):
    # given: kept, in its aborted transaction - a connection closed as Lost would answer Lost
    create_items(database_dsn)
    configured = drivers.open(database_dsn, adapters=unsendable_dumper_adapters())
    with configured.session() as session:
        session.pipeline([BEGIN, insert_item(2), DIVIDE_BY_ZERO, UNSENDABLE, COMMIT])
        # when
        reply = session.pipeline([SELECT_ONE])
    # then
    assert (type(reply), fault_of(reply).sqlstate) == (Failed, "25P02")


# --------------------------------------------------------------------------- unclean ends


def test_pipeline_comment_only_statement_is_lost_never_completed(driver, database_dsn):
    # given: a statement that yields an empty-query result, which the driver cannot read as a
    # statement result - with psycopg 3.3.9 the 'stopped statement ran' rule reports it
    create_items(database_dsn)
    statements = [BEGIN, insert_item(2), COMMIT, SQL("-- nothing")]
    # when
    reply = run_in_session(driver, statements)
    # then
    assert reply == Lost((BEGIN_RESULT, INSERT_RESULT, COMMIT_RESULT), ANY)


def test_pipeline_copy_after_commit_is_lost_with_the_commit_result(driver, database_dsn):
    # given: COPY cannot run inside a pipeline
    create_items(database_dsn)
    statements = [BEGIN, insert_item(2), COMMIT, SQL("COPY items FROM STDIN")]
    # when
    reply = run_in_session(driver, statements)
    # then
    assert reply == Lost((BEGIN_RESULT, INSERT_RESULT, COMMIT_RESULT), ANY)


def test_pipeline_copy_after_commit_keeps_the_data_committed(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    run_in_session(driver, [BEGIN, insert_item(2), COMMIT, SQL("COPY items FROM STDIN")])
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,), (2,)]


def test_pipeline_copy_before_commit_is_lost_without_a_commit_result(driver, database_dsn):
    # given
    create_items(database_dsn)
    statements = [BEGIN, insert_item(2), SQL("COPY items FROM STDIN"), COMMIT]
    # when
    reply = run_in_session(driver, statements)
    # then
    assert reply == Lost((BEGIN_RESULT, INSERT_RESULT), ANY)


def test_pipeline_copy_before_commit_commits_nothing(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    run_in_session(driver, [BEGIN, insert_item(2), SQL("COPY items FROM STDIN"), COMMIT])
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,)]
