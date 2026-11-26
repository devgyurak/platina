"""The Platina exception hierarchy (design section 10.12) and its structured fields (ADR-0006).

Every exception carries, besides its message, the keyword-only fields ``usecase``, ``entity``,
``field``, ``location``, ``hint`` and ``details``, so tools and tests read values instead of
parsing text. ``str(exc)`` renders the message followed by the location, the details in order and
the hint, each on its own indented line (design section 4.13). User domain exceptions are not
wrapped; they propagate as they are.

This module is the bottom of the core: it imports nothing from ``platina``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final, Literal

__all__ = [
    "ChainClosed",
    "CheckViolation",
    "CommitCycle",
    "ConcurrencyError",
    "ConflictingWrites",
    "DatabaseError",
    "ForeignKeyViolation",
    "IntraUsecaseConflict",
    "ModuleBoundaryError",
    "MovedSnapshotAccess",
    "NotFound",
    "PlatinaError",
    "RelationNotLoaded",
    "RetryExhausted",
    "SealError",
    "SourceLocation",
    "UniqueViolation",
    "UnloadedReference",
    "UsageError",
    "VersionMismatch",
]


@dataclass(frozen=True, slots=True)
class SourceLocation:
    """Where an error points: a display path, a line and the enclosing function (ADR-0006).

    ``file`` is the path from the top-level package directory with ``/`` separators
    (``shop/billing/usecases.py``), the bare file name when that cannot be derived, or a pseudo
    name such as ``<string>`` as it is - never an absolute path.
    """

    file: str
    line: int
    function: str | None = None  # qualified name: "pay", "OrderRepo.expire_older_than"


def _restore[E: PlatinaError](cls: type[E], args: tuple[Any, ...]) -> E:
    """Unpickling and copying entry point: rebuild without calling ``__init__`` (ADR-0006).

    ``BaseException.__new__`` sets ``args``; the instance attributes are restored from the state
    that ``PlatinaError.__reduce__`` returns. A subclass constructor may therefore take any shape.
    """
    return cls.__new__(cls, *args)


# Rendering tolerates two mistakes that untyped code makes easily - a value that is not a
# string, and a detail that is not a (label, value) pair - instead of hiding the whole message
# behind "<exception str() failed>" in the traceback. Other wrong shapes (``details=None``, a
# location that is not a SourceLocation) are type errors and are not rendered (ADR-0006).


def _location_text(location: SourceLocation) -> str:
    where = f"{location.file}:{location.line}"
    if location.function is None:
        return where
    return f"{where}  ({location.function})"


def _indented(value: object) -> str:
    # Continuation lines of a multi-line value are indented under the label's line.
    return "\n    ".join(str(value).splitlines())


def _line(label: object, value: object) -> str:
    return f"  {label}: {_indented(value)}"


def _detail_line(detail: tuple[str, str]) -> str:
    try:
        label, value = detail
    except TypeError, ValueError:  # not a pair, e.g. details=("Field", "x") without the outer tuple
        return f"  {_indented(detail)}"
    return _line(label, value)


class PlatinaError(Exception):
    """Base of every Platina exception.

    The message is the only positional argument; ``exc.args[0]`` is the headline alone.
    ``usecase`` is the use case's registry name, ``entity`` the entity class, ``field`` the
    attribute path relative to ``entity`` (``"items"``, ``"address.city"``). ``details`` holds
    ordered ``(label, value)`` lines the other fields cannot express. None of the fields is
    validated: an exception while building an exception would hide the real error.
    """

    def __init__(
        self,
        message: str,
        /,
        *,
        usecase: str | None = None,
        entity: type[object] | None = None,
        field: str | None = None,
        location: SourceLocation | None = None,
        hint: str | None = None,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(message)
        self.usecase: Final = usecase
        self.entity: Final = entity
        self.field: Final = field
        self.location: Final = location
        self.hint: Final = hint
        self.details: Final = details

    def __str__(self) -> str:
        lines = [str(self.args[0]) if self.args else ""]
        if self.location is not None:
            lines.append(_line("Location", _location_text(self.location)))
        lines.extend(_detail_line(detail) for detail in self.details)
        if self.hint is not None:
            lines.append(_line("Fix", self.hint))
        return "\n".join(lines)

    def __reduce__(self) -> tuple[Any, ...]:
        # One reduction for the whole hierarchy: pickle, copy and deepcopy keep every field and
        # __notes__ without calling the subclass constructor (ADR-0006, decision 4).
        return (_restore, (type(self), self.args), self.__dict__)


class SealError(PlatinaError):
    """Validation failure at startup (module boundaries, invariants, mappings)."""


class ModuleBoundaryError(SealError):
    """A module uses an entity that another module owns."""


class UsageError(PlatinaError):
    """A programming error; never retried."""


class RelationNotLoaded(UsageError):
    """A relation that the use case did not declare was read."""


class UnloadedReference(UsageError):
    """A field read, ``.set``, ``==`` or ``hash()`` on a ref."""


class ChainClosed(UsageError):
    """``.set`` on a view outside the ``chain`` block."""


class MovedSnapshotAccess(UsageError):
    """A read (also ``==`` / ``hash()``) of an original moved by ``chain``."""


class ConflictingWrites(UsageError):
    """The same field written twice within a single step."""


class IntraUsecaseConflict(UsageError):
    """A set change and a row change overlap in the same use case."""


class CommitCycle(UsageError):
    """The commit planner found a dependency cycle."""


class NotFound(PlatinaError):
    """The row of the root ref or of a required dependent load is missing."""


class ConcurrencyError(PlatinaError):
    """A concurrency failure the caller has to handle."""


class RetryExhausted(ConcurrencyError):
    """The 40001/40P01 retry limit was exceeded."""


class VersionMismatch(ConcurrencyError):
    """``expected_version`` did not match (optimistic lock across requests)."""


class DatabaseError(PlatinaError):
    """Any other database error.

    ``sqlstate`` is required (``None`` for driver errors without one). The original driver
    exception is not a field: it is this exception's ``__cause__`` (``raise ... from e``).
    """

    def __init__(
        self,
        message: str,
        /,
        *,
        sqlstate: str | None,
        usecase: str | None = None,
        entity: type[object] | None = None,
        field: str | None = None,
        location: SourceLocation | None = None,
        hint: str | None = None,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(
            message,
            usecase=usecase,
            entity=entity,
            field=field,
            location=location,
            hint=hint,
            details=details,
        )
        self.sqlstate: Final = sqlstate


class UniqueViolation(DatabaseError):
    """A unique constraint was violated: ``sqlstate`` is always ``"23505"``.

    The constructor takes no ``sqlstate``, so an instance with another value cannot be built
    (ADR-0006, decided in #18).
    """

    def __init__(
        self,
        message: str,
        /,
        *,
        usecase: str | None = None,
        entity: type[object] | None = None,
        field: str | None = None,
        location: SourceLocation | None = None,
        hint: str | None = None,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(
            message,
            sqlstate="23505",
            usecase=usecase,
            entity=entity,
            field=field,
            location=location,
            hint=hint,
            details=details,
        )


class CheckViolation(DatabaseError):
    """A check constraint was violated: ``sqlstate`` is always ``"23514"``.

    The constructor takes no ``sqlstate``, so an instance with another value cannot be built
    (ADR-0006, decided in #18).
    """

    def __init__(
        self,
        message: str,
        /,
        *,
        usecase: str | None = None,
        entity: type[object] | None = None,
        field: str | None = None,
        location: SourceLocation | None = None,
        hint: str | None = None,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(
            message,
            sqlstate="23514",
            usecase=usecase,
            entity=entity,
            field=field,
            location=location,
            hint=hint,
            details=details,
        )


class ForeignKeyViolation(DatabaseError):
    """A foreign key was violated: a row still references a deleted one, or a key points at no
    row (``23503``; ``23001`` from a ``RESTRICT`` foreign key). Not retried: it depends on rows
    the use case did not read (ADR-0010).

    ``sqlstate`` is one of the two values, so no other can be passed (ADR-0012).
    """

    def __init__(
        self,
        message: str,
        /,
        *,
        sqlstate: Literal["23503", "23001"],
        usecase: str | None = None,
        entity: type[object] | None = None,
        field: str | None = None,
        location: SourceLocation | None = None,
        hint: str | None = None,
        details: tuple[tuple[str, str], ...] = (),
    ) -> None:
        super().__init__(
            message,
            sqlstate=sqlstate,
            usecase=usecase,
            entity=entity,
            field=field,
            location=location,
            hint=hint,
            details=details,
        )
