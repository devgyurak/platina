"""Unit tests on free-threaded CPython with the GIL off (design section 11.10, ADR-0002).

    make test-unit-ft                                   # what CI runs, in its own .venv-ft
    uv run python -m tools.freethreaded [PYTEST_ARG...]  # on an interpreter you already have

Runs pytest in this process (each test on several threads at once with pytest-run-parallel,
``--parallel-threads N`` in the arguments) and fails, besides on a test failure, when:

- the interpreter is not a free-threaded build, or the GIL is on before the run;
- ``PYTHON_GIL`` or ``-X gil`` is set: forcing the GIL off would hide an extension module that
  switches it back on;
- the GIL is on after the run: importing an extension module without ``Py_mod_gil`` (from a test
  or from a dependency, also during collection) re-enables it for the whole process and CPython
  only warns;
- fewer than 2 threads per test were asked for, or a test ran on one thread without an explicit
  ``@pytest.mark.thread_unsafe(reason=...)``: the plugin silently runs tests it considers unsafe
  (``monkeypatch``, ``capsys``, ``pytest.warns``, ...) on one thread;
- a warning was recorded. The plugin's worker threads swallow every ``Warning`` exception, so
  under the project's ``filterwarnings = ["error"]`` a warning would end the test body early and
  still report it as passed. This run appends ``-W always`` so warnings are recorded instead, and
  any recorded warning fails it - the same policy without the swallow. That holds only while the
  project's ``filterwarnings`` is exactly ``["error"]`` (an ``ignore`` entry would be overridden),
  so the run refuses to start otherwise; for an expected warning use ``pytest.warns``;
- ``--skip-thread-unsafe`` was passed: it turns thread-unsafe tests into skips;
- ADR-0002's counter test (``tests/unit/test_fallback_id_counter.py``) was not collected, or a
  collected case did not pass (skipped and xfail count as not passed): on a GIL build that test
  passes trivially, so it is a real check only here. Deselecting it with ``PYTEST_ARGS`` fails the
  run, so local runs pass the whole of ``tests/unit``.

After pytest, the run draws from an unsafe read-modify-write counter (``n += 1``) on several
threads at once, in this process, and logs how many draws repeated: the control for the counter
test. It fails the run when that count is 0, because then the threads did not race on this machine
and the counter test passing proves nothing.

The checks are a CI step rather than a test, so the suite itself still passes on GIL builds.
"""

from __future__ import annotations

import os
import sys
import sysconfig
import tomllib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import NamedTuple, Protocol

import pytest

from tools.concurrent_draws import duplicate_draws, read_modify_write_counter

COUNTER_TEST = "tests/unit/test_fallback_id_counter.py"
# the same shape as the counter test (which runs on one pytest thread, bringing its own 8), so
# the control speaks for it
CONTROL_THREADS = 8
CONTROL_DRAWS = 200_000
PYPROJECT = Path(__file__).resolve().parents[1] / "pyproject.toml"


@dataclass(frozen=True, slots=True)
class Interpreter:
    free_threaded_build: bool
    gil_enabled: bool
    forced_gil: str | None


class Collected(NamedTuple):
    nodeid: str
    single_threaded: bool
    thread_unsafe_reason: str | None


class Report(NamedTuple):
    nodeid: str
    when: str
    outcome: str


class _WarningMessage(Protocol):
    """The fields of ``warnings.WarningMessage`` that pytest passes to the hook."""

    @property
    def message(self) -> Warning | str: ...
    @property
    def category(self) -> type[Warning]: ...
    @property
    def filename(self) -> str: ...
    @property
    def lineno(self) -> int: ...


class Warned(NamedTuple):
    where: str
    category: str
    message: str


@dataclass(frozen=True, slots=True)
class Run:
    gil_enabled: bool
    threads: str | None
    collected: Sequence[Collected]
    reports: Sequence[Report]
    warnings: Sequence[Warned]
    skip_thread_unsafe: bool = False


def forced_gil(environ: Mapping[str, str], xoptions: Mapping[str, object]) -> str | None:
    settings: list[str] = []
    if "PYTHON_GIL" in environ:
        settings.append(f"PYTHON_GIL={environ['PYTHON_GIL']}")
    if "gil" in xoptions:
        settings.append(f"-X gil={xoptions['gil']}")
    return ", ".join(settings) or None


def current_interpreter() -> Interpreter:
    return Interpreter(
        free_threaded_build=bool(sysconfig.get_config_var("Py_GIL_DISABLED")),
        gil_enabled=sys._is_gil_enabled(),
        forced_gil=forced_gil(os.environ, sys._xoptions),
    )


def problems_before(interpreter: Interpreter, filterwarnings: Sequence[str]) -> list[str]:
    problems: list[str] = []
    if list(filterwarnings) != ["error"]:
        problems.append(
            f"filterwarnings is {list(filterwarnings)}, expected ['error']: this run replaces it "
            "with -W always and fails on any recorded warning; update tools/freethreaded.py first"
        )
    if not interpreter.free_threaded_build:
        problems.append("not a free-threaded build (use python3.14t)")
    if interpreter.forced_gil is not None:
        problems.append(
            f"{interpreter.forced_gil} is set; unset it so a module re-enabling the GIL is seen"
        )
    if interpreter.free_threaded_build and interpreter.gil_enabled:
        problems.append("the GIL is enabled before the run")
    return problems


