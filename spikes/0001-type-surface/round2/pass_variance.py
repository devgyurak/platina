"""Variance pinned where both checkers agree: owner covariance on both copies of `Column`.

Accepted assignments are the assertion (pyright narrows the declared type after an assignment,
so `assert_type` would report the narrowed type, not the declared one).
"""

import domain_final as inferred_domain
import domain_final_declared as declared_domain
import lib_final as inferred
import lib_final_declared as declared


def owner_covariance_inferred(c: inferred.Column[inferred_domain.Order, int]) -> None:
    wide: inferred.Column[inferred.Entity, int] = c
    op: inferred.Op[inferred.Entity] = c.to(1)
    print(wide, op)


def owner_covariance_declared(c: declared.Column[declared_domain.Order, int]) -> None:
    wide: declared.Column[declared.Entity, int] = c
    op: declared.Op[declared.Entity] = c.to(1)
    print(wide, op)
