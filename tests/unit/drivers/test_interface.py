"""The driver contract's pure parts: ``settle`` and ``SessionUnavailable`` (ADR-0012)."""

import copy

import pytest

from platina.drivers.interface import Completed, Failed, Lost, SessionUnavailable, settle
from tests.support.faults import fault, pickled, results, unavailable_state


@pytest.mark.parametrize("received", [0, 1, 3], ids=["none", "one", "three"])
@pytest.mark.parametrize("lost", [False, True], ids=["not-lost", "lost-flag-without-fault"])
def test_settle_without_fault_completes_with_the_received_results(received, lost):
    # given
    arrived = results(received)
    # when
    reply = settle(arrived, None, lost=lost)
    # then
    assert reply == Completed(arrived)


@pytest.mark.parametrize("received", [0, 1, 3], ids=["none", "one", "three"])
def test_settle_with_fault_fails_at_the_first_missing_result(received):
    # given
    arrived = results(received)
    failure = fault("23505")
    # when
    reply = settle(arrived, failure, lost=False)
    # then
    assert reply == Failed(arrived, failure)


@pytest.mark.parametrize("received", [0, 1, 3], ids=["none", "one", "three"])
def test_settle_with_fault_and_lost_reports_the_connection_lost(received):
    # given
    arrived = results(received)
    failure = fault(None, message="server closed the connection unexpectedly")
    # when
    reply = settle(arrived, failure, lost=True)
    # then
    assert reply == Lost(arrived, failure)


def test_session_unavailable_keeps_its_fault():
    # given
    failure = fault(None, message="couldn't get a connection after 0.50 sec")
    # when
    exc = SessionUnavailable(failure)
    # then
    assert exc.fault is failure


def test_session_unavailable_message_is_the_fault_message():
    # given
    failure = fault(None, message="couldn't get a connection after 0.50 sec")
    # when
    exc = SessionUnavailable(failure)
    # then
    assert str(exc) == "couldn't get a connection after 0.50 sec"


@pytest.mark.parametrize("received", [0, 1, 3], ids=["none", "one", "three"])
def test_failed_at_is_the_number_of_results_before_the_failure(received):
    # given
    failure = fault("23505")
    # when
    reply = Failed(results(received), failure)
    # then
    assert reply.at == received


@pytest.mark.parametrize(
    "copier", [pickled, copy.copy, copy.deepcopy], ids=["pickle", "copy", "deepcopy"]
)
def test_session_unavailable_copy_keeps_class_message_and_fault(copier):
    # given
    exc = SessionUnavailable(
        fault(None, message="couldn't get a connection", constraint="c", table="t", schema="s")
    )
    # when
    copied = copier(exc)
    # then
    assert unavailable_state(copied) == unavailable_state(exc)
