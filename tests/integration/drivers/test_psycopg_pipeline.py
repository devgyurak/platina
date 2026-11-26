"""``pipeline`` on real PostgreSQL: one round trip, replies instead of exceptions (ADR-0012).

Every test runs with the sync and the async driver (the ``drivers`` fixture). ``fetch_plain``
reads on a separate connection, so it sees committed data only; ``rows_seen_while_held`` reads
there before the session is left, so the release's ``ROLLBACK`` cannot account for the result.
"""

from unittest.mock import ANY

import pytest

from platina.drivers.interface import (
    Completed,
    DatabaseFault,
    Failed,
    Lost,
    StatementResult,
    UnreadableRows,
)
from tests.support.database import (
    ITEM_IDS,
    create_allocations,
    create_days,
    create_deferred_keys,
    create_items,
    fetch_plain,
)
from tests.support.drivers import (
    backend_pid,
    failing_int_adapters,
    raised_by_pipeline,
    raising_uuid_loader_adapters,
    rows_seen_while_held,
    run_in_session,
    run_round_trips,
    session_pid,
    with_string_params,
)
from tests.support.statements import (
    ADD_ONE,
    BEGIN,
    BEGIN_RESULT,
    COMMIT,
    COMMIT_RESULT,
    DIVIDE_BY_ZERO,
    INSERT_RESULT,
    ROLLBACK,
    ROLLBACK_RESULT,
    SELECT_ONE,
    SIXTH_EXECUTION_AFTER_A_FAILURE,
    SQL,
    TERMINATE_OWN_BACKEND,
    commit_status,
    fault_of,
    insert_item,
    insert_key,
    unreadable_fault,
)

UNADAPTABLE_INT = SQL("SELECT %s::int", (object(),))
INSERT_INFINITE_DAY = SQL("INSERT INTO days (d) VALUES ('infinity') RETURNING d")

# --------------------------------------------------------------------------- success


def test_pipeline_of_successful_statements_completes_with_one_result_each(driver, database_dsn):
    # given
    create_items(database_dsn)
    statements = [BEGIN, insert_item(2), insert_item(3), SQL(ITEM_IDS), COMMIT]
    # when
    reply = run_in_session(driver, statements)
    # then
    assert reply == Completed(
        (
            BEGIN_RESULT,
            INSERT_RESULT,
            INSERT_RESULT,
            StatementResult("SELECT 3", 3, ((1,), (2,), (3,))),
            COMMIT_RESULT,
        )
    )


def test_pipeline_without_statements_completes_with_no_results(driver):
    # when
    reply = run_in_session(driver, [])
    # then
    assert reply == Completed(())


def test_pipeline_committed_transaction_is_visible_to_another_connection(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    run_in_session(driver, [BEGIN, insert_item(2), COMMIT])
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,), (2,)]


def test_pipeline_statement_without_begin_is_committed_at_once(driver, database_dsn):
    # given: the connection is in autocommit mode; only the statements' own BEGIN opens one
    create_items(database_dsn)
    # when
    seen = rows_seen_while_held(driver, database_dsn, ITEM_IDS, [insert_item(2)])
    # then
    assert seen == [(1,), (2,)]


@pytest.mark.parametrize(
    ("statement", "rows"),
    [
        pytest.param(SQL("SELECT '%%'::text"), (("%",),), id="literal-percent-without-params"),
        pytest.param(SQL("SELECT %s::int", (5,)), ((5,),), id="placeholder"),
    ],
)
def test_pipeline_passes_params_always_so_percent_is_escaped(driver, statement, rows):
    # when
    reply = run_in_session(driver, [statement])
    # then
    assert reply == Completed((StatementResult("SELECT 1", 1, rows),))


# --------------------------------------------------------------------------- unreadable rows


def test_pipeline_unloadable_returning_value_completes_with_unreadable_rows(driver, database_dsn):
    # given: 'infinity' is a valid date that psycopg cannot load
    create_days(database_dsn)
    # when
    reply = run_in_session(driver, [BEGIN, INSERT_INFINITE_DAY, COMMIT])
    # then
    assert reply == Completed(
        (BEGIN_RESULT, StatementResult("INSERT 0 1", 1, UnreadableRows(ANY)), COMMIT_RESULT)
    )


def test_pipeline_unreadable_rows_fault_has_no_sqlstate(driver, database_dsn):
    # given
    create_days(database_dsn)
    # when
    reply = run_in_session(driver, [BEGIN, INSERT_INFINITE_DAY, COMMIT])
    # then
    assert unreadable_fault(reply, 1).sqlstate is None


