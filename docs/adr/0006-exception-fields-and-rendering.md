# ADR-0006: Exception fields are typed keyword-only values; `str(exc)` renders them in a fixed layout

- Status: Accepted (maintainer, 2026-11-25)
- Date: 2026-11-25
- Related: design sections 4.6 (exception table), 4.13 (message examples), 10.3
  (`core/errors.py`), 10.12 (exception hierarchy); ADR-0004 (embedded paths); issue #8

The bar for this document: the maintainer reads it and is convinced. Keep it short.

## Context
- Section 10.12 gives every exception five structured fields - `usecase`, `entity`, `field`,
  `location`, `hint` - "so no string parsing is needed for CLI or IDE integration or for test
  assertions". It names them but gives them no types and no constructor.
- `platina.core.errors` is the bottom of the core: every other core package raises from it, so it
  cannot import `Column`, `Entity`, the use-case wrapper or anything else in `platina`. It may
  only use the standard-library allowlist (`CORE_ALLOWED`; no `os`, `sys`, `pathlib`).
- The 4.13 examples carry lines the five fields cannot hold: `Actual load declaration: ...`,
  `Example of the needed declaration: ...` (`RelationNotLoaded`) and
  `Field: Order.status  ← @invariant paid_requires_total (entities.py:29)` (`SealError`). The
  maintainer already decided (2026-11-25) that the location line is always
  `Location: <file>:<line>  (<function>)`, replacing `Use case: ...` in the first example, and
  that `ModuleBoundaryError` is a subclass of `SealError`.
- Facts checked on CPython 3.14.7 (probes, not kept in the repository):
  - The default `BaseException.__reduce__` returns `(cls, self.args, self.__dict__)`, so
    unpickling calls `cls(*args)`. It breaks as soon as a constructor has a keyword-only argument
    without a default (`TypeError: missing 1 required keyword-only argument`) or builds its own
    message from other arguments.
  - A base-class `__reduce__` returning `(_restore, (type(self), self.args), self.__dict__)`,
    where `_restore(cls, args)` is `cls.__new__(cls, *args)`, round-trips through `pickle`,
    `copy.copy` and `copy.deepcopy` with every attribute and `__notes__` - also for a subclass
    with a required keyword-only field and for one whose constructor takes no message.
  - `__cause__`, `__context__` and `__traceback__` are never pickled.
  - An exception holding a **use-case object** (a stand-in wrapper instance that replaces the
    module-level function, as `@usecase` would): with a plain wrapper, `pickle.dumps` fails
    (`PicklingError: Can't pickle <function pay>: it's not the same object as <module>.pay`)
    and `copy.deepcopy` clones the wrapper (`copied.usecase is pay` is `False`). Only a wrapper
    that implements `__reduce__` (returning its global name), `__copy__` and `__deepcopy__`
    keeps the same object on all three paths. A use case defined inside a function (as in the
    section 4.12 test example) fails either way (`PicklingError: Can't pickle local object`).
  - The traceback prints `<module>.<qualname>: <str(exc)>`, so a Platina exception shows as
    `platina.core.errors.RelationNotLoaded: ...`; the `ClassName:` prefix is not part of
    `str(exc)`.

