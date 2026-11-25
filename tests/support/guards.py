"""Helpers for testing tools/guards and tools/typetests."""

from __future__ import annotations

import json
import textwrap
from collections.abc import Mapping

from tools import typetests
from tools.guards import archlint, langlint, testlint
from tools.hooks import agent_hook


def lint_test_module(source: str, path: str = "tests/unit/test_sample.py") -> list[str]:
    return sorted(v.code for v in testlint.check(path, textwrap.dedent(source)))


def lint_src_module(source: str, path: str = "src/platina/cli/sample.py") -> list[str]:
    return sorted(v.code for v in archlint.check(path, textwrap.dedent(source)))


def lint_language(source: str, path: str = "src/platina/sample.py") -> list[str]:
    return sorted(v.code for v in langlint.check(path, textwrap.dedent(source)))


def pyright_json(*errors: tuple[str, int, str], warnings: tuple[tuple[str, int], ...] = ()) -> str:
    """A minimal ``pyright --outputjson`` payload: errors as (file, 1-based line, rule)."""
    diags = [
        {"file": path, "severity": "error", "rule": rule, "range": {"start": {"line": line - 1}}}
        for path, line, rule in errors
    ] + [
        {"file": path, "severity": "warning", "range": {"start": {"line": line - 1}}}
        for path, line in warnings
    ]
    return json.dumps({"generalDiagnostics": diags})


def judged(
    path: str, source: str, pyright: dict[int, set[str]], mypy: dict[int, set[str]]
) -> list[str]:
    """``checker:line`` for every problem ``typetests.judge`` reports."""
    problems = typetests.judge(
        path, textwrap.dedent(source), {"pyright": {path: pyright}, "mypy": {path: mypy}}
    )
    return sorted(f"{p.message.split(':', 1)[0]}:{p.line}" for p in problems)


def hook_paths(tool_input: Mapping[str, object]) -> list[str]:
    return agent_hook.extract_paths(tool_input)


def stamped_translation(source: str, body: str, *, source_sha: str, own_sha: str) -> str:
    """A translation text with an i18n header carrying the given hashes."""
    header = (
        f"<!-- i18n: source={source} source-sha256={source_sha} translation-sha256={own_sha} -->"
    )
    return f"{header}\n{body}"