def test_pipeline_unreadable_rows_keep_the_data_committed(driver, database_dsn):
    # given
    create_days(database_dsn)
    # when
    run_in_session(driver, [BEGIN, INSERT_INFINITE_DAY, COMMIT])
    # then
    assert fetch_plain(database_dsn, "SELECT d::text FROM days") == [("infinity",)]


def test_pipeline_rows_a_caller_loader_cannot_load_complete_with_unreadable_rows(
    drivers, database_dsn
):
    # given: a loader from the caller's adapters map raising ValueError, not a psycopg error
    create_items(database_dsn)
    configured = drivers.open(database_dsn, adapters=failing_int_adapters())
    returning = SQL("INSERT INTO items (id, qty) VALUES (7, 1) RETURNING id")
    # when
    reply = run_in_session(configured, [BEGIN, returning, COMMIT])
    # then
    assert reply == Completed(
        (BEGIN_RESULT, StatementResult("INSERT 0 1", 1, UnreadableRows(ANY)), COMMIT_RESULT)
    )


def test_pipeline_rows_after_unreadable_rows_are_still_loaded(driver):
    # when
    reply = run_in_session(driver, [SQL("SELECT 'infinity'::date"), SQL("SELECT 1")])
    # then
    assert reply == Completed(
        (
            StatementResult("SELECT 1", 1, UnreadableRows(ANY)),
            StatementResult("SELECT 1", 1, ((1,),)),
        )
    )


# --------------------------------------------------------------------------- server errors


def test_pipeline_failing_at_its_first_statement_fails_at_zero_with_no_results(
    driver, database_dsn
):
    # given: the transaction was begun by an earlier round trip
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN])
        # when
        reply = session.pipeline([insert_item(2, qty=-1), insert_item(3), COMMIT])
    # then
    assert reply == Failed((), ANY)


def test_pipeline_server_skips_the_statements_after_a_failed_one(driver, database_dsn):
    # given: a PostgreSQL fact Failed relies on. Run, the ROLLBACK would end the transaction
    # and the insert after it would commit on its own (autocommit): row 3 would exist.
    create_items(database_dsn)
    statements = [BEGIN, insert_item(2), insert_item(1), ROLLBACK, insert_item(3)]
    # when
    run_in_session(driver, statements)
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,)]


