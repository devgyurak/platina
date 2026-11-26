"""Architecture guard for ``src/platina``.

import-linter (``[tool.importlinter]`` in pyproject.toml) enforces the layering *between our own
packages*. This guard covers what it does not see: which *external* modules and calls each zone
may use (design doc section 10).

Zones
    sans-I/O core   ``platina.core`` and ``platina.sql`` (functional core, design section 10.1)
    shell           every other package under ``src/platina``

Codes
    A101  module outside ``CORE_ALLOWED`` imported in the sans-I/O core (an allowlist: no I/O,
          concurrency, clock, environment, logging, file system or randomness modules)
    A102  ``psycopg`` / ``psycopg_pool`` imported outside ``platina.drivers.psycopg`` (the rest of
          ``platina.drivers`` - the contract and the SQLSTATE mapping - imports without libpq)
    A103  ``sqlalchemy`` / ``alembic`` imported outside ``platina.migrate`` (optional extra)
    A104  ``asyncio`` / ``trio`` / ``uvloop`` imported in the shell outside ``platina.drivers.psycopg``
          (write against anyio, design section 5)
    A105  ``async def`` / ``await`` / ``async for`` / ``async with`` / async comprehensions in the core
          (the engine yields commands; the runners own the event loop)
    A106  hidden clock, random-ID, console, file or dynamic-code call in the sans-I/O core:
          any call ending in ``now`` / ``utcnow`` / ``today`` / ``fromtimestamp`` /
          ``uuid1|4|6|7|8`` (aliases included), ``open()``, ``print()``, ``input()``,
          ``breakpoint()``, ``eval()``, ``exec()``, ``__import__()``; and *references* without a
          call (``default_factory=uuid.uuid7``, ``make_id = uuid.uuid4``): any ``uuidN`` name,
          and ``now`` / ``utcnow`` / ``today`` / ``fromtimestamp`` on ``datetime`` / ``date``
          (or an alias of them)

Threat model: the guard stops code written by accident (ordinary imports and calls), not
deliberate evasion (``getattr`` on modules, ``sys.modules``, strings built at run time). Those are
for architecture review (the ``arch-guardian`` sub-agent).
"""

from __future__ import annotations

import ast
from pathlib import PurePosixPath

from tools.guards.core import Violation, parse

SANS_IO = ("platina.core", "platina.sql")

# The only modules the sans-I/O core may import (A101). An allowlist, not a blocklist: the core
# needs little of the standard library, and every new entry is a deliberate decision.
# `datetime` and `uuid` are here for their *types*; their clock and random-ID calls are A106.
CORE_ALLOWED = frozenset(
    {
        "__future__", "abc", "annotationlib", "bisect", "collections", "contextlib",
        "contextvars", "copy", "dataclasses", "datetime", "decimal", "enum", "fractions",
        "functools", "graphlib", "hashlib", "heapq", "inspect", "itertools", "json", "math",
        "numbers", "operator", "re", "string", "textwrap", "types", "typing", "uuid", "weakref",
        "platina",
    }
)  # fmt: skip
DRIVER_MODULES = ("psycopg", "psycopg_pool")
SCHEMA_TOOL_MODULES = ("sqlalchemy", "alembic")
LOOP_MODULES = ("asyncio", "trio", "uvloop")

