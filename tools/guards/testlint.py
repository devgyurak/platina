"""Test-style guard: Given/When/Then structure and zero control flow in test modules.

Applies to ``tests/**/test_*.py``. ``tests/support/**`` and ``conftest.py`` are exempt: that is
where loops, branches and other helper logic belong.

Codes
    T101  control flow / comprehension in a test module
    T201  missing ``# when`` marker
    T202  missing ``# then`` marker
    T203  markers out of order (given -> when -> then)
    T204  duplicated marker
    T205  statements before ``# when`` without a ``# given`` marker
    T206  no assertion after ``# then``
    T301  sleeping in a test (any call whose last name is ``sleep``: time, asyncio, anyio, trio)
"""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import PurePosixPath

from tools.guards.core import Violation, parse

_BANNED: dict[type[ast.AST], str] = {
    ast.For: "for", ast.AsyncFor: "async for", ast.While: "while", ast.If: "if",
    ast.IfExp: "conditional expression", ast.Match: "match", ast.Try: "try",
    ast.TryStar: "try/except*", ast.ListComp: "list comprehension",
    ast.SetComp: "set comprehension", ast.DictComp: "dict comprehension",
    ast.GeneratorExp: "generator expression",
}  # fmt: skip
_MARKER = re.compile(r"^#\s*(given|when\s*/\s*then|when|then)\b\s*(?::.*)?$", re.IGNORECASE)
_ASSERT_CALL = re.compile(r"^(assert|raises|warns)")


def applies_to(path: str) -> bool:
    p = PurePosixPath(path)
    return (
        p.parts[:1] == ("tests",)
        and "support" not in p.parts
        and p.suffix == ".py"
        and (p.name.startswith("test_") or p.stem.endswith("_test"))
    )


def check(path: str, source: str) -> list[Violation]:
    tree = parse(source, path)
    if isinstance(tree, Violation):
        return [tree]
    markers = _markers(source)
    violations = [
        Violation(
            path, node.lineno, "T101",
            f"`{_BANNED[type(node)]}` is forbidden in tests - use pytest.mark.parametrize, "
            "fixtures, or move the logic into tests/support/",
        )
        for node in ast.walk(tree)
        if type(node) in _BANNED and isinstance(node, ast.stmt | ast.expr)
    ]  # fmt: skip
    violations += [v for fn in _test_functions(tree) for v in _check_gwt(path, fn, markers)]
    violations += [
        Violation(path, node.lineno, "T301", "sleeping in tests is forbidden - await a condition")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and _dotted(node.func).rsplit(".", 1)[-1] == "sleep"
    ]
    return violations


def _markers(source: str) -> dict[int, str]:
    found: dict[int, str] = {}
    for tok in tokenize.generate_tokens(io.StringIO(source).readline):
        if tok.type == tokenize.COMMENT and (m := _MARKER.match(tok.string.strip())):
            found[tok.start[0]] = re.sub(r"\s+", "", m.group(1).lower())
    return found


def _test_functions(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    funcs: list[ast.FunctionDef | ast.AsyncFunctionDef] = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.startswith("Test"):
            funcs += [n for n in node.body if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)]
        elif isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            funcs.append(node)
    return [f for f in funcs if f.name.startswith("test")]


def _check_gwt(
    path: str, fn: ast.FunctionDef | ast.AsyncFunctionDef, markers: dict[int, str]
) -> list[Violation]:
    # From the `def` line: a `# given` may be followed by a blank line or an explanatory comment.
    start, end = fn.lineno, fn.end_lineno or fn.lineno
    own = sorted((line, kind) for line, kind in markers.items() if start <= line <= end)
    kinds = [k for _, k in own]
    out: list[Violation] = []

    def err(code: str, msg: str, line: int = fn.lineno) -> None:
        out.append(Violation(path, line, code, f"{fn.name}: {msg}"))

    for kind in {"given", "when", "then", "when/then"}:
        if kinds.count(kind) > 1:
            err("T204", f"`# {kind}` appears more than once - one behaviour per test")
    combined = "when/then" in kinds
    when_line = next((ln for ln, k in own if k in {"when", "when/then"}), None)
    then_line = next((ln for ln, k in own if k in {"then", "when/then"}), None)
    given_line = next((ln for ln, k in own if k == "given"), None)
    if when_line is None:
        err("T201", "missing `# when` (or `# when / then`) marker")
    if then_line is None and not combined:
        err("T202", "missing `# then` marker")
    order = [k if k != "when/then" else "when" for k in kinds]
    expected = [k for k in ("given", "when", "then") if k in order]
    if order != expected and len(set(order)) == len(order):
        err("T203", f"markers must appear in given -> when -> then order, got {' -> '.join(kinds)}")
    body = [s for s in fn.body if not _is_docstring(s)]
    first_stmt = body[0].lineno if body else None
    if (
        when_line
        and first_stmt
        and first_stmt < when_line
        and (given_line is None or given_line > first_stmt)
    ):
        err("T205", "statements before `# when` must sit under a `# given` marker", first_stmt)
    if then_line is not None and not _has_assertion_after(fn, then_line):
        err(
            "T206",
            "no assertion (assert / pytest.raises / assert_* helper) after `# then`",
            then_line,
        )
    return out


def _is_docstring(stmt: ast.stmt) -> bool:
    return (
        isinstance(stmt, ast.Expr)
        and isinstance(stmt.value, ast.Constant)
        and isinstance(stmt.value.value, str)
    )


def _has_assertion_after(fn: ast.AST, line: int) -> bool:
    for node in ast.walk(fn):
        if getattr(node, "lineno", 0) < line:
            continue
        if isinstance(node, ast.Assert):
            return True
        if isinstance(node, ast.Call) and _ASSERT_CALL.match(_dotted(node.func).rsplit(".", 1)[-1]):
            return True
    return False


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""