def test_pipeline_check_violation_names_constraint_table_and_schema(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    reply = run_in_session(driver, [BEGIN, insert_item(2, qty=-1), COMMIT])
    # then
    assert fault_of(reply) == DatabaseFault("23514", ANY, "items_qty_check", "items", "public", ANY)


def test_pipeline_failing_in_the_middle_reports_the_results_before_it(driver, database_dsn):
    # given: id 1 exists, so the second insert violates the primary key
    create_items(database_dsn)
    statements = [BEGIN, insert_item(2), insert_item(1), insert_item(3), COMMIT]
    # when
    reply = run_in_session(driver, statements)
    # then
    assert reply == Failed((BEGIN_RESULT, INSERT_RESULT), ANY)


def test_pipeline_unique_violation_names_constraint_table_and_schema(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    reply = run_in_session(driver, [BEGIN, insert_item(1), COMMIT])
    # then
    assert fault_of(reply) == DatabaseFault("23505", ANY, "items_pkey", "items", "public", ANY)


def test_pipeline_fault_message_is_the_primary_message_without_key_values(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    reply = run_in_session(driver, [BEGIN, insert_item(1), COMMIT])
    # then
    assert fault_of(reply).message == 'duplicate key value violates unique constraint "items_pkey"'


def test_pipeline_server_error_before_a_client_error_is_the_one_reported(driver, database_dsn):
    # given: the duplicate fails on the server; the NUL character cannot be sent at all
    create_items(database_dsn)
    statements = [BEGIN, insert_item(1), SQL("SELECT %s::text", ("a\x00b",)), COMMIT]
    # when
    reply = run_in_session(driver, statements)
    # then
    assert (reply, fault_of(reply).sqlstate) == (Failed((BEGIN_RESULT,), ANY), "23505")


def test_pipeline_server_error_surfacing_in_a_later_execute_is_reported_at_its_statement(
    driver, database_dsn
):
    # given: with 500 statements behind it, the duplicate's error arrives while psycopg is
    # still sending - raised by a later execute(), then PipelineAborted at the block's exit
    create_items(database_dsn)
    statements = [BEGIN, insert_item(1), *([SELECT_ONE] * 500), COMMIT]
    # when
    reply = run_in_session(driver, statements)
    # then
    assert (reply, fault_of(reply).sqlstate) == (Failed((BEGIN_RESULT,), ANY), "23505")


def test_pipeline_deferred_violation_fails_at_the_commit(driver, database_dsn):
    # given
    create_deferred_keys(database_dsn)
    statements = [BEGIN, insert_key(1), insert_key(1), COMMIT]
    # when
    reply = run_in_session(driver, statements)
    # then
    assert reply == Failed((BEGIN_RESULT, INSERT_RESULT, INSERT_RESULT), ANY)


def test_pipeline_foreign_key_violation_names_constraint_table_and_schema(driver, database_dsn):
    # given: an allocation of an item that does not exist
    create_allocations(database_dsn)
    allocate = SQL("INSERT INTO allocations (id, item_id) VALUES (1, %s)", (99,))
    # when
    reply = run_in_session(driver, [BEGIN, allocate, COMMIT])
    # then
    assert fault_of(reply) == DatabaseFault(
        "23503", ANY, "allocations_item_id_fkey", "allocations", "public", ANY
    )


def test_pipeline_deferred_violation_at_commit_names_the_constraint(driver, database_dsn):
    # given
    create_deferred_keys(database_dsn)
    # when
    reply = run_in_session(driver, [BEGIN, insert_key(1), insert_key(1), COMMIT])
    # then
    assert fault_of(reply) == DatabaseFault("23505", ANY, "keys_id_key", "keys", "public", ANY)


def test_pipeline_deferred_violation_at_commit_commits_nothing(driver, database_dsn):
    # given
    create_deferred_keys(database_dsn)
    statements = [BEGIN, insert_key(1), insert_key(1), COMMIT]
    # when
    seen = rows_seen_while_held(driver, database_dsn, "SELECT id FROM keys", statements)
    # then
    assert seen == []


def test_pipeline_after_a_failure_before_commit_rollback_completes(driver, database_dsn):
    # given
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN, insert_item(1), COMMIT])
        # when
        reply = session.pipeline([ROLLBACK])
    # then
    assert reply == Completed((ROLLBACK_RESULT,))


def test_pipeline_after_a_failure_and_rollback_the_next_transaction_commits(driver, database_dsn):
    # given
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN, insert_item(1), COMMIT])
        session.pipeline([ROLLBACK])
        # when
        reply = session.pipeline([BEGIN, insert_item(2), COMMIT])
    # then
    assert reply == Completed((BEGIN_RESULT, INSERT_RESULT, COMMIT_RESULT))


def test_pipeline_error_after_commit_reports_the_commit_result(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    reply = run_in_session(driver, [BEGIN, insert_item(2), COMMIT, DIVIDE_BY_ZERO])
    # then
    assert (reply, fault_of(reply).sqlstate) == (
        Failed((BEGIN_RESULT, INSERT_RESULT, COMMIT_RESULT), ANY),
        "22012",
    )


def test_pipeline_error_after_commit_keeps_the_data_committed(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    run_in_session(driver, [BEGIN, insert_item(2), COMMIT, DIVIDE_BY_ZERO])
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,), (2,)]


def test_pipeline_commit_of_a_transaction_aborted_earlier_answers_rollback(driver, database_dsn):
    # given: the first round trip aborts the transaction
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN, insert_item(1)])
        # when
        reply = session.pipeline([COMMIT])
    # then
    assert reply == Completed((ROLLBACK_RESULT,))


def test_pipeline_commit_of_a_transaction_aborted_earlier_commits_nothing(driver, database_dsn):
    # given
    create_items(database_dsn)
    aborting = [BEGIN, insert_item(2), insert_item(1)]
    # when
    seen = rows_seen_while_held(driver, database_dsn, ITEM_IDS, aborting, [COMMIT])
    # then
    assert seen == [(1,)]


# --------------------------------------------------------------------------- client errors


def test_pipeline_unadaptable_param_fails_at_its_statement(driver, database_dsn):
    # given
    create_items(database_dsn)
    statements = [BEGIN, insert_item(2), insert_item(3, qty=object()), COMMIT]
    # when
    reply = run_in_session(driver, statements)
    # then
    assert reply == Failed((BEGIN_RESULT, INSERT_RESULT), ANY)


