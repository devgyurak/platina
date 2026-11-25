"""Variance of Column with the variance declared (old-style type variables) vs inferred (PEP 695)."""

from domain_final import Order as InferredOrder
from domain_final_declared import Order as DeclaredOrder
from lib_final import Column as InferredColumn
from lib_final_declared import Column as DeclaredColumn


def inferred(c: InferredColumn[InferredOrder, object]) -> None:
    x: InferredColumn[InferredOrder, int] = (
        c  # pyright rejects (invariant), mypy accepts (contravariant)
    )
    print(x)


def declared(c: DeclaredColumn[DeclaredOrder, object]) -> None:
    x: DeclaredColumn[DeclaredOrder, int] = c  # both reject (declared invariant)
    print(x)
