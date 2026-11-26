"""Write a variant of the reproducer's round-6 stub: `LoadAfter.load` takes an invariant `Path[E]`.

Usage: python variant_r6x.py STUB OUT. Restores round 5's invariant `Path` as a base of `Relation`
and `RelColumn`, and types `LoadAfter.load(*paths: Path[E])`; `Relation.load` / `RelColumn.load`
keep the covariant `LoadPath`. A probe for the widening found in round 6 (W6-W8, W14).
"""

import sys
from pathlib import Path

PATH_CLASS = '''_P_inv = TypeVar("_P_inv")  # [variant] invariant

class Path(Generic[_P_inv]):  # noqa: UP046  # [variant] round 5's invariant Path
    """Invariant in its owner."""

'''


def swap(text: str, old: str, new: str, count: int) -> str:
    if text.count(old) != count:
        raise SystemExit(f"expected {count} of {old!r}, found {text.count(old)}")
    return text.replace(old, new)


def main() -> int:
    s = Path(sys.argv[1]).read_text()
    s = swap(s, "# [r6-repro] _P_inv and Path removed\n", PATH_CLASS, 1)
    s = swap(s, "    OwnedExpr[O], LoadPath[O]\n", "    OwnedExpr[O], Path[O], LoadPath[O]\n", 2)
    s = swap(
        s,
        "def load(self, *paths: LoadPath[E]) -> LoadAfter[E]",
        "def load(self, *paths: Path[E]) -> LoadAfter[E]",
        1,
    )
    Path(sys.argv[2]).write_text(s)
    return 0


if __name__ == "__main__":
    sys.exit(main())
