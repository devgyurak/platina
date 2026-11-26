"""psycopg 3.3+ adapter: pool, pipeline mode, COPY, per-pool adapters (ADR-0012).

The only package that imports psycopg / psycopg_pool (guard A102). The contract it implements,
and the SQLSTATE mapping, live in ``platina.drivers`` without psycopg.
"""

from platina.drivers.psycopg.async_ import AsyncPsycopgDriver
from platina.drivers.psycopg.sync_ import SyncPsycopgDriver

__all__ = ["AsyncPsycopgDriver", "SyncPsycopgDriver"]
