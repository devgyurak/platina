"""CLI entry point.

python -m tools.guards                 # full scan (all tracked + untracked files)
python -m tools.guards --changed       # files changed vs HEAD (+ untracked)
python -m tools.guards PATH [PATH...]  # specific files
python -m tools.guards i18n-stamp FILE # refresh a translation header after syncing it
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from tools.guards import archlint, langlint, testlint
from tools.guards.core import ROOT, Violation, changed_files, rel, repo_files


def run(paths: list[Path], *, full: bool) -> list[Violation]:
    violations: list[Violation] = []
    for path in paths:
        name = rel(path)
        if not (
            testlint.applies_to(name) or archlint.applies_to(name) or langlint.applies_to(name)
        ):
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        if testlint.applies_to(name):
            violations += testlint.check(name, text)
        if archlint.applies_to(name):
            violations += archlint.check(name, text)
        if langlint.applies_to(name):
            violations += langlint.check(name, text)
    if full:
        violations += langlint.missing_translations({rel(p) for p in paths})
    return sorted(set(violations))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["i18n-stamp"]:
        for target in argv[1:]:
            print(langlint.stamp(target))
        return 0
    parser = argparse.ArgumentParser(
        prog="python -m tools.guards",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("paths", nargs="*", type=Path)
    parser.add_argument("--changed", action="store_true", help="only files changed vs HEAD")
    args = parser.parse_args(argv)
    if args.paths:
        paths = [(p if p.is_absolute() else Path.cwd() / p) for p in args.paths]
        paths = [p for p in paths if p.is_file() and p.resolve().is_relative_to(ROOT)]
        full = False
    elif args.changed:
        paths, full = changed_files(), False
    else:
        paths, full = repo_files(), True
    violations = run(paths, full=full)
    for v in violations:
        print(v.render(), file=sys.stderr)
    scope = "full scan" if full else f"{len(paths)} file(s)"
    print(f"guards: {len(violations)} violation(s) ({scope})", file=sys.stderr)
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
