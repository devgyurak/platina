"""Variance of a PEP 695 `Column[O, T]` depending on its members (L6)."""

from typing import overload

class Op[O]: ...

class ColWithPath[O, T]:
    """As lib_final: `to` takes T, `path` refers to Column[T, U]."""

    def to(self, value: T, /) -> Op[O]: ...
    def path[U](self, field: ColWithPath[T, U], /) -> ColWithPath[O, U]: ...

class ColWithPathAndGetter[O, T]:
    """As above, plus a member that returns T."""

    def to(self, value: T, /) -> Op[O]: ...
    def path[U](self, field: ColWithPathAndGetter[T, U], /) -> ColWithPathAndGetter[O, U]: ...
    @property
    def value_type(self) -> T: ...

class ColNoPath[O, T]:
    """`to` only, no `path`."""

    def to(self, value: T, /) -> Op[O]: ...

__all__ = ["ColNoPath", "ColWithPath", "ColWithPathAndGetter", "Op", "overload"]
