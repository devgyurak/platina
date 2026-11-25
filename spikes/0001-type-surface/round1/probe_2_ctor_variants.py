"""Item 2 alternatives: which declaration gives T as the constructor type and blocks assignment."""

from typing import reveal_type

from lib_ctor_variants import ColNeverSet, ColNoSet, ColObjectSet, FrozenBase, PlainBase


class FrozenNoSet(FrozenBase):
    a: ColNoSet[int]


class FrozenNeverSet(FrozenBase):
    a: ColNeverSet[int]


class PlainNoSet(PlainBase):
    a: ColNoSet[int]


class PlainNeverSet(PlainBase):
    a: ColNeverSet[int]


class PlainObjectSet(PlainBase):
    a: ColObjectSet[int]


def probe(
    fn: FrozenNoSet, fv: FrozenNeverSet, pn: PlainNoSet, pv: PlainNeverSet, po: PlainObjectSet
) -> None:
    reveal_type(FrozenNoSet.__init__)
    reveal_type(FrozenNeverSet.__init__)
    reveal_type(PlainNoSet.__init__)
    reveal_type(PlainNeverSet.__init__)
    reveal_type(PlainObjectSet.__init__)
    reveal_type(FrozenNoSet)
    reveal_type(FrozenNeverSet)
    reveal_type(PlainNoSet)
    reveal_type(PlainNeverSet)
    reveal_type(PlainObjectSet)
    FrozenNoSet(a=1)
    FrozenNeverSet(a=1)
    PlainNoSet(a=1)
    PlainNeverSet(a=1)
    PlainObjectSet(a=1)
    fn.a = 1  # A1
    fv.a = 1  # A2
    pn.a = 1  # A3
    pv.a = 1  # A4
    po.a = 1  # A5
