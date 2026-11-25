"""Shared types and helpers for the guard checkers."""

from __future__ import annotations

import ast
import subprocess
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True, order=True)
class Violation:
    path: str
    line: int
    code: str
    message: str

    def render(self) -> str:
        return f"{self.path}:{self.line}: {self.code} {self.message}"


def rel(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def parse(source: str, path: str) -> ast.Module | Violation:
    try:
        return ast.parse(source, filename=path)
    except SyntaxError as exc:
        return Violation(path, exc.lineno or 1, "G001", f"syntax error: {exc.msg}")


def repo_files() -> list[Path]:
    """Tracked + untracked (not ignored) files."""
    out = subprocess.run(
        ["git", "ls-files", "-co", "--exclude-standard"],
        cwd=ROOT, capture_output=True, text=True, check=True,
    ).stdout  # fmt: skip
    return [ROOT / line for line in out.splitlines() if (ROOT / line).is_file()]


def changed_files() -> list[Path]:
    """Files modified relative to HEAD plus untracked files (works before the first commit)."""
    has_head = (
        subprocess.run(
            ["git", "rev-parse", "--verify", "-q", "HEAD"], cwd=ROOT, capture_output=True
        ).returncode
        == 0
    )
    diff_cmd = ["git", "diff", "--name-only", "HEAD"] if has_head else ["git", "ls-files"]
    names = set(subprocess.run(diff_cmd, cwd=ROOT, capture_output=True, text=True).stdout.split())
    names |= set(
        subprocess.run(
            ["git", "ls-files", "-o", "--exclude-standard"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        ).stdout.split()
    )
    return sorted(ROOT / n for n in names if (ROOT / n).is_file())