def test_pipeline_unadaptable_param_fault_has_no_sqlstate(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    reply = run_in_session(driver, [BEGIN, insert_item(3, qty=object()), COMMIT])
    # then
    assert fault_of(reply).sqlstate is None


def test_pipeline_unadaptable_param_sends_nothing_after_it(driver, database_dsn):
    # given
    create_items(database_dsn)
    statements = [BEGIN, insert_item(2), insert_item(3, qty=object()), COMMIT]
    # when
    seen = rows_seen_while_held(driver, database_dsn, ITEM_IDS, statements)
    # then
    assert seen == [(1,)]


def test_pipeline_commit_after_a_client_error_commits_the_statements_before_it(
    driver, database_dsn
):
    # given: a client-side error leaves the transaction open, not aborted (pinned fact)
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN, insert_item(2), UNADAPTABLE_INT])
        # when
        reply = session.pipeline([COMMIT])
    # then
    assert reply == Completed((COMMIT_RESULT,))


def test_pipeline_commit_after_a_client_error_makes_the_earlier_rows_visible(driver, database_dsn):
    # given
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN, insert_item(2), UNADAPTABLE_INT])
        # when
        session.pipeline([COMMIT])
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,), (2,)]


def test_pipeline_rollback_after_a_client_error_discards_the_earlier_rows(driver, database_dsn):
    # given: read on the same session - inside the open transaction row 2 would be visible
    create_items(database_dsn)
    with driver.session() as session:
        session.pipeline([BEGIN, insert_item(2), UNADAPTABLE_INT])
        # when
        session.pipeline([ROLLBACK])
        # then
        assert session.pipeline([SQL(ITEM_IDS)]) == Completed(
            (StatementResult("SELECT 1", 1, ((1,),)),)
        )


def test_pipeline_unadaptable_param_after_commit_reports_the_commit_result(driver, database_dsn):
    # given
    create_items(database_dsn)
    statements = [BEGIN, insert_item(2), COMMIT, SQL("SELECT %s", (object(),))]
    # when
    reply = run_in_session(driver, statements)
    # then
    assert reply == Failed((BEGIN_RESULT, INSERT_RESULT, COMMIT_RESULT), ANY)


def test_pipeline_unadaptable_param_after_commit_keeps_the_data_committed(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    run_in_session(driver, [BEGIN, insert_item(2), COMMIT, SQL("SELECT %s", (object(),))])
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,), (2,)]


# --------------------------------------------------------------------------- connection lost


def test_pipeline_connection_lost_before_commit_is_lost_with_the_results_before_it(
    driver, database_dsn
):
    # given
    create_items(database_dsn)
    # when
    reply = run_in_session(driver, [BEGIN, insert_item(2), TERMINATE_OWN_BACKEND, COMMIT])
    # then
    assert reply == Lost((BEGIN_RESULT, INSERT_RESULT), ANY)


def test_pipeline_connection_lost_fault_has_no_sqlstate(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    reply = run_in_session(driver, [BEGIN, insert_item(2), TERMINATE_OWN_BACKEND, COMMIT])
    # then
    assert fault_of(reply).sqlstate is None


def test_pipeline_connection_lost_before_commit_commits_nothing(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    run_in_session(driver, [BEGIN, insert_item(2), TERMINATE_OWN_BACKEND, COMMIT])
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,)]


def test_pipeline_connection_lost_after_commit_is_lost_with_the_commit_result(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    reply = run_in_session(driver, [BEGIN, insert_item(2), COMMIT, TERMINATE_OWN_BACKEND])
    # then
    assert reply == Lost((BEGIN_RESULT, INSERT_RESULT, COMMIT_RESULT), ANY)


def test_pipeline_connection_lost_after_commit_keeps_the_data_committed(driver, database_dsn):
    # given
    create_items(database_dsn)
    # when
    run_in_session(driver, [BEGIN, insert_item(2), COMMIT, TERMINATE_OWN_BACKEND])
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,), (2,)]


def test_pipeline_unclean_end_after_commit_is_lost_without_claiming_an_outcome(
    database_dsn, drivers
):
    # given: psycopg fails setting up the uuid result itself and stays in pipeline mode, so
    # nothing after it can be known - the COMMIT did run (next test)
    create_items(database_dsn)
    configured = drivers.open(database_dsn, adapters=raising_uuid_loader_adapters())
    statements = [BEGIN, insert_item(16), SQL("SELECT gen_random_uuid()"), COMMIT, SELECT_ONE]
    # when
    reply = run_in_session(configured, statements)
    # then
    assert (type(reply), commit_status(reply)) == (Lost, None)


