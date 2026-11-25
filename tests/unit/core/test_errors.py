"""The exception hierarchy of design section 10.12 and its fields and rendering (ADR-0006)."""

import dataclasses

import pytest

import platina
from platina.core import errors
from platina.core.errors import (
    ChainClosed,
    CheckViolation,
    CommitCycle,
    ConcurrencyError,
    ConflictingWrites,
    DatabaseError,
    IntraUsecaseConflict,
    ModuleBoundaryError,
    MovedSnapshotAccess,
    NotFound,
    PlatinaError,
    RelationNotLoaded,
    RetryExhausted,
    SealError,
    SourceLocation,
    UniqueViolation,
    UnloadedReference,
    UsageError,
    VersionMismatch,
)
from tests.support.errors import (
    AttemptsExhausted,
    Copier,
    Order,
    deep_copy,
    pickle_round_trip,
    raise_database_error_from,
    shallow_copy,
    state_of,
    untyped_error,
    with_field,
    with_note,
)

PUBLIC_NAMES = [
    "PlatinaError",
    "SourceLocation",
    "SealError",
    "ModuleBoundaryError",
    "UsageError",
    "RelationNotLoaded",
    "UnloadedReference",
    "ChainClosed",
    "MovedSnapshotAccess",
    "ConflictingWrites",
    "IntraUsecaseConflict",
    "CommitCycle",
    "NotFound",
    "ConcurrencyError",
    "RetryExhausted",
    "VersionMismatch",
    "DatabaseError",
    "UniqueViolation",
    "CheckViolation",
]

MESSAGE_ONLY_CLASSES = [
    PlatinaError,
    SealError,
    ModuleBoundaryError,
    UsageError,
    RelationNotLoaded,
    UnloadedReference,
    ChainClosed,
    MovedSnapshotAccess,
    ConflictingWrites,
    IntraUsecaseConflict,
    CommitCycle,
    NotFound,
    ConcurrencyError,
    RetryExhausted,
    VersionMismatch,
]

LOCATION = SourceLocation("shop/billing/usecases.py", 12, "pay")

# One instance per class with several fields set (all of them on PlatinaError), so a copy that
# drops a field is caught.
FULL_INSTANCES = [
    PlatinaError("m", usecase="pay", entity=Order, field="items", location=LOCATION, hint="h",
                 details=(("Label", "value"),)),
    SealError("m", entity=Order, field="status", location=LOCATION, hint="h"),
    ModuleBoundaryError("m", usecase="restock", entity=Order, hint="h"),
    UsageError("m", usecase="pay", location=LOCATION),
    RelationNotLoaded("m", usecase="pay", entity=Order, field="items", location=LOCATION,
                      hint="h", details=(("Actual load declaration", "Load()"),)),
    UnloadedReference("m", entity=Order, hint="h"),
    ChainClosed("m", entity=Order, field="total", location=LOCATION),
    MovedSnapshotAccess("m", entity=Order, field="total", location=LOCATION, hint="h"),
    ConflictingWrites("m", entity=Order, field="status"),
    IntraUsecaseConflict("m", usecase="pay", entity=Order),
    CommitCycle("m", entity=Order),
    NotFound("m", usecase="pay", entity=Order),
    ConcurrencyError("m", usecase="pay"),
    RetryExhausted("m", usecase="pay", hint="h"),
    VersionMismatch("m", usecase="edit", entity=Order),
    DatabaseError("m", sqlstate="22001", usecase="pay"),
    UniqueViolation("m", sqlstate="23505", entity=Order, field="number"),
    CheckViolation("m", sqlstate="23514", entity=Order, field="total"),
]  # fmt: skip

