import pytest

from tools.freethreaded import (
    COUNTER_TEST,
    Collected,
    Interpreter,
    Report,
    Run,
    Warned,
    control_problems,
    counter_outcomes,
    forced_gil,
    problems_after,
    problems_before,
)

CASE = f"{COUNTER_TEST}::test_itertools_count_hands_out_unique_values_to_concurrent_threads[1]"
CASE_2 = f"{COUNTER_TEST}::test_itertools_count_hands_out_unique_values_to_concurrent_threads[2]"
COUNTER = Collected(CASE, single_threaded=False, thread_unsafe_reason=None)
COUNTER_2 = Collected(CASE_2, single_threaded=False, thread_unsafe_reason=None)
OTHER = "tests/unit/core/test_errors.py::test_x"
PASSED = [Report(CASE, "setup", "passed"), Report(CASE, "call", "passed")]
RE_ENABLED = (
    "the GIL was re-enabled during the run: an extension module without Py_mod_gil was "
    "imported (see the RuntimeWarning above)"
)


@pytest.mark.parametrize(
    ("environ", "xoptions", "expected"),
    [
        ({}, {}, None),
        ({"PYTHON_GIL": "0"}, {}, "PYTHON_GIL=0"),
        ({}, {"gil": "1"}, "-X gil=1"),
        ({"PYTHON_GIL": "0"}, {"gil": "1"}, "PYTHON_GIL=0, -X gil=1"),
        ({"PYTHONPATH": "."}, {"dev": True}, None),
    ],
    ids=["unset", "env", "x-option", "both", "unrelated"],
)
def test_gil_settings_are_read_from_python_gil_and_x_gil(environ, xoptions, expected):
    # when
    setting = forced_gil(environ, xoptions)
    # then
    assert setting == expected


@pytest.mark.parametrize(
    ("interpreter", "expected"),
    [
        (Interpreter(free_threaded_build=True, gil_enabled=False, forced_gil=None), []),
        (
            Interpreter(free_threaded_build=False, gil_enabled=True, forced_gil=None),
            ["not a free-threaded build (use python3.14t)"],
        ),
        (
            Interpreter(free_threaded_build=True, gil_enabled=True, forced_gil=None),
            ["the GIL is enabled before the run"],
        ),
        (
            Interpreter(free_threaded_build=True, gil_enabled=False, forced_gil="PYTHON_GIL=0"),
            ["PYTHON_GIL=0 is set; unset it so a module re-enabling the GIL is seen"],
        ),
        (
            Interpreter(free_threaded_build=True, gil_enabled=True, forced_gil="-X gil=1"),
            [
                "-X gil=1 is set; unset it so a module re-enabling the GIL is seen",
                "the GIL is enabled before the run",
            ],
        ),
    ],
    ids=["gil-off", "gil-build", "gil-on", "gil-forced-off", "gil-forced-on"],
)
def test_run_starts_only_on_a_free_threaded_build_with_the_gil_off_by_itself(interpreter, expected):
    # when
    problems = problems_before(interpreter, ["error"])
    # then
    assert problems == expected


@pytest.mark.parametrize(
    ("filterwarnings", "expected"),
    [
        (["error"], []),
        (
            ["error", "ignore::DeprecationWarning"],
            [
                "filterwarnings is ['error', 'ignore::DeprecationWarning'], expected ['error']: "
                "this run replaces it with -W always and fails on any recorded warning; update "
                "tools/freethreaded.py first"
            ],
        ),
        (
            [],
            [
                "filterwarnings is [], expected ['error']: this run replaces it with -W always "
                "and fails on any recorded warning; update tools/freethreaded.py first"
            ],
        ),
    ],
    ids=["error-only", "with-ignore", "unset"],
)
def test_run_starts_only_while_every_warning_is_an_error(filterwarnings, expected):
    # given
    interpreter = Interpreter(free_threaded_build=True, gil_enabled=False, forced_gil=None)
    # when
    problems = problems_before(interpreter, filterwarnings)
    # then
    assert problems == expected


