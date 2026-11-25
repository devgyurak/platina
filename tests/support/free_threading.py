"""Concurrent draws from a shared counter, for the free-threading checks of ADR-0002.

ADR-0002's fallback ID sequence is an ``itertools.count()`` used only through ``__next__``: the
core cannot import ``threading``, so it cannot take a lock. On free-threaded CPython 3.14.7
(macOS arm64) 8 threads x 200,000 draws (1.6 million per run), 5 runs gave 0 duplicates for
``itertools.count().__next__`` and up to about 1.2 million for a plain ``box[0] += 1`` counter.
That is an observation, not a documented guarantee, so the unit test built on this helper pins it;
on a GIL build it passes trivially, on the 3.14t CI job it is the real check.

To repeat the comparison by hand, pass a factory such as ``read_modify_write_counter``.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable

Draw = Callable[[], int]


def itertools_counter() -> Draw:
    return itertools.count().__next__


def read_modify_write_counter() -> Draw:
    """The unsafe shape (``n += 1``), kept only for manual comparison runs."""
    box = [0]

    def draw() -> int:
        box[0] += 1
        return box[0]

    return draw


def duplicate_draws(make: Callable[[], Draw], threads: int = 8, per_thread: int = 200_000) -> int:
    """Start ``threads`` threads together, each drawing ``per_thread`` values from one shared
    counter made by ``make``; return how many draws repeated an earlier value."""
    draw = make()
    results: list[list[int]] = [[] for _ in range(threads)]
    start = threading.Barrier(threads)

    def work(index: int) -> None:
        start.wait()
        results[index] = [draw() for _ in range(per_thread)]

    workers = [threading.Thread(target=work, args=(i,)) for i in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    values = [value for part in results for value in part]
    return len(values) - len(set(values))