def test_pipeline_unclean_end_after_commit_keeps_the_data_committed(database_dsn, drivers):
    # given
    create_items(database_dsn)
    configured = drivers.open(database_dsn, adapters=raising_uuid_loader_adapters())
    statements = [BEGIN, insert_item(16), SQL("SELECT gen_random_uuid()"), COMMIT, SELECT_ONE]
    # when
    run_in_session(configured, statements)
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,), (16,)]


@pytest.mark.parametrize("trailing", [0, 2000])
def test_pipeline_loader_failing_mid_round_trip_after_commit_is_lost_with_commit_result(
    database_dsn, drivers, trailing
):
    # given: with many statements after it, the loader's error surfaces from a later execute()
    # instead of at the block's exit; either way the COMMIT that ran stays visible
    create_items(database_dsn)
    configured = drivers.open(database_dsn, adapters=raising_uuid_loader_adapters())
    statements = [
        BEGIN,
        insert_item(16),
        COMMIT,
        SQL("SELECT gen_random_uuid()"),
        *[SELECT_ONE] * trailing,
    ]
    # when
    reply = run_in_session(configured, statements)
    # then
    assert reply == Lost((BEGIN_RESULT, INSERT_RESULT, COMMIT_RESULT), ANY)


def test_pipeline_programming_error_before_sending_propagates(driver, database_dsn):
    # given: parameters that are not a sequence fail in execute(), before the statement is sent
    create_items(database_dsn)
    statements = [BEGIN, insert_item(2), with_string_params("SELECT %s::text", "ab")]
    # when
    raised = raised_by_pipeline(driver, statements)
    # then
    assert type(raised) is TypeError


def test_pipeline_programming_error_leaves_nothing_committed(driver, database_dsn):
    # given
    create_items(database_dsn)
    statements = [BEGIN, insert_item(2), with_string_params("SELECT %s::text", "ab"), COMMIT]
    # when
    raised_by_pipeline(driver, statements)
    # then
    assert fetch_plain(database_dsn, ITEM_IDS) == [(1,)]


def test_pipeline_unclean_end_discards_the_connection(database_dsn, drivers):
    # given
    configured = drivers.open(database_dsn, adapters=raising_uuid_loader_adapters())
    with configured.session() as session:
        unclean_pid = backend_pid(session)
        session.pipeline([BEGIN, SQL("SELECT gen_random_uuid()"), COMMIT])
    # when
    pid = session_pid(configured)
    # then
    assert pid != unclean_pid


def test_pipeline_deferred_violation_without_begin_is_lost(driver, database_dsn):
    # given: the pipeline's implicit transaction fails when it ends, after the last result
    # (observed with psycopg 3.3.9: the connection is left unclean, so the reply is Lost)
    create_deferred_keys(database_dsn)
    # when
    reply = run_in_session(driver, [insert_key(1), insert_key(1)])
    # then
    assert reply == Lost((INSERT_RESULT, INSERT_RESULT), ANY)


def test_pipeline_deferred_violation_without_begin_commits_nothing(driver, database_dsn):
    # given
    create_deferred_keys(database_dsn)
    # when
    run_in_session(driver, [insert_key(1), insert_key(1)])
    # then
    assert fetch_plain(database_dsn, "SELECT id FROM keys") == []


# --------------------------------------------------------------------------- prepared statements


def test_pipeline_next_session_after_a_skipped_sixth_execution_completes(driver):
    # given: the sixth execution of ADD_ONE sits after a failure in its pipeline; with psycopg's
    # automatic preparation it would be recorded as prepared although the server skipped it
    with driver.session() as session:
        run_round_trips(session, *SIXTH_EXECUTION_AFTER_A_FAILURE)
    # when
    with driver.session() as session:
        reply = session.pipeline([BEGIN, ADD_ONE, COMMIT])
    # then
    assert reply == Completed(
        (BEGIN_RESULT, StatementResult("SELECT 1", 1, ((2,),)), COMMIT_RESULT)
    )


def test_pipeline_transaction_control_after_a_skipped_sixth_execution_completes(driver):
    # given
    with driver.session() as session:
        run_round_trips(session, *SIXTH_EXECUTION_AFTER_A_FAILURE)
    # when
    with driver.session() as session:
        reply = session.pipeline([ROLLBACK, BEGIN, COMMIT])
    # then
    assert reply == Completed((ROLLBACK_RESULT, BEGIN_RESULT, COMMIT_RESULT))