@pytest.mark.parametrize(
    ("collected", "reports", "expected"),
    [
        ([COUNTER], PASSED, {CASE: "passed"}),
        ([COUNTER], [], {CASE: "not run"}),
        ([COUNTER], [Report(CASE, "setup", "passed")], {CASE: "not run"}),
        ([COUNTER], [Report(CASE, "setup", "skipped")], {CASE: "skipped"}),
        ([COUNTER], [Report(CASE, "call", "skipped")], {CASE: "skipped"}),
        ([COUNTER], [Report(CASE, "call", "failed")], {CASE: "failed"}),
        ([COUNTER], [*PASSED, Report(CASE, "teardown", "failed")], {CASE: "failed"}),
        (
            [COUNTER],
            [Report(CASE, "setup", "failed"), Report(CASE, "teardown", "passed")],
            {CASE: "failed"},
        ),
        (
            [COUNTER, Collected(OTHER, False, None)],
            [*PASSED, Report(OTHER, "call", "failed")],
            {CASE: "passed"},
        ),
        ([Collected(f"{COUNTER_TEST}.bak::test_x", False, None)], [], {}),
        ([], PASSED, {}),
    ],
    ids=[
        "passed",
        "never-reported",
        "setup-only",
        "setup-skipped",
        "call-skipped-or-xfail",
        "call-failed",
        "teardown-failed-after-pass",
        "failure-is-not-overwritten",
        "other-module-ignored",
        "exact-module-only",
        "deselected",
    ],
)
def test_counter_case_outcome_is_its_first_failure_or_skip_else_its_call(
    collected, reports, expected
):
    # when
    outcomes = counter_outcomes(collected, reports)
    # then
    assert outcomes == expected


@pytest.mark.parametrize(
    ("run", "expected"),
    [
        (Run(False, "8", [COUNTER], PASSED, []), []),
        (Run(True, "8", [COUNTER], PASSED, []), [RE_ENABLED]),
        (
            Run(False, "1", [COUNTER], PASSED, []),
            ["--parallel-threads is 1, expected a number of at least 2"],
        ),
        (
            Run(False, None, [COUNTER], PASSED, []),
            ["--parallel-threads is None, expected a number of at least 2"],
        ),
        (
            Run(False, "auto", [COUNTER], PASSED, []),
            ["--parallel-threads is auto, expected a number of at least 2"],
        ),
        (
            Run(False, "8", [COUNTER, Collected(OTHER, True, None)], PASSED, []),
            [f"{OTHER} ran on one thread without @pytest.mark.thread_unsafe(reason=...)"],
        ),
        (Run(False, "8", [COUNTER, Collected(OTHER, True, "uses monkeypatch")], PASSED, []), []),
        (
            Run(False, "8", [COUNTER], PASSED, [Warned(OTHER, "DeprecationWarning", "x")] * 8),
            [f"warning recorded: {OTHER}: DeprecationWarning: x"],
        ),
        (
            Run(
                False,
                "8",
                [COUNTER],
                PASSED,
                [
                    Warned(OTHER, "PytestUnhandledThreadExceptionWarning", "in Thread-17"),
                    Warned(OTHER, "PytestUnhandledThreadExceptionWarning", "in Thread-18"),
                    Warned(OTHER, "DeprecationWarning", "y"),
                    Warned(CASE, "PytestUnhandledThreadExceptionWarning", "in Thread-19"),
                ],
            ),
            [
                f"warning recorded: {OTHER}: PytestUnhandledThreadExceptionWarning: in Thread-17",
                f"warning recorded: {OTHER}: DeprecationWarning: y",
                f"warning recorded: {CASE}: PytestUnhandledThreadExceptionWarning: in Thread-19",
            ],
        ),
        (
            Run(False, "8", [COUNTER], PASSED, [], skip_thread_unsafe=True),
            ["--skip-thread-unsafe turns thread-unsafe tests into skips; drop it"],
        ),
        (
            Run(False, "8", [], [], []),
            [f"{COUNTER_TEST} was not collected (or was deselected)"],
        ),
        (
            Run(False, "8", [COUNTER], [Report(CASE, "setup", "skipped")], []),
            [f"{CASE} skipped, expected passed"],
        ),
        (
            Run(True, "8", [COUNTER_2, COUNTER], [Report(CASE_2, "call", "failed")], []),
            [
                RE_ENABLED,
                f"{CASE} not run, expected passed",
                f"{CASE_2} failed, expected passed",
            ],
        ),
    ],
    ids=[
        "clean",
        "gil-re-enabled",
        "one-thread",
        "no-plugin",
        "auto-threads",
        "silently-single-threaded",
        "single-threaded-with-reason",
        "warning-once-per-test",
        "warning-once-per-test-and-category",
        "skip-thread-unsafe",
        "counter-missing",
        "counter-skipped",
        "several-problems-in-order",
    ],
)
def test_run_passes_only_with_the_gil_off_threads_used_and_every_counter_case_passed(run, expected):
    # when
    problems = problems_after(run)
    # then
    assert problems == expected


@pytest.mark.parametrize(
    ("duplicates", "expected"),
    [
        (523_118, []),
        (1, []),
        (
            0,
            [
                "the read-modify-write control counter gave 0 duplicates: the threads did not "
                f"race on this machine, so {COUNTER_TEST} passing proves nothing"
            ],
        ),
    ],
    ids=["raced", "barely-raced", "no-race"],
)
def test_counter_test_counts_only_when_the_unsafe_control_counter_raced(duplicates, expected):
    # when
    problems = control_problems(duplicates)
    # then
    assert problems == expected