## Decision
1. **Constructor.** On `PlatinaError` the message is the only positional argument
   (positional-only); every field is keyword-only with the default `None` (`details`: `()`).
   `args == (message,)`.

   ```python
   class PlatinaError(Exception):
       def __init__(
           self,
           message: str,
           /,
           *,
           usecase: str | None = None,        # the use case's registry name
           entity: type[object] | None = None,   # the entity class itself: Order
           field: str | None = None,          # path relative to entity: "items", "address.city"
           location: SourceLocation | None = None,
           hint: str | None = None,
           details: tuple[tuple[str, str], ...] = (),   # ordered (label, value) lines
       ) -> None: ...

   @dataclass(frozen=True, slots=True)
   class SourceLocation:
       file: str                     # path from the top-level package: "shop/billing/usecases.py"
       line: int
       function: str | None = None   # qualified name: "pay", "OrderRepo.expire_older_than"
   ```

   - `entity` is the class object because that is the one exact way to name an entity
     (`exc.entity is Order`); its type is `type[object]` because `errors.py` cannot import
     `Entity` (bare `type` is `type[Any]` and would leak `Any` into user code).
   - `usecase` is the use case's **registry name** - the same string the use-case object
     exposes. A string, not the object: a class pickles by reference, copies atomically and
     carries its own `__module__`/`__qualname__`, but a use case is a wrapper instance that
     `@usecase` put in place of the function: none of that holds for it by default, and the type
     `errors.py` could give it promises none of it (Context). The name's
     format is set by the issue that introduces `@usecase` and the registry, which needs a stable
     name anyway because `then` records use cases in the outbox as commands (section 4.6); fixing
     it here first could create a second name. #8 only stores `usecase` and never renders it, so
     deferring the format changes nothing in #8's code or tests.
   - `field` is a string because columns overload `==` to build expressions. It is the attribute
     path relative to `entity`, joined with `.` like ADR-0004's embedded paths. By convention
     `field` is only set together with `entity`; the constructor does not check it.
   - `SourceLocation.file` is a display path and never an absolute, machine-dependent one:
     the path **from the top-level package directory**, always with `/`, when it can be derived;
     otherwise the bare file name; a pseudo file name of the form `<...>` (`<string>`, REPL)
     as is. The package path is derived with string operations from the module name and the
     file name, so the core can compute it. It cannot be derived when the module runs as
     `__main__` (`python -m shop.billing.usecases`) or when the module name does not match the
     path (`spec_from_file_location("a.b.c.plugin", "plug/z.py")`); both fall back to the file
     name. The line of an access (the second 4.13 example, line 31) comes from a frame, not a
     code object; without `sys` in `CORE_ALLOWED` the only way to a frame is
     `inspect.currentframe`, and a function wrapped with `functools.wraps` needs
     `inspect.unwrap` or the location points at the decorator. The helper that does all this,
     and its tests, land with the first issue that raises with a location. #8 only stores and
     renders the field, and tests build `SourceLocation` explicitly.
   - The fields are instance attributes declared `self.entity: Final = entity` in `__init__`:
     read-only to pyright and mypy, no runtime enforcement. Both reject assignment; `del` is
     rejected by pyright only (mypy accepts it). Because the fields are `Final`, a subclass cannot
     narrow a base field (e.g. make `ModuleBoundaryError.usecase` non-optional); we accept that.
   - Every exception and `SourceLocation` are re-exported from `platina` (`__all__`). The name is
     `SourceLocation`, not `Location`, because `Location` is a common entity name in user code.
2. **Lines the five fields cannot hold go to `details`.** An ordered tuple of `(label, value)`
   pairs on the base class (not `notes`, to avoid confusion with PEP 678 `__notes__`).
   - A subclass may add typed fields of its own (`RetryExhausted.attempts`, ...) in the feature
     issue that raises it, required or not, and may take a different constructor signature.
   - A line that restates one of the **subclass's own** typed fields is built by the class from
     that field in its constructor; the raise site does not pass it in `details`, so that value
     is given once. Until a subclass has such a field, the line goes in `details`: the fifth
     4.13 example (`Field: Order.status  ← @invariant ...`) passes it as a detail next to
     `entity=Order, field="status"`, and the overlap stays until the issue that raises it gives
     the class a typed field.
   - Issue #8 adds no subclass fields except `DatabaseError.sqlstate: str | None`, keyword-only
     and **required** (a forgotten SQLSTATE does not type-check; `None` is for driver errors
     without one, which #18 may narrow). `UniqueViolation` and `CheckViolation` inherit it
     unchanged in #8, so `UniqueViolation("...", sqlstate="40001")` type-checks; whether they fix
     their value (23505 / 23514) is decided by #18 with the SQLSTATE mapping.
   - The original driver exception is **not a field**: it is the `__cause__` of the
     `DatabaseError` (`raise ... from e`).
3. **Rendering.** `str(exc)` is the headline (the message) followed by one line per present item,
   each indented two spaces, in this order:

   | Order | Source | Line |
   |---|---|---|
   | 1 | `location` | `Location: <file>:<line>  (<function>)` - without `  (<function>)` when `function` is `None` |
   | 2 | `details`, in order | `<label>: <value>` |
   | 3 | `hint` | `Fix: <hint>` |

   - A field that is `None` (or empty `details`) produces no line; a bare message renders as
     itself. The headline alone is `exc.args[0]`.
   - `usecase`, `entity` and `field` produce no line of their own: they exist for programs, and
     the headline or a detail line shows them to people.
   - Values are rendered with `str()`; continuation lines of a value that contains line breaks
     are indented four spaces, and a trailing line break adds no line. The headline is rendered
     as given. Nothing is validated in the constructor (an exception while building an exception
     would hide the real error). For the same reason rendering tolerates the two mistakes
     untyped code makes most easily - a value that is not a string, and a detail that is not a
     `(label, value)` pair (rendered as a bare line) - rather than leaving the traceback with
     `<exception str() failed>`. It is not total: other wrong shapes (`details=None`, a
     `location` that is not a `SourceLocation`) are type errors under both checkers, and
     `str(exc)` fails on them; guarding every shape at run time would be detection where the
     type checker already removes the mistake.
   - One detail is one line: the first 4.13 example's
     `Actual load declaration: Load()  ·  Example of the needed declaration: ...` becomes two
     details, so two lines.
   - The `ClassName:` prefix in 4.13 is the traceback's (module-qualified,
     `platina.core.errors.RelationNotLoaded:`), not part of `str(exc)`. 4.13 keeps the short
     form for readability and says so; tests compare `str(exc)`.
   - `repr(exc)` stays the default (`RelationNotLoaded('Order.items is not loaded.')`). PEP 678
     notes a user adds with `add_note` still print after the rendered lines.