# Design section 4.13, with the maintainer's decisions of 2026-11-25 (ADR-0006): the location
# line is always `Location: ...`, and the first example's `·` line is two details.
SECTION_4_13_EXAMPLES = [
    pytest.param(
        RelationNotLoaded(
            "Order.items is not loaded.",
            usecase="pay",
            entity=Order,
            field="items",
            location=SourceLocation("shop/billing/usecases.py", 12, "pay"),
            details=(
                ("Actual load declaration", "Load()"),
                ("Example of the needed declaration",
                 "orders.payable = Profile(Order.items, Order.user)"),
            ),
            hint="use Annotated[Order, orders.payable] or add Load(Order.items)",
        ),
        "Order.items is not loaded.\n"
        "  Location: shop/billing/usecases.py:12  (pay)\n"
        "  Actual load declaration: Load()\n"
        "  Example of the needed declaration: orders.payable = Profile(Order.items, Order.user)\n"
        "  Fix: use Annotated[Order, orders.payable] or add Load(Order.items)",
        id="relation-not-loaded",
    ),
    pytest.param(
        MovedSnapshotAccess(
            "alias is an alias of order, which was moved by chain. Order.total was read.",
            usecase="checkout",
            entity=Order,
            field="total",
            location=SourceLocation("shop/billing/usecases.py", 31, "checkout"),
            hint="use the order returned by chain, or c.original(order) if you need the value "
            "before the change",
        ),
        "alias is an alias of order, which was moved by chain. Order.total was read.\n"
        "  Location: shop/billing/usecases.py:31  (checkout)\n"
        "  Fix: use the order returned by chain, or c.original(order) if you need the value "
        "before the change",
        id="moved-snapshot-access",
    ),
    pytest.param(
        UnloadedReference(
            ".set was called on Order.ref(...). A ref is only a load request.",
            entity=Order,
            hint="take it as a use case parameter so it is loaded, or state it explicitly with "
            "Order.where(Order.id == x).set(...)",
        ),
        ".set was called on Order.ref(...). A ref is only a load request.\n"
        "  Fix: take it as a use case parameter so it is loaded, or state it explicitly with "
        "Order.where(Order.id == x).set(...)",
        id="unloaded-reference",
    ),
    pytest.param(
        SealError(
            "the key of inline projection daily_revenue is not an entity ID (date).",
            hint='mode="async" or allow_hot_key="reason"',
        ),
        "the key of inline projection daily_revenue is not an entity ID (date).\n"
        '  Fix: mode="async" or allow_hot_key="reason"',
        id="seal-hot-projection-key",
    ),
    pytest.param(
        SealError(
            "a set change modifies a field protected by an invariant.",
            entity=Order,
            field="status",
            location=SourceLocation("shop/billing/repos.py", 41, "OrderRepo.expire_older_than"),
            details=(
                ("Field", "Order.status  ← @invariant paid_requires_total (entities.py:29)"),
            ),
            hint='move the invariant to Check(...) or state .set(..., unsafe_bypass="reason") '
            "explicitly",
        ),
        "a set change modifies a field protected by an invariant.\n"
        "  Location: shop/billing/repos.py:41  (OrderRepo.expire_older_than)\n"
        "  Field: Order.status  ← @invariant paid_requires_total (entities.py:29)\n"
        '  Fix: move the invariant to Check(...) or state .set(..., unsafe_bypass="reason") '
        "explicitly",
        id="seal-invariant-bypass",
    ),
    pytest.param(
        SealError(
            "the Load.when expression is ambiguous. refund_merge has two parameters of type "
            "Order (src, dst).",
            usecase="refund_merge",
            entity=Order,
            hint="use Load.after(function) to state which parameter is meant",
        ),
        "the Load.when expression is ambiguous. refund_merge has two parameters of type "
        "Order (src, dst).\n"
        "  Fix: use Load.after(function) to state which parameter is meant",
        id="seal-ambiguous-load-when",
    ),
    pytest.param(
        ModuleBoundaryError(
            "shop.catalog.usecases.restock loads the entity Order of the billing module.",
            usecase="restock",
            entity=Order,
            hint="use a query published by billing (orders.summaries) or communicate through "
            "events",
        ),
        "shop.catalog.usecases.restock loads the entity Order of the billing module.\n"
        "  Fix: use a query published by billing (orders.summaries) or communicate through "
        "events",
        id="module-boundary",
    ),
]  # fmt: skip


@pytest.mark.parametrize(
    ("cls", "parent"),
    [
        (PlatinaError, Exception),
        (SealError, PlatinaError),
        (ModuleBoundaryError, SealError),
        (UsageError, PlatinaError),
        (RelationNotLoaded, UsageError),
        (UnloadedReference, UsageError),
        (ChainClosed, UsageError),
        (MovedSnapshotAccess, UsageError),
        (ConflictingWrites, UsageError),
        (IntraUsecaseConflict, UsageError),
        (CommitCycle, UsageError),
        (NotFound, PlatinaError),
        (ConcurrencyError, PlatinaError),
        (RetryExhausted, ConcurrencyError),
        (VersionMismatch, ConcurrencyError),
        (DatabaseError, PlatinaError),
        (UniqueViolation, DatabaseError),
        (CheckViolation, DatabaseError),
    ],
)
def test_exception_class_has_the_parent_of_section_10_12(cls, parent):
    # when
    bases = cls.__bases__
    # then
    assert bases == (parent,)


@pytest.mark.parametrize("name", PUBLIC_NAMES)
def test_platina_reexports_the_name_from_core_errors(name):
    # when
    exported = getattr(platina, name)
    # then
    assert exported is getattr(errors, name)


def test_platina_all_lists_exactly_the_exception_names():
    # when
    public = set(platina.__all__)
    # then
    assert public == set(PUBLIC_NAMES)


