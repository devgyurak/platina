"""Type tests: the public API must type-check the same way under pyright *and* mypy.

    tests/typing/pass_*.py   both checkers report no error
    tests/typing/fail_*.py   every misuse line ends with
                                 # expect-error[<pyright rule>, <mypy code>]: <why>
                             e.g. ``# expect-error[reportArgumentType, arg-type]: UUID is not Order``.
                             Each checker must report at least one error on that line, every error it
                             reports there must carry one of the listed codes for that checker, and no
                             unmarked line may have an error.

    uv run python -m tools.typetests              # every file under tests/typing
    uv run python -m tools.typetests FILE [...]   # selected files (also outside tests/typing, e.g. spikes/)

Codes starting with ``report`` are pyright rules, the others mypy error codes; list several per
checker when either is acceptable. Pinning the code is what makes a "type error" mean the right
type error: a misspelled name on the line would otherwise pass (design doc section 11.8).
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TYPING_DIR = ROOT / "tests" / "typing"
_MARKER = re.compile(r"#\s*expect-error(?:\[(?P<codes>[^\]]*)\])?")
_MYPY_LINE = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+):(?:\d+:)? error: (?P<message>.*?)(?:\s+\[(?P<code>[a-z0-9-]+)\])?$"
)
NO_CODE = "<none>"

# path -> line -> codes reported on that line
ErrorMap = dict[str, dict[int, set[str]]]


@dataclass(frozen=True)
class Problem:
    path: str
    line: int
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.message}"


@dataclass(frozen=True)
class Expectation:
    """Codes a marked line expects, per checker (empty set = the marker named none)."""

    pyright: frozenset[str]
    mypy: frozenset[str]

    def codes(self, checker: str) -> frozenset[str]:
        return self.pyright if checker == "pyright" else self.mypy


def expectations(source: str) -> dict[int, Expectation]:
    """1-based line -> expected codes, for every line with an ``# expect-error`` marker."""
    found: dict[int, Expectation] = {}
    for n, text in enumerate(source.splitlines(), 1):
        if m := _MARKER.search(text):
            codes = [c.strip() for c in (m.group("codes") or "").split(",") if c.strip()]
            found[n] = Expectation(
                pyright=frozenset(c for c in codes if c.startswith("report")),
                mypy=frozenset(c for c in codes if not c.startswith("report")),
            )
    return found


def parse_pyright(output: str) -> ErrorMap:
    """Errors per repo-relative path and line from ``pyright --outputjson``."""
    errors: ErrorMap = defaultdict(lambda: defaultdict(set))
    for diag in json.loads(output or "{}").get("generalDiagnostics", []):
        if diag.get("severity") == "error":
            line = diag["range"]["start"]["line"] + 1
            errors[_relative(diag["file"])][line].add(diag.get("rule") or NO_CODE)
    return _plain(errors)


def parse_mypy(output: str) -> ErrorMap:
    """Errors per repo-relative path and line from mypy's default text output."""
    errors: ErrorMap = defaultdict(lambda: defaultdict(set))
    for line in output.splitlines():
        if m := _MYPY_LINE.match(line.strip()):
            errors[_relative(m.group("path"))][int(m.group("line"))].add(m.group("code") or NO_CODE)
    return _plain(errors)


def judge(path: str, source: str, by_checker: dict[str, ErrorMap]) -> list[Problem]:
    """Compare what each checker reported for ``path`` with what the file expects."""
    expected = expectations(source) if Path(path).name.startswith("fail_") else {}
    problems: list[Problem] = []
    for checker in sorted(by_checker):
        got = by_checker[checker].get(path, {})
        for line in sorted(set(expected) | set(got)):
            problems += _judge_line(path, line, checker, expected.get(line), got.get(line, set()))
    return problems


def _judge_line(
    path: str, line: int, checker: str, expectation: Expectation | None, codes: set[str]
) -> list[Problem]:
    if expectation is None:
        listed = ", ".join(sorted(codes))
        return [Problem(path, line, f"{checker}: unexpected type error [{listed}]")]
    wanted = expectation.codes(checker)
    if not wanted:
        return [
            Problem(
                path, line,
                f"{checker}: the marker names no {checker} code - write "
                "`# expect-error[<pyright rule>, <mypy code>]`",
            )
        ]  # fmt: skip
    if not codes:
        return [Problem(path, line, f"{checker}: expected [{', '.join(sorted(wanted))}], got none")]
    if stray := sorted(codes - wanted):
        return [
            Problem(
                path, line,
                f"{checker}: error [{', '.join(stray)}] is not the expected "
                f"[{', '.join(sorted(wanted))}] - the line fails for another reason",
            )
        ]  # fmt: skip
    return []


def run_checkers(paths: list[str]) -> dict[str, ErrorMap]:
    pyright = subprocess.run(
        [sys.executable, "-m", "pyright", "--outputjson", *paths],
        cwd=ROOT, capture_output=True, text=True,
    )  # fmt: skip
    mypy = subprocess.run(
        [sys.executable, "-m", "mypy", "--strict", "--show-error-codes", "--no-error-summary",
         "--no-color-output", "--hide-error-context", "--no-incremental", *paths],
        cwd=ROOT, capture_output=True, text=True,
    )  # fmt: skip
    if pyright.returncode not in (0, 1) or not pyright.stdout.strip().startswith("{"):
        raise SystemExit(f"pyright did not run:\n{pyright.stdout}\n{pyright.stderr}")
    if mypy.returncode not in (0, 1):
        raise SystemExit(f"mypy did not run:\n{mypy.stdout}\n{mypy.stderr}")
    return {"pyright": parse_pyright(pyright.stdout), "mypy": parse_mypy(mypy.stdout)}


def _plain(errors: ErrorMap) -> ErrorMap:
    return {path: dict(lines) for path, lines in errors.items()}


def _relative(raw: str) -> str:
    path = Path(raw)
    path = path if path.is_absolute() else ROOT / path
    resolved = path.resolve()
    return resolved.relative_to(ROOT).as_posix() if resolved.is_relative_to(ROOT) else raw


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.typetests",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="*", type=Path)
    args = parser.parse_args(argv)
    files = args.paths or sorted(
        p for p in TYPING_DIR.glob("*.py") if p.name.startswith(("pass_", "fail_"))
    )
    paths = [_relative(str(p)) for p in files]
    if not paths:
        print("typetests: no pass_*/fail_* files under tests/typing yet", file=sys.stderr)
        return 0
    by_checker = run_checkers(paths)
    problems = [
        problem for path in paths for problem in judge(path, (ROOT / path).read_text(), by_checker)
    ]
    for problem in problems:
        print(problem.render(), file=sys.stderr)
    print(f"typetests: {len(problems)} problem(s) in {len(paths)} file(s)", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