def counter_outcomes(collected: Sequence[Collected], reports: Sequence[Report]) -> dict[str, str]:
    """Final outcome of every collected case of ``COUNTER_TEST``: a failure or skip in any phase
    wins, otherwise a passing call phase makes it ``passed``, otherwise ``not run``."""
    outcomes = {item.nodeid: "not run" for item in collected if _is_counter(item.nodeid)}
    for report in reports:
        if report.nodeid not in outcomes or outcomes[report.nodeid] in ("failed", "skipped"):
            continue
        if report.outcome in ("failed", "skipped"):
            outcomes[report.nodeid] = report.outcome
        elif report.when == "call":
            outcomes[report.nodeid] = "passed"
    return outcomes


def control_problems(duplicates: int) -> list[str]:
    if duplicates > 0:
        return []
    return [
        "the read-modify-write control counter gave 0 duplicates: the threads did not race on "
        f"this machine, so {COUNTER_TEST} passing proves nothing"
    ]


def problems_after(run: Run) -> list[str]:
    problems: list[str] = []
    if run.gil_enabled:
        problems.append(
            "the GIL was re-enabled during the run: an extension module without Py_mod_gil was "
            "imported (see the RuntimeWarning above)"
        )
    if run.threads is None or not run.threads.isdigit() or int(run.threads) < 2:
        problems.append(f"--parallel-threads is {run.threads}, expected a number of at least 2")
    if run.skip_thread_unsafe:
        problems.append("--skip-thread-unsafe turns thread-unsafe tests into skips; drop it")
    problems += [
        f"{item.nodeid} ran on one thread without @pytest.mark.thread_unsafe(reason=...)"
        for item in run.collected
        if item.single_threaded and not item.thread_unsafe_reason
    ]
    # one test on N threads records its warning N times, the text often naming the thread
    first: dict[tuple[str, str], str] = {}
    for warning in run.warnings:
        first.setdefault((warning.where, warning.category), warning.message)
    problems += [
        f"warning recorded: {where}: {category}: {message}"
        for (where, category), message in first.items()
    ]
    counter = counter_outcomes(run.collected, run.reports)
    if not counter:
        problems.append(f"{COUNTER_TEST} was not collected (or was deselected)")
    problems += [
        f"{nodeid} {outcome}, expected passed"
        for nodeid, outcome in sorted(counter.items())
        if outcome != "passed"
    ]
    return problems


def _is_counter(nodeid: str) -> bool:
    return nodeid.split("::", 1)[0] == COUNTER_TEST


@dataclass(slots=True)
class Recorder:
    """pytest plugin: records what ``problems_after`` judges."""

    threads: str | None = None
    collected: list[Collected] = field(default_factory=list[Collected])
    reports: list[Report] = field(default_factory=list[Report])
    warnings: list[Warned] = field(default_factory=list[Warned])
    skip_thread_unsafe: bool = False

    @pytest.hookimpl(trylast=True)  # after pytest-run-parallel has marked single-threaded tests
    def pytest_collection_finish(self, session: pytest.Session) -> None:
        threads = session.config.getoption("parallel_threads", default=None)
        self.threads = None if threads is None else str(threads)
        self.skip_thread_unsafe = bool(
            session.config.getoption("skip_thread_unsafe", default=False)
        )
        self.collected = [_collected(item) for item in session.items]

    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        self.reports.append(Report(report.nodeid, report.when, report.outcome))

    def pytest_warning_recorded(self, warning_message: _WarningMessage, nodeid: str) -> None:
        where = nodeid or f"{warning_message.filename}:{warning_message.lineno}"
        message = str(warning_message.message).splitlines()[0]
        self.warnings.append(Warned(where, warning_message.category.__name__, message))

    def run(self, *, gil_enabled: bool) -> Run:
        return Run(
            gil_enabled,
            self.threads,
            self.collected,
            self.reports,
            self.warnings,
            self.skip_thread_unsafe,
        )


def _collected(item: pytest.Item) -> Collected:
    threads = item.get_closest_marker("parallel_threads")
    unsafe = item.get_closest_marker("thread_unsafe")
    return Collected(
        nodeid=item.nodeid,
        single_threaded=threads is not None and str(threads.args[0]) == "1",
        thread_unsafe_reason=None if unsafe is None else unsafe.kwargs.get("reason"),
    )


def main(argv: list[str]) -> int:
    before = current_interpreter()
    print(f"free-threaded check: {sys.version}")
    print(
        f"free-threaded check: Py_GIL_DISABLED={int(before.free_threaded_build)}, "
        f"GIL enabled before the run: {before.gil_enabled}"
    )
    pytest_options = tomllib.loads(PYPROJECT.read_text())["tool"]["pytest"]["ini_options"]
    problems = problems_before(before, pytest_options.get("filterwarnings", []))
    if problems:
        return _fail(problems)

    recorder = Recorder()
    exit_code = pytest.main([*argv, "-W", "always"], plugins=[recorder])

    control = duplicate_draws(read_modify_write_counter, CONTROL_THREADS, CONTROL_DRAWS)
    print(
        f"free-threaded check: control, read-modify-write counter, {CONTROL_THREADS} threads x "
        f"{CONTROL_DRAWS} draws on {os.process_cpu_count()} CPUs: {control} duplicates"
    )
    run = recorder.run(gil_enabled=sys._is_gil_enabled())
    print(f"free-threaded check: GIL enabled after the run: {run.gil_enabled}")
    serial = sum(item.single_threaded for item in run.collected)
    print(
        f"free-threaded check: {len(run.collected)} tests, {run.threads} threads each except "
        f"{serial} marked thread_unsafe"
    )
    for nodeid, outcome in sorted(counter_outcomes(run.collected, run.reports).items()):
        print(f"free-threaded check: {nodeid} {outcome}")
    problems = problems_after(run) + control_problems(control)
    if problems:
        return _fail(problems)
    return int(exit_code)


def _fail(problems: list[str]) -> int:
    for problem in problems:
        print(f"free-threaded check FAILED: {problem}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