def test_core_errors_all_lists_exactly_the_exception_names():
    # when
    defined = set(errors.__all__)
    # then
    assert defined == set(PUBLIC_NAMES)


@pytest.mark.parametrize("field", ["usecase", "entity", "field", "location", "hint"])
def test_platina_error_field_without_argument_is_none(field):
    # when
    exc = PlatinaError("m")
    # then
    assert getattr(exc, field) is None


FIELD_VALUES = [
    ("usecase", "pay"),
    ("entity", Order),
    ("field", "address.city"),
    ("location", LOCATION),
    ("hint", "add Load(Order.items)"),
    ("details", (("Actual load declaration", "Load()"),)),
]


@pytest.mark.parametrize(("field", "value"), FIELD_VALUES)
def test_platina_error_keeps_the_field_it_was_given(field, value):
    # when
    exc = with_field(PlatinaError, field, value)
    # then
    assert getattr(exc, field) is value


@pytest.mark.parametrize(("field", "value"), FIELD_VALUES)
def test_database_error_keeps_the_base_field_it_was_given(field, value):
    # when
    exc = with_field(UniqueViolation, field, value, sqlstate="23505")
    # then
    assert getattr(exc, field) is value


def test_platina_error_details_without_argument_is_empty():
    # when
    exc = PlatinaError("m")
    # then
    assert exc.details == ()


@pytest.mark.parametrize("cls", MESSAGE_ONLY_CLASSES)
def test_exception_with_only_a_message_has_it_as_its_only_arg(cls):
    # when
    exc = cls("Order.items is not loaded.")
    # then
    assert exc.args == ("Order.items is not loaded.",)


@pytest.mark.parametrize("cls", MESSAGE_ONLY_CLASSES)
def test_exception_with_only_a_message_renders_the_message(cls):
    # when
    exc = cls("Order.items is not loaded.")
    # then
    assert str(exc) == "Order.items is not loaded."


@pytest.mark.parametrize("cls", [DatabaseError, UniqueViolation, CheckViolation])
def test_database_error_with_only_a_message_has_it_as_its_only_arg(cls):
    # when
    exc = cls("duplicate key value", sqlstate="23505")
    # then
    assert exc.args == ("duplicate key value",)


@pytest.mark.parametrize("cls", [DatabaseError, UniqueViolation, CheckViolation])
def test_database_error_with_only_a_message_renders_the_message(cls):
    # when
    exc = cls("duplicate key value", sqlstate="23505")
    # then
    assert str(exc) == "duplicate key value"


@pytest.mark.parametrize(("exc", "expected"), SECTION_4_13_EXAMPLES)
def test_exception_renders_the_section_4_13_example(exc, expected):
    # when
    rendered = str(exc)
    # then
    assert rendered == expected


def test_exception_renders_location_without_function_as_file_and_line():
    # given
    exc = PlatinaError("m", location=SourceLocation("shop/billing/entities.py", 29))
    # when
    rendered = str(exc)
    # then
    assert rendered == "m\n  Location: shop/billing/entities.py:29"


def test_exception_renders_usecase_entity_and_field_as_no_line():
    # given
    exc = PlatinaError("m", usecase="pay", entity=Order, field="items")
    # when
    rendered = str(exc)
    # then
    assert rendered == "m"


def test_exception_renders_location_then_details_then_fix_whatever_the_argument_order():
    # given
    exc = PlatinaError(
        "m",
        hint="h",
        details=(("First", "1"), ("Second", "2")),
        location=SourceLocation("a.py", 1, "f"),
    )
    # when
    rendered = str(exc)
    # then
    assert rendered == "m\n  Location: a.py:1  (f)\n  First: 1\n  Second: 2\n  Fix: h"


def test_exception_indents_continuation_lines_of_a_hint_four_spaces():
    # given
    exc = PlatinaError("m", hint="first line\nsecond line")
    # when
    rendered = str(exc)
    # then
    assert rendered == "m\n  Fix: first line\n    second line"


def test_exception_indents_continuation_lines_of_a_detail_four_spaces():
    # given
    exc = PlatinaError("m", details=(("Plan", "stage 1\nstage 2"),))
    # when
    rendered = str(exc)
    # then
    assert rendered == "m\n  Plan: stage 1\n    stage 2"


def test_exception_renders_an_empty_hint_as_a_fix_line():
    # given: only None drops a line
    exc = PlatinaError("m", hint="")
    # when
    rendered = str(exc)
    # then
    assert rendered == "m\n  Fix: "


def test_exception_renders_a_trailing_newline_in_a_value_as_no_extra_line():
    # given
    exc = PlatinaError("m", hint="first line\n")
    # when
    rendered = str(exc)
    # then
    assert rendered == "m\n  Fix: first line"


