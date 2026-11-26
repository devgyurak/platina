"""``first_error`` and ``verdict``: the pure rules behind every pipeline reply (ADR-0012).

``first_error`` picks which of a pipeline's two errors belongs to its first failed statement;
``verdict`` decides the reply. One table row per branch of ``verdict``, including the ones no
database run reaches deterministically with psycopg 3.3 (a non-psycopg error at the block's exit,
the count guard of the dumper shape, results missing without an error).

No database needed, but ``platina.drivers.psycopg._common`` imports psycopg, which the
free-threaded unit job cannot load - so it lives with the integration tests.
"""

import psycopg
import pytest
from psycopg import errors

from platina.drivers.psycopg._common import first_error
from tests.support.statements import BEGIN_RESULT, INSERT_RESULT
from tests.support.verdicts import verdict_shape

UNIQUE = errors.UniqueViolation("duplicate key")
ABORTED = errors.PipelineAborted("pipeline aborted")
DATA = psycopg.DataError("cannot adapt")
LOADER = ValueError("a caller's loader failed")
DUMPER = ValueError("a caller's dumper failed")
TWO = (BEGIN_RESULT, INSERT_RESULT)


@pytest.mark.parametrize(
    ("in_block", "at_exit", "expected"),
    [
        pytest.param(UNIQUE, ABORTED, UNIQUE, id="server-error-in-block-then-aborted"),
        pytest.param(DATA, UNIQUE, UNIQUE, id="client-error-then-earlier-server-error"),
        pytest.param(None, ABORTED, ABORTED, id="aborted-alone-is-kept"),
        pytest.param(UNIQUE, None, UNIQUE, id="in-block-alone"),
        pytest.param(None, None, None, id="no-error"),
    ],
)
def test_first_error_picks_the_error_of_the_first_failed_statement(in_block, at_exit, expected):
    # when
    chosen = first_error(in_block, at_exit)
    # then
    assert chosen is expected


@pytest.mark.parametrize(
    ("observed", "expected"),
    [
        pytest.param(
            {"unclean": True, "statements": 4, "sent": 4, "received": TWO, "at_exit": DATA},
            ("abandon", None, DATA),
            id="unclean-connection-is-lost",
        ),
        pytest.param(
            {"unclean": True, "statements": 4, "sent": 4, "received": TWO},
            ("abandon", None, None),
            id="unclean-without-error-is-lost-with-own-fault",
        ),
        pytest.param(
            {"statements": 4, "sent": 4, "received": TWO, "stopped_ran": True, "at_exit": DATA},
            ("abandon", None, DATA),
            id="stopped-statement-ran-is-lost",
        ),
        pytest.param(
            {"statements": 4, "sent": 4, "received": TWO, "at_exit": LOADER},
            ("abandon", None, LOADER),
            id="non-psycopg-exit-error-is-lost",
        ),
        pytest.param(
            {"statements": 4, "sent": 3, "received": TWO, "in_block": DUMPER},
            ("propagate", None, DUMPER),
            id="dumper-shape-propagates",
        ),
        pytest.param(
            {"statements": 4, "sent": 4, "received": TWO, "in_block": DUMPER},
            ("abandon", None, DUMPER),
            id="non-psycopg-in-block-error-not-in-dumper-shape-is-lost",
        ),
        pytest.param(
            {"statements": 5, "sent": 4, "received": TWO, "in_block": DUMPER, "at_exit": UNIQUE},
            ("failed", 2, UNIQUE),
            id="earlier-server-error-wins-over-dumper-error",
        ),
        pytest.param(
            {"statements": 5, "sent": 4, "received": TWO, "in_block": DUMPER, "at_exit": ABORTED},
            ("abandon", None, DUMPER),
            id="dumper-error-with-aborted-exit-is-lost",
        ),
        pytest.param(
            {"statements": 2, "sent": 2, "received": TWO},
            ("completed", 2, None),
            id="every-result-is-completed",
        ),
        pytest.param(
            {"statements": 4, "sent": 4, "received": TWO},
            ("abandon", None, None),
            id="results-missing-without-error-is-lost",
        ),
        pytest.param(
            {"statements": 4, "sent": 3, "received": TWO, "in_block": DATA},
            ("failed", 2, DATA),
            id="psycopg-client-error-fails-at-first-missing-result",
        ),
        pytest.param(
            {"statements": 4, "sent": 3, "received": TWO, "in_block": UNIQUE, "at_exit": ABORTED},
            ("failed", 2, UNIQUE),
            id="server-error-in-block-wins-over-aborted-exit",
        ),
    ],
)
def test_verdict_decides_each_branch(observed, expected):
    # when
    shape = verdict_shape(**observed)
    # then
    assert shape == expected
