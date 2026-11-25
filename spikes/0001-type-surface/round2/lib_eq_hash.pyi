"""P-B: entity equality/hashing variants at the type level."""

from typing import ClassVar, dataclass_transform

def field[T](*, default: T = ...) -> T: ...

@dataclass_transform(kw_only_default=True, field_specifiers=(field,))
class EqBase:
    """V1: synthesised __eq__, not frozen."""

@dataclass_transform(kw_only_default=True, frozen_default=True, field_specifiers=(field,))
class EqFrozenBase:
    """V2: synthesised __eq__ + frozen."""

@dataclass_transform(kw_only_default=True, eq_default=False, field_specifiers=(field,))
class NoEqBase:
    """V3: eq_default=False."""

@dataclass_transform(kw_only_default=True, field_specifiers=(field,))
class EqHashNoneBase:
    """V4: synthesised __eq__ and an explicit `__hash__ = None`."""

    __hash__: ClassVar[None]  # type: ignore[assignment]

@dataclass_transform(kw_only_default=True, eq_default=False, field_specifiers=(field,))
class NoEqHashNoneBase:
    """V5: no synthesised __eq__ and an explicit `__hash__ = None`."""

    __hash__: ClassVar[None]  # type: ignore[assignment]
