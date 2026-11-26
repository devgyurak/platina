"""Helpers for the exception tests (ADR-0006).

``Order`` is a module-level stand-in for an entity class: ``PlatinaError.entity`` holds a class,
and a class pickles by reference only when it is importable at module level.
"""

from __future__ import annotations

import copy
import inspect
import pickle
from collections.abc import Callable
from typing import Any, Final

from platina.core.errors import DatabaseError, PlatinaError, RetryExhausted

Copier = Callable[[PlatinaError], PlatinaError]


class Order:
    """Stand-in entity class."""


def pickle_round_trip(exc: PlatinaError) -> PlatinaError:
    restored: PlatinaError = pickle.loads(pickle.dumps(exc))
    return restored


def shallow_copy(exc: PlatinaError) -> PlatinaError:
    return copy.copy(exc)


def deep_copy(exc: PlatinaError) -> PlatinaError:
    return copy.deepcopy(exc)


def state_of(exc: BaseException) -> tuple[type, tuple[Any, ...], dict[str, Any]]:
    """What a faithful copy must keep: the class, ``args`` and every instance attribute."""
    return type(exc), exc.args, dict(vars(exc))


def with_note(exc: PlatinaError, note: str) -> PlatinaError:
    exc.add_note(note)
    return exc


def raise_database_error_from(cause: Exception) -> None:
    """Raise a ``DatabaseError`` chained to a driver exception, as the mapping layer will."""
    try:
        raise cause
    except Exception as e:
        raise DatabaseError("duplicate key value", sqlstate="23505") from e


class AttemptsExhausted(RetryExhausted):
    """A subclass shaped like a later feature issue's: its own required field, its own message.

    ADR-0006 decision 4: copies must not call the constructor, so this shape round-trips too.
    """

    def __init__(self, *, attempts: int) -> None:
        super().__init__(f"gave up after {attempts} attempts", hint="retry later")
        self.attempts: Final = attempts


def with_field(cls: type[PlatinaError], field: str, value: Any, **required: Any) -> PlatinaError:
    """Build ``cls("m", <field>=value)``; ``required`` carries ``sqlstate`` for ``DatabaseError``
    (``UniqueViolation`` and ``CheckViolation`` fix theirs and take none).
    """
    return cls("m", **{field: value}, **required)


def untyped_error(**fields: Any) -> PlatinaError:
    """Build a ``PlatinaError`` from values that bypass the type checker, as untyped code can."""
    return PlatinaError("m", **fields)


def parameters(cls: type[PlatinaError]) -> list[inspect.Parameter]:
    """The constructor parameters of ``cls``, in order (name, kind, default, annotation)."""
    return list(inspect.signature(cls).parameters.values())


def parameters_without(cls: type[PlatinaError], name: str) -> list[inspect.Parameter]:
    """``parameters(cls)`` without the one called ``name``."""
    return [parameter for parameter in parameters(cls) if parameter.name != name]
