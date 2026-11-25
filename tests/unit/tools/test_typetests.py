import pytest

from tests.support.guards import judged, pyright_json
from tools.typetests import Expectation, expectations, parse_mypy, parse_pyright

FAIL = "tests/typing/fail_bind.py"
PASS = "tests/typing/pass_bind.py"
FAIL_SOURCE = """\
pay.bind(order=oid)  # expect-error[reportArgumentType, arg-type]: UUID is not Order
pay.bind(order=ref)
orders.by_number(42)  # expect-error[reportArgumentType, reportCallIssue, arg-type]
Order.new()  # expect-error: no codes
"""
ARG = {"reportArgumentType"}
MYPY_ARG = {"arg-type"}


def test_markers_split_codes_between_the_two_checkers():
    # when
    found = expectations(FAIL_SOURCE)
    # then
    assert found == {
        1: Expectation(pyright=frozenset(ARG), mypy=frozenset(MYPY_ARG)),
        3: Expectation(
            pyright=frozenset({"reportArgumentType", "reportCallIssue"}), mypy=frozenset(MYPY_ARG)
        ),
        4: Expectation(pyright=frozenset(), mypy=frozenset()),
    }


def test_pyright_errors_keep_their_rule_and_warnings_are_ignored():
    # given
    output = pyright_json((FAIL, 1, "reportArgumentType"), (FAIL, 3, ""), warnings=((FAIL, 2),))
    # when
    errors = parse_pyright(output)
    # then
    assert errors == {FAIL: {1: ARG, 3: {"<none>"}}}


def test_mypy_errors_keep_their_code_and_notes_are_ignored():
    # given
    output = (
        f"{FAIL}:1: error: Argument 1 has incompatible type  [arg-type]\n"
        f"{FAIL}:1: note: See https://mypy.readthedocs.io\n"
        f"{FAIL}:3:5: error: Name 'x' is not defined  [name-defined]\n"
    )
    # when
    errors = parse_mypy(output)
    # then
    assert errors == {FAIL: {1: MYPY_ARG, 3: {"name-defined"}}}


@pytest.mark.parametrize(
    ("pyright", "mypy", "expected"),
    [
        ({1: ARG, 3: ARG}, {1: MYPY_ARG, 3: MYPY_ARG}, ["mypy:4", "pyright:4"]),
        ({1: ARG}, {1: MYPY_ARG, 3: MYPY_ARG}, ["mypy:4", "pyright:3", "pyright:4"]),
        (
            {1: {"reportUndefinedVariable"}, 3: ARG},
            {1: MYPY_ARG, 3: MYPY_ARG},
            ["mypy:4", "pyright:1", "pyright:4"],
        ),
        (
            {1: ARG | {"reportUndefinedVariable"}, 3: ARG},
            {1: MYPY_ARG, 3: MYPY_ARG},
            ["mypy:4", "pyright:1", "pyright:4"],
        ),
        (
            {1: ARG, 3: ARG},
            {1: MYPY_ARG, 2: MYPY_ARG, 3: MYPY_ARG},
            ["mypy:2", "mypy:4", "pyright:4"],
        ),
    ],
    ids=[
        "both-agree-codeless-marker-reported",
        "pyright-misses-one",
        "wrong-reason",
        "extra-unexpected-code",
        "error-on-unmarked-line",
    ],
)
def test_fail_files_need_the_named_error_from_both_checkers(pyright, mypy, expected):
    # when
    problems = judged(FAIL, FAIL_SOURCE, pyright, mypy)
    # then
    assert problems == expected


def test_pass_files_ignore_markers_and_reject_every_error():
    # when
    problems = judged(PASS, FAIL_SOURCE, {3: ARG}, {})
    # then
    assert problems == ["pyright:3"]
