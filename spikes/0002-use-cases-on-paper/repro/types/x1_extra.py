# TEMPORARY (spike 0002): the reproducer's code below is kept byte-identical, so lint and
# formatting are suppressed for this file until the maintainer decides how to treat it.
# ruff: noqa: F821
"""[repro] X1 strengthening: how much of `Annotated[...]` metadata does each checker look at?"""

from typing import Annotated

from domain import Order
from lib import Load


def a(x: Annotated[Order, Load(1, 2, 3)]) -> None: ...  # wrong argument types
def b(x: Annotated[Order, Load.no_such_method()]) -> None: ...  # unknown attribute
def c(x: Annotated[Order, undefined_name]) -> None: ...  # undefined name
def d(x: Annotated[Order, 1 + "a"]) -> None: ...  # plain operator error
