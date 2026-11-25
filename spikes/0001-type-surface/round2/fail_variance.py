"""Variance pinned where both checkers agree. The wide-value line on the inferred `lib_final.Column`
(rejected by pyright only) cannot be pinned here; it stays in `probe_variance_declared.py`."""

import domain_final as inferred_domain
import domain_final_declared as declared_domain
import lib_final as inferred
import lib_final_declared as declared


# fmt: off
def inferred_column(narrow: inferred.Column[inferred_domain.Order, bool]) -> None:
    x: inferred.Column[inferred_domain.Order, int] = narrow  # expect-error[reportAssignmentType, assignment]: value parameter is not covariant
    print(x)


def declared_column(
    wide: declared.Column[declared_domain.Order, object],
    narrow: declared.Column[declared_domain.Order, bool],
    to_child: declared.Column[declared.Entity, int],
) -> None:
    a: declared.Column[declared_domain.Order, int] = wide  # expect-error[reportAssignmentType, assignment]: value parameter is invariant (not contravariant)
    b: declared.Column[declared_domain.Order, int] = narrow  # expect-error[reportAssignmentType, assignment]: value parameter is invariant (not covariant)
    c: declared.Column[declared_domain.Order, int] = to_child  # expect-error[reportAssignmentType, assignment]: owner parameter is covariant, not contravariant
    print(a, b, c)
# fmt: on
