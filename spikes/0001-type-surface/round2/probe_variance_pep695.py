"""L6: which PEP 695 shapes make both checkers agree on the variance of T."""

from lib_variance import ColNoPath, ColWithPath, ColWithPathAndGetter


class Order: ...


def with_path(wide: ColWithPath[Order, object], narrow: ColWithPath[Order, bool]) -> None:
    a: ColWithPath[Order, int] = wide  # W1 accepted iff T is contravariant
    b: ColWithPath[Order, int] = narrow  # W2 accepted iff T is covariant
    print(a, b)


def with_getter(
    wide: ColWithPathAndGetter[Order, object], narrow: ColWithPathAndGetter[Order, bool]
) -> None:
    a: ColWithPathAndGetter[Order, int] = wide  # G1
    b: ColWithPathAndGetter[Order, int] = narrow  # G2
    print(a, b)


def no_path(wide: ColNoPath[Order, object], narrow: ColNoPath[Order, bool]) -> None:
    a: ColNoPath[Order, int] = wide  # N1
    b: ColNoPath[Order, int] = narrow  # N2
    print(a, b)
