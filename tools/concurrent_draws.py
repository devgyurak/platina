"""Concurrent draws from a shared counter, for the free-threading checks of ADR-0002.

ADR-0002's fallback ID sequence is an ``itertools.count()`` used only through ``__next__``: the
core cannot import ``threading``, so it cannot take a lock. On free-threaded CPython 3.14.7
(macOS arm64) 8 threads x 200,000 draws (1.6 million per run), 5 runs gave 0 duplicates for
``itertools.count().__next__`` and up to about 1.2 million for a plain ``box[0] += 1`` counter.
That is an observation, not a documented guarantee, so the unit test built on this helper
(``tests/unit/test_fallback_id_counter.py``) pins it; on a GIL build it passes trivially, on the
3.14t CI job it is the real check.

``read_modify_write_counter`` is the control: ``tools/freethreaded.py`` draws from it after every
free-threaded run, to show that threads on that machine really race. The helper lives in
``tools/`` rather than ``tests/support/`` because both the test and that runner use it and imports
only go from ``tests`` to ``tools``. It is test tooling, never imported by ``src/``.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Callable

Draw = Callable[[], int]


def itertools_counter() -> Draw:
    return itertools.count().__next__


def read_modify_write_counter() -> Draw:
    """The unsafe shape (``n += 1``): the control ``tools/freethreaded.py`` draws from after
    every free-threaded run."""
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
    errors: list[Exception] = []
    start = threading.Barrier(threads)

    def work(index: int) -> None:
        start.wait()
        try:
            results[index] = [draw() for _ in range(per_thread)]
        except Exception as error:  # kept for the caller: fewer draws could hide a race
            errors.append(error)

    workers = [threading.Thread(target=work, args=(i,)) for i in range(threads)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join()
    if errors:
        raise RuntimeError(
            f"{len(errors)} of {threads} threads did not finish their draws"
        ) from errors[0]
    values = [value for part in results for value in part]
    return len(values) - len(set(values))
