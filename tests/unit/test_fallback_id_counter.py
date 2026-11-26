import pytest

from tools.concurrent_draws import duplicate_draws, itertools_counter


@pytest.mark.thread_unsafe(
    reason="brings its own 8 threads; the control run of tools/freethreaded.py has the same shape"
)
@pytest.mark.parametrize("run", [1, 2, 3, 4, 5])
def test_itertools_count_hands_out_unique_values_to_concurrent_threads(run):
    """ADR-0002: the fallback ID sequence relies on this; it matters on free-threaded builds."""
    # when
    duplicates = duplicate_draws(itertools_counter)
    # then
    assert duplicates == 0