# Calls forbidden in the sans-I/O core (A106), matched on the *last* attribute name so that
# aliases (`import datetime as dt; dt.datetime.now()`, `from datetime import datetime as D;
# D.now()`) are caught too. A core method with one of these names is renamed, not exempted.
CORE_BANNED_METHODS = {
    "now": "read the clock in the shell and inject it (`Now`)",
    "utcnow": "read the clock in the shell and inject it (`Now`)",
    "today": "read the clock in the shell and inject it (`Now`)",
    "fromtimestamp": "read the clock in the shell and inject it (`Now`)",
    "uuid1": "new IDs are injected, not generated in the core (see ADR-0002)",
    "uuid4": "new IDs are injected, not generated in the core (see ADR-0002)",
    "uuid6": "new IDs are injected, not generated in the core (see ADR-0002)",
    "uuid7": "new IDs are injected, not generated in the core (see ADR-0002)",
    "uuid8": "new IDs are injected, not generated in the core (see ADR-0002)",
}
CORE_BANNED_BUILTINS = {
    "open": "file I/O",
    "print": "console I/O - report through return values or Observer plugins",
    "input": "console I/O",
    "breakpoint": "debugger left in",
    "eval": "dynamic code",
    "exec": "dynamic code",
    "__import__": "dynamic import bypasses the layer contracts",
}


def applies_to(path: str) -> bool:
    p = PurePosixPath(path)
    return p.parts[:2] == ("src", "platina") and p.suffix in {".py", ".pyi"}


def module_of(path: str) -> str:
    """``src/platina/core/engine/run.py`` -> ``platina.core.engine.run``."""
    p = PurePosixPath(path).with_suffix("")
    parts = p.parts[1:]
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


def check(path: str, source: str) -> list[Violation]:
    tree = parse(source, path)
    if isinstance(tree, Violation):
        return [tree]
    module = module_of(path)
    core = _within(module, SANS_IO)
    out: list[Violation] = []
    for line, imported in _imports(tree):
        out += _import_violations(path, line, module, imported, core=core)
    if core:
        out += _async_violations(path, tree)
        out += _call_violations(path, tree)
        out += _reference_violations(path, tree)
    return out


def _import_violations(
    path: str, line: int, module: str, imported: str, *, core: bool
) -> list[Violation]:
    top = imported.split(".", 1)[0]
    if core and top not in CORE_ALLOWED:
        return [
            Violation(
                path, line, "A101",
                f"`{imported}` in the sans-I/O core ({module}) is not on the allowlist "
                "(CORE_ALLOWED in tools/guards/archlint.py): the core does no I/O, reads no "
                "clock, environment or randomness; adding a module is the maintainer's call",
            )
        ]  # fmt: skip
    if top in DRIVER_MODULES and not _within(module, ("platina.drivers.psycopg",)):
        return [
            Violation(
                path, line, "A102",
                f"`{imported}` outside platina.drivers.psycopg - go through the driver "
                "interface (platina.drivers.interface)",
            )
        ]  # fmt: skip
    if top in SCHEMA_TOOL_MODULES and not _within(module, ("platina.migrate",)):
        return [
            Violation(
                path, line, "A103",
                f"`{imported}` outside platina.migrate - the runtime must not need the "
                "`platina[migrate]` extra",
            )
        ]  # fmt: skip
    if top in LOOP_MODULES and not _within(module, ("platina.drivers.psycopg",)):
        return [
            Violation(
                path, line, "A104",
                f"`{imported}` in src - write against anyio (asyncio is only the backend)",
            )
        ]  # fmt: skip
    return []


def _async_violations(path: str, tree: ast.Module) -> list[Violation]:
    kinds: dict[type[ast.AST], str] = {
        ast.AsyncFunctionDef: "async def", ast.Await: "await",
        ast.AsyncFor: "async for", ast.AsyncWith: "async with",
    }  # fmt: skip
    found = [(n, kinds[type(n)]) for n in ast.walk(tree) if type(n) in kinds]
    # `[x async for x in y]`: the comprehension node has no line, its parent expression has.
    found += [
        (parent, "async comprehension")
        for parent in ast.walk(tree)
        if isinstance(parent, ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp)
        and any(gen.is_async for gen in parent.generators)
    ]
    return [
        Violation(
            path, getattr(node, "lineno", 1), "A105",
            f"`{kind}` in the sans-I/O core - yield a Command and let the runner do I/O",
        )
        for node, kind in found
    ]  # fmt: skip


