"""Platina: an ORM whose domain code never touches the database.

Public so far: the exception hierarchy (design section 10.12, ADR-0006). The rest of the surface
(``App``, ``Entity``, ``usecase``, ``Load``, ...) is sketched in docs/design/design.md section 4 and
lands item by item through the feature loop.
"""

from platina.core.errors import (
    ChainClosed,
    CheckViolation,
    CommitCycle,
    ConcurrencyError,
    ConflictingWrites,
    DatabaseError,
    IntraUsecaseConflict,
    ModuleBoundaryError,
    MovedSnapshotAccess,
    NotFound,
    PlatinaError,
    RelationNotLoaded,
    RetryExhausted,
    SealError,
    SourceLocation,
    UniqueViolation,
    UnloadedReference,
    UsageError,
    VersionMismatch,
)

__all__ = [
    "ChainClosed",
    "CheckViolation",
    "CommitCycle",
    "ConcurrencyError",
    "ConflictingWrites",
    "DatabaseError",
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
