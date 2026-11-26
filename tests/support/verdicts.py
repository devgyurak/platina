"""Helpers for the ``verdict`` truth table (``tests/integration/drivers/test_psycopg_common.py``).

``verdict`` returns a reply, ``Abandon`` (close, reply ``Lost``) or ``Propagate`` (raise). The
table compares a small shape of it - the kind, the failure position and which exception the
fault came from - so each row states one branch without building whole faults.
"""

from __future__ import annotations

from platina.drivers.interface import Completed, Failed, Lost, StatementResult
from platina.drivers.psycopg._common import Abandon, Propagate, verdict

type Shape = tuple[str, int | None, BaseException | None]


def verdict_shape(
    *,
    unclean: bool = False,
    statements: int,
    sent: int,
    received: tuple[StatementResult, ...],
    stopped_ran: bool = False,
    in_block: Exception | None = None,
    at_exit: Exception | None = None,
) -> Shape:
    """``(kind, at, cause)``: ``("completed", n, None)``, ``("failed", at, cause)``,
    ``("abandon", None, cause)`` (``cause`` ``None`` for the driver's own "unknown state" fault),
    ``("propagate", None, error)``."""
    outcome = verdict(
        unclean=unclean,
        statements=statements,
        sent=sent,
        received=received,
        stopped_ran=stopped_ran,
        in_block=in_block,
        at_exit=at_exit,
    )
    match outcome:
        case Completed(results):
            return ("completed", len(results), None)
        case Failed(results, fault):
            return ("failed", len(results), fault.cause)
        case Abandon(fault):
            own = fault.message == "the connection was left in an unknown state"
            return ("abandon", None, None if own else fault.cause)
        case Propagate(error):
            return ("propagate", None, error)
        case Lost():
            raise AssertionError("verdict never replies Lost itself; it returns Abandon")