def test_exception_indents_continuation_lines_after_a_windows_line_break():
    # given
    exc = PlatinaError("m", hint="first line\r\nsecond line")
    # when
    rendered = str(exc)
    # then
    assert rendered == "m\n  Fix: first line\n    second line"


def test_exception_with_emptied_args_renders_an_empty_headline():
    # given
    exc = PlatinaError("m", hint="h")
    exc.args = ()
    # when
    rendered = str(exc)
    # then
    assert rendered == "\n  Fix: h"


def test_exception_renders_a_non_string_value_with_str():
    # given
    exc = untyped_error(hint=42)
    # when
    rendered = str(exc)
    # then
    assert rendered == "m\n  Fix: 42"


def test_exception_renders_a_detail_that_is_not_a_pair_as_a_bare_line():
    # given: the outer tuple is missing, so each string is a detail of its own
    exc = untyped_error(details=("Field", "Order.status"))
    # when
    rendered = str(exc)
    # then
    assert rendered == "m\n  Field\n  Order.status"


def test_exception_renders_a_multi_line_headline_as_given():
    # given
    exc = PlatinaError("first\nsecond", hint="h")
    # when
    rendered = str(exc)
    # then
    assert rendered == "first\nsecond\n  Fix: h"


def test_exception_headline_is_the_first_arg():
    # given
    exc = RelationNotLoaded("Order.items is not loaded.", hint="add Load(Order.items)")
    # when
    headline = exc.args[0]
    # then
    assert headline == "Order.items is not loaded."


def test_exception_repr_is_the_default_exception_repr():
    # given
    exc = RelationNotLoaded("Order.items is not loaded.", hint="add Load(Order.items)")
    # when
    text = repr(exc)
    # then
    assert text == "RelationNotLoaded('Order.items is not loaded.')"


@pytest.mark.parametrize("exc", FULL_INSTANCES, ids=lambda exc: type(exc).__name__)
@pytest.mark.parametrize(
    "copier", [pickle_round_trip, shallow_copy, deep_copy], ids=["pickle", "copy", "deepcopy"]
)
def test_exception_copy_keeps_class_args_and_every_field(exc, copier: Copier):
    # when
    copied = copier(exc)
    # then
    assert state_of(copied) == state_of(exc)


@pytest.mark.parametrize(
    "copier", [pickle_round_trip, shallow_copy, deep_copy], ids=["pickle", "copy", "deepcopy"]
)
def test_exception_copy_keeps_added_notes(copier: Copier):
    # given
    exc = with_note(RelationNotLoaded("m", entity=Order), "while handling request 7")
    # when
    copied = copier(exc)
    # then
    assert copied.__notes__ == ["while handling request 7"]


@pytest.mark.parametrize(
    "copier", [pickle_round_trip, shallow_copy, deep_copy], ids=["pickle", "copy", "deepcopy"]
)
def test_subclass_with_its_own_constructor_shape_survives_a_copy(copier: Copier):
    # given
    exc = AttemptsExhausted(attempts=4)
    # when
    copied = copier(exc)
    # then
    assert state_of(copied) == state_of(exc)


def test_exception_pickle_keeps_the_entity_class_by_reference():
    # given
    exc = RelationNotLoaded("m", entity=Order, field="items")
    # when
    restored = pickle_round_trip(exc)
    # then
    assert restored.entity is Order


def test_database_error_keeps_its_sqlstate():
    # when
    exc = UniqueViolation("duplicate key value", sqlstate="23505")
    # then
    assert exc.sqlstate == "23505"


def test_database_error_accepts_no_sqlstate_for_driver_errors_without_one():
    # when
    exc = DatabaseError("connection lost", sqlstate=None)
    # then
    assert exc.sqlstate is None


def test_database_error_raised_from_a_driver_exception_keeps_it_as_cause():
    # given
    driver_error = RuntimeError("duplicate key value violates unique constraint")
    # when / then
    with pytest.raises(DatabaseError) as raised:
        raise_database_error_from(driver_error)
    assert raised.value.__cause__ is driver_error
    assert raised.value.sqlstate == "23505"


def test_source_location_is_frozen():
    # given
    location = SourceLocation("shop/billing/usecases.py", 12, "pay")
    # when / then
    with pytest.raises(dataclasses.FrozenInstanceError):
        location.line = 13  # type: ignore[misc]


def test_source_location_declares_slots_for_its_three_fields():
    # when
    slots = SourceLocation.__slots__
    # then
    assert slots == ("file", "line", "function")


def test_source_location_function_defaults_to_none():
    # when
    location = SourceLocation("shop/billing/entities.py", 29)
    # then
    assert location.function is None
