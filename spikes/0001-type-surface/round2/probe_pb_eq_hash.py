"""P-B: {e}, {e: 1}, a Hashable argument and hash(e) for five eq/hash variants."""

from collections.abc import Hashable

from lib_eq_hash import EqBase, EqFrozenBase, EqHashNoneBase, NoEqBase, NoEqHashNoneBase


class V1(EqBase):
    a: int


class V2(EqFrozenBase):
    a: int


class V3(NoEqBase):
    a: int


class V4(EqHashNoneBase):
    a: int


class V5(NoEqHashNoneBase):
    a: int


def takes(h: Hashable) -> None: ...


def probe(v1: V1, v2: V2, v3: V3, v4: V4, v5: V5) -> None:
    _ = {v1}  # V1-set
    _ = {v1: 1}  # V1-dict
    takes(v1)  # V1-arg
    hash(v1)  # V1-hash
    _ = {v2}  # V2-set
    _ = {v2: 1}  # V2-dict
    takes(v2)  # V2-arg
    hash(v2)  # V2-hash
    _ = {v3}  # V3-set
    _ = {v3: 1}  # V3-dict
    takes(v3)  # V3-arg
    hash(v3)  # V3-hash
    _ = {v4}  # V4-set
    _ = {v4: 1}  # V4-dict
    takes(v4)  # V4-arg
    hash(v4)  # V4-hash
    _ = {v5}  # V5-set
    _ = {v5: 1}  # V5-dict
    takes(v5)  # V5-arg
    hash(v5)  # V5-hash