4. **Pickle and copy round-trip is guaranteed** for every class in the hierarchy by one
   `__reduce__` on `PlatinaError` (`_restore` + `__dict__`, see Context); no subclass defines its
   own. Unpickling does not call `__init__`, so subclass constructors are free in shape. The copy
   keeps every field and `__notes__`; it loses `__cause__` like any Python exception, so
   `DatabaseError` keeps `sqlstate` but not the original driver exception. `entity` pickles by
   reference: it must be a module-level class (an entity defined inside a test function does not
   pickle), so the round-trip test uses a module-level entity. The pickle stream names
   `platina.core.errors._restore`, so pickles are only guaranteed to load with the same Platina
   version; compatibility across versions is not promised.

## Consequences
- Tests, the CLI and IDE tooling read `exc.entity`, `exc.field`, `exc.location.line` directly; the
  4.13 examples become exact `str(exc)` assertions.
- One rendering rule for every class; a new class only chooses its message, details and hint.
- The hierarchy pickles across process boundaries (multiprocessing, pytest-xdist) without
  per-class code, pinned by a round-trip test parametrized over every class.
- `details` is untyped text: a program that needs one of those values waits for the typed field
  its feature issue adds.
- Fields are read-only, so an exception must know every field when it is built; nothing fills
  `usecase` in later. Design 10.5 has the runner build the exception with `map_sqlstate(e)`
  and throw it into the engine, but the driver and the runner do not know the use case. Which
  layer builds the public `DatabaseError` and links the driver exception as `__cause__` is
  decided by #17/#18, not here.
- `SourceLocation.file` is a display path: in a src layout `shop/billing/usecases.py` is not a
  path from the project root, so a tool cannot always open it. Resolvable fields (`module`, ...)
  can be added to `SourceLocation` later with defaults without breaking compatibility; none is
  added now.
- Type tests pin the surface under both checkers: `assert_type(exc.location, SourceLocation | None)`
  and the other fields; assigning to a field, passing a field positionally and omitting
  `DatabaseError`'s `sqlstate` are errors.
