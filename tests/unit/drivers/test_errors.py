"""SQLSTATE -> public exception mapping (``platina.drivers.errors``, engine rule 10, ADR-0012)."""

import pytest

from platina.core.errors import CheckViolation, DatabaseError, ForeignKeyViolation, UniqueViolation
from platina.drivers.errors import FOREIGN_KEY_HINT, database_error
from tests.support.faults import fault

SQLSTATE_CLASSES = [
    pytest.param("23505", UniqueViolation, id="unique-violation"),
    pytest.param("23514", CheckViolation, id="check-violation"),
    pytest.param("23503", ForeignKeyViolation, id="foreign-key-violation"),
    pytest.param("23001", ForeignKeyViolation, id="restrict-violation"),
    pytest.param("40001", DatabaseError, id="serialization-failure"),
    pytest.param("40P01", DatabaseError, id="deadlock"),
    pytest.param("57014", DatabaseError, id="query-canceled"),
    pytest.param("53200", DatabaseError, id="out-of-memory"),
    pytest.param("22012", DatabaseError, id="division-by-zero"),
    pytest.param(None, DatabaseError, id="no-sqlstate"),
]

# One SQLSTATE per constructor call in database_error (UniqueViolation, CheckViolation,
# ForeignKeyViolation, DatabaseError with a SQLSTATE and without one), so a field dropped by one
# call is caught.
CONSTRUCTOR_SQLSTATES = ["23505", "23514", "23503", "40001", None]


@pytest.mark.parametrize(("sqlstate", "cls"), SQLSTATE_CLASSES)
def test_database_error_of_a_sqlstate_is_exactly_its_class(sqlstate, cls):
    # given
    failure = fault(sqlstate)
    # when
    exc = database_error(failure, usecase="pay")
    # then
    assert type(exc) is cls


@pytest.mark.parametrize(("sqlstate", "cls"), SQLSTATE_CLASSES)
def test_database_error_keeps_the_fault_sqlstate(sqlstate, cls):
    # given
    failure = fault(sqlstate)
    # when
    exc = database_error(failure, usecase="pay")
    # then
    assert exc.sqlstate == sqlstate


@pytest.mark.parametrize("sqlstate", CONSTRUCTOR_SQLSTATES)
@pytest.mark.parametrize("usecase", ["pay", None])
def test_database_error_passes_the_usecase_through(usecase, sqlstate):
    # given
    failure = fault(sqlstate)
    # when
    exc = database_error(failure, usecase=usecase)
    # then
    assert exc.usecase == usecase


@pytest.mark.parametrize("sqlstate", CONSTRUCTOR_SQLSTATES)
def test_database_error_chains_the_driver_exception_as_cause(sqlstate):
    # given
    failure = fault(sqlstate)
    # when
    exc = database_error(failure, usecase="pay")
    # then
    assert exc.__cause__ is failure.cause


@pytest.mark.parametrize("sqlstate", CONSTRUCTOR_SQLSTATES)
def test_database_error_suppresses_the_context_like_raise_from(sqlstate):
    # given
    failure = fault(sqlstate)
    # when
    exc = database_error(failure, usecase="pay")
    # then
    assert exc.__suppress_context__ is True


@pytest.mark.parametrize("sqlstate", CONSTRUCTOR_SQLSTATES)
def test_database_error_message_is_the_fault_message(sqlstate):
    # given
    failure = fault(sqlstate, message="could not serialize access")
    # when
    exc = database_error(failure, usecase="pay")
    # then
    assert exc.args == ("could not serialize access",)


@pytest.mark.parametrize(
    ("constraint", "table", "schema", "details"),
    [
        pytest.param(
            "orders_number_key", "orders", "public",
            (("Constraint", "orders_number_key"), ("Table", "public.orders")),
            id="constraint-table-schema",
        ),
        pytest.param(
            "orders_number_key", "orders", None,
            (("Constraint", "orders_number_key"), ("Table", "orders")),
            id="table-without-schema",
        ),
        pytest.param(
            "orders_number_key", None, None,
            (("Constraint", "orders_number_key"),),
            id="constraint-only",
        ),
        pytest.param(None, "orders", "public", (("Table", "public.orders"),), id="table-only"),
        pytest.param(None, None, "public", (), id="schema-without-table"),
        pytest.param(None, None, None, (), id="nothing-named"),
    ],
)  # fmt: skip
@pytest.mark.parametrize("sqlstate", CONSTRUCTOR_SQLSTATES)
def test_database_error_details_name_the_constraint_and_table(
    constraint, table, schema, details, sqlstate
):
    # given
    failure = fault(sqlstate, constraint=constraint, table=table, schema=schema)
    # when
    exc = database_error(failure, usecase="pay")
    # then
    assert exc.details == details


def test_database_error_renders_no_line_for_the_server_detail_text():
    # given: the cause's text carries "DETAIL:  Key (number)=(42) already exists."
    failure = fault(
        "23505",
        message='duplicate key value violates unique constraint "orders_number_key"',
        constraint="orders_number_key",
        table="orders",
        schema="public",
    )
    # when
    rendered = str(database_error(failure, usecase="pay"))
    # then
    assert rendered == (
        'duplicate key value violates unique constraint "orders_number_key"\n'
        "  Constraint: orders_number_key\n"
        "  Table: public.orders"
    )


@pytest.mark.parametrize("field", ["entity", "field", "location", "hint"])
def test_database_error_leaves_the_fields_a_fault_cannot_know_unset(field):
    # given
    failure = fault("23505", constraint="orders_number_key", table="orders", schema="public")
    # when
    exc = database_error(failure, usecase="pay")
    # then
    assert getattr(exc, field) is None


@pytest.mark.parametrize("sqlstate", ["23503", "23001"])
def test_database_error_of_a_foreign_key_violation_hints_at_the_referencing_rows(sqlstate):
    # given
    failure = fault(sqlstate)
    # when
    exc = database_error(failure, usecase="pay")
    # then
    assert exc.hint == FOREIGN_KEY_HINT


@pytest.mark.parametrize("sqlstate", ["23505", "23514", "40001", None])
def test_database_error_of_another_sqlstate_has_no_hint(sqlstate):
    # given
    failure = fault(sqlstate)
    # when
    exc = database_error(failure, usecase="pay")
    # then
    assert exc.hint is None
