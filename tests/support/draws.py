"""Counters for testing ``tools.concurrent_draws`` itself."""

from __future__ import annotations

import itertools

from tools.concurrent_draws import Draw


def constant_counter() -> Draw:
    """Every draw is 0, so all draws but the first repeat."""
    return itertools.repeat(0).__next__


def broken_counter() -> Draw:
    def draw() -> int:
        raise ValueError("counter broke")

    return draw