- Documents updated with the implementation (docs-sync): design 4.13 (the `Location:` line, the
  first example's `·` line split in two, a note on the `ClassName:` prefix) and 10.12
  (`ModuleBoundaryError` under `SealError`, field types, link here), both with `design-KO.md`;
  `docs/architecture.md` (`platina.core.errors`, root re-exports, ADR table); the Errors section
  of `.agents/rules/architecture.md` followed by `make agents-sync`; `CHANGELOG.md`; the
  "nothing implemented" status in `AGENTS.md` and `README.md` (+ `README-KO.md`); the
  "Nothing is public yet" docstring of `src/platina/__init__.py`.

## Alternatives considered
- **All five fields as strings** (`entity: str | None`): simplest, but `"Order"` vs
  `"shop.billing.entities.Order"` vs the table name is a second way to name an entity, and
  tests could no longer assert `exc.entity is Order`.
- **Object references typed `object`** (`field: object`, holding the `Column`): `errors.py`
  could not type them, every reader would need `isinstance`, and `exc.field == Order.status`
  builds an expression instead of comparing.
- **Typed fields per class now** (`RelationNotLoaded.declared: Load`, ...): those classes are not
  raised anywhere yet; their fields belong to the issues that raise them (#11 and #14 for
  `RelationNotLoaded`, #17/#18 for the concurrency and database errors, ...), and the types they
  would need are above `errors.py`.
- **The use-case object in `usecase`** (`Callable[..., object] | None`): pickle and deepcopy keep
  it only if the not-yet-written `Usecase` class implements `__reduce__`, `__copy__` and
  `__deepcopy__`, so decision 4's guarantee would depend on it; a use case defined inside a
  function never pickles (Context); and a CLI or IDE could not read the name without importing
  `Usecase` - the same reason `field: object` is rejected.
- **PEP 678 `__notes__` for the extra lines**: `str(exc)` would not contain them (only the
  traceback prints them), they print unindented after `Fix:`, and they are attached by mutation
  after construction rather than given to the constructor.
- **The default `__reduce__` with "every field keyword-only with a default" as the rule**: works
  for #8, but makes every subclass field optional (`sqlstate` could be forgotten silently) and a
  subclass that builds its own message breaks on unpickle; the test would be the only guard.
- **Absolute `co_filename` paths in `SourceLocation.file`**: no computation, but messages and
  test expectations would depend on the machine.
- **`__module__ = "platina"` on every class** so the traceback prints `platina.RelationNotLoaded`:
  nicer, but a second place to keep in sync with the re-exports, and it changes the pickle path;
  can be added later without affecting the fields.

## Review
`architect`, 2026-11-25, on the first draft: **APPROVE WITH CHANGES** - "Typed keyword-only
fields with one fixed rendering keep one way per operation and keep the core sans-I/O. Using
`type` for `entity` and `str` for `usecase` and `field` fits what `CORE_ALLOWED` lets `errors.py`
import. With decision B applied, the rendering order (location, notes, hint) fits all seven 4.13
examples." Two MAJOR findings (the defaults-only pickle rule; who produces `Location.file`) and
eight MINOR/NIT findings (one only confirms the scope), all taken into the second revision.

Independent review (separate session), 2026-11-25, on the second revision: **APPROVE WITH
CHANGES** - three MAJOR findings: (a) the "each value once" rule contradicted the fifth 4.13
example - fixed; (b) with read-only fields, who builds the public `DatabaseError` - deferred to
#17/#18 by the maintainer; (c) the reason given for `usecase: str` was not consistent with
`entity: type` - the string stays, the reason was replaced. Four MINOR
(`sqlstate` on `UniqueViolation`/`CheckViolation`; fallback when the package path cannot be
derived, and frames for access lines; a display path tools may not open; missing docs-sync
targets) and NITs. It reproduced the base-class `__reduce__` round trip (pickle protocols 0-5,
`copy`, `deepcopy`), the type-checker behaviour (pyright strict and mypy strict) and all seven
4.13 examples under the rendering rule. With the maintainer's decisions of the same day (the three
open questions approved; who builds the public `DatabaseError` deferred to #17/#18; `usecase`
stays a string, redefined as the registry name), all findings are taken into this revision.

## History
- 2026-11-25 - created.
- 2026-11-25 - architect review (APPROVE WITH CHANGES): base-class `__reduce__` instead of the
  defaults-only rule, `sqlstate` required; `SourceLocation.file` is the package-relative path;
  `notes` renamed `details`, `Location` renamed `SourceLocation` and re-exported from `platina`;
  class-built lines for typed fields; continuation-line indent; module-level entity for pickle;
  `Final` narrowing limit stated; complete docs-sync list.
- 2026-11-25 - independent review and maintainer decisions: `usecase` is the registry name (format
  deferred, use-case object rejected with reproduced facts); class-built lines only for a
  subclass's own fields; `UniqueViolation`/`CheckViolation` inherit `sqlstate` until #18; the
  driver exception is `__cause__`, its builder decided by #17/#18; `SourceLocation.file`
  fallbacks and the frame path; display-path limit; more docs-sync targets; no cross-version
  pickle promise; `exc.args[0]` for the headline.
- 2026-11-25 - review paragraph lists the independent review's three MAJOR findings; the
  `usecase` reason no longer claims more than the Context shows.
- 2026-11-25 - accepted by the maintainer.
- 2026-11-25 - implementation review (type-reviewer, code-reviewer): `entity` is
  `type[object] | None` rather than bare `type` (which leaked `Any`); `del` on a field is caught
  by pyright only; rendering uses `str()`, drops a trailing line break, keeps the headline as
  given and tolerates a non-string value and a detail that is not a pair. No change of
  direction.
- 2026-11-25 - independent verification: the rendering claim narrowed to what it does and what
  the tests pin (a non-string value, a non-pair detail; `details=None` or a non-`SourceLocation`
  location still make `str()` fail and are type errors); `SourceLocation` has no public
  `render()` method, the location line is built by a module-private function.
