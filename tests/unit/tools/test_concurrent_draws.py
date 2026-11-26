import pytest

from tests.support.draws import broken_counter, constant_counter
from tools.concurrent_draws import duplicate_draws


def test_duplicate_draws_counts_every_draw_that_repeats_an_earlier_value():
    # when
    duplicates = duplicate_draws(constant_counter, threads=2, per_thread=3)
    # then
    assert duplicates == 5


def test_duplicate_draws_refuses_a_result_when_a_worker_did_not_finish():
    # when / then
    with pytest.raises(RuntimeError, match="2 of 2 threads did not finish their draws") as raised:
        duplicate_draws(broken_counter, threads=2, per_thread=1)
    # then
    assert isinstance(raised.value.__cause__, ValueError)