def _call_violations(path: str, tree: ast.Module) -> list[Violation]:
    # `from uuid import uuid4 as fresh` -> calls to `fresh()` are calls to `uuid4()`.
    aliases = {
        alias.asname: alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module in {"datetime", "uuid"}
        for alias in node.names
        if alias.asname
    }
    out: list[Violation] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id in CORE_BANNED_BUILTINS:
            reason = CORE_BANNED_BUILTINS[node.func.id]
            out.append(
                Violation(path, node.lineno, "A106", f"`{node.func.id}()` in the core: {reason}")
            )
        elif (name := aliases.get(_last_name(node.func), _last_name(node.func))) in (
            CORE_BANNED_METHODS
        ):
            out.append(
                Violation(
                    path, node.lineno, "A106",
                    f"`{_dotted(node.func) or name}()` in the core: {CORE_BANNED_METHODS[name]}",
                )
            )  # fmt: skip
    return out


_ID_FUNCTIONS = frozenset({"uuid1", "uuid4", "uuid6", "uuid7", "uuid8"})
_CLOCK_METHODS = frozenset({"now", "utcnow", "today", "fromtimestamp"})


def _reference_violations(path: str, tree: ast.Module) -> list[Violation]:
    """Clock and ID functions *referenced* without a call: ``field(default_factory=uuid.uuid7)``,
    ``field(default_factory=datetime.now)``, ``make_id = uuid.uuid4``. Calls are A106 already
    (``_call_violations``), so call targets are skipped here to report each site once."""
    called = {id(n.func) for n in ast.walk(tree) if isinstance(n, ast.Call)}
    dt_modules = {
        alias.asname or alias.name
        for n in ast.walk(tree)
        if isinstance(n, ast.Import)
        for alias in n.names
        if alias.name == "datetime"
    }
    dt_classes, id_names = set[str](), set(_ID_FUNCTIONS)
    for n in ast.walk(tree):
        if isinstance(n, ast.ImportFrom) and n.module == "datetime":
            dt_classes |= {a.asname or a.name for a in n.names if a.name in {"datetime", "date"}}
        elif isinstance(n, ast.ImportFrom) and n.module == "uuid":
            id_names |= {a.asname or a.name for a in n.names if a.name in _ID_FUNCTIONS}

    def is_datetime(node: ast.AST) -> bool:
        if isinstance(node, ast.Name):
            return node.id in dt_classes
        return (
            isinstance(node, ast.Attribute)
            and node.attr in {"datetime", "date"}
            and isinstance(node.value, ast.Name)
            and node.value.id in dt_modules
        )

    out: list[Violation] = []
    for node in ast.walk(tree):
        if id(node) in called:
            continue
        if (isinstance(node, ast.Name) and node.id in id_names) or (
            isinstance(node, ast.Attribute) and node.attr in _ID_FUNCTIONS
        ):
            reason = CORE_BANNED_METHODS["uuid7"]
        elif (
            isinstance(node, ast.Attribute)
            and node.attr in _CLOCK_METHODS
            and is_datetime(node.value)
        ):
            reason = CORE_BANNED_METHODS["now"]
        else:
            continue
        shown = _dotted(node) or "?"
        out.append(
            Violation(
                path, getattr(node, "lineno", 1), "A106",
                f"`{shown}` referenced in the core (e.g. as a default_factory): {reason}",
            )
        )  # fmt: skip
    return out


def _imports(tree: ast.Module) -> list[tuple[int, str]]:
    """Absolute modules imported anywhere in the tree (relative imports stay inside platina)."""
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found += [(node.lineno, alias.name) for alias in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            found.append((node.lineno, node.module))
    return found


def _within(module: str, packages: tuple[str, ...]) -> bool:
    return any(module == p or module.startswith(p + ".") for p in packages)


def _last_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _dotted(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return f"{_dotted(node.value)}.{node.attr}"
    return ""
