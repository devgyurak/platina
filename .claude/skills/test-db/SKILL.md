---
name: test-db
description: Start, stop, reset and troubleshoot the docker-compose PostgreSQL used by integration tests and spikes. Use when tests or spikes cannot connect, or a clean database is needed.
---
# Test database

| Profile | Service | Host port | Use for |
|---|---|---|---|
| fast | `postgres` | 26432 | integration tests; spikes asking "does X happen at all" |
| durable | `postgres-durable` | 26433 | anything that measures rates, throughput or latency |

Both: PostgreSQL 18, user / password / database `platina` / `platina` / `platina`, e.g.
`postgresql://platina:platina@localhost:26432/platina`. The fast profile lives on tmpfs (a
restart wipes it) with `fsync` and `full_page_writes` off; that shortens commits and therefore the
window in which transactions overlap, so it would understate conflict and retry rates. The
durable profile keeps default durability on a named volume. Isolation, SSI and
`synchronous_commit` keep PostgreSQL's defaults in both.

```bash
make db-up           # fast profile, waits for the healthcheck
make db-up-durable   # durable profile
make db-down      # stop both (the fast one is wiped; the durable volume is kept)
make db-reset     # down + up
make db-psql      # psql shell
make test-int     # integration tests
```

Integration tests (`tests/integration/`, the `integration` marker applied by its `conftest.py`)
connect with `PLATINA_TEST_DSN` (default: the fast profile,
`postgresql://platina:platina@localhost:26432/platina`) and get one empty database per test
(`CREATE DATABASE`, dropped `WITH (FORCE)` afterwards); each test creates its own tables. The
server is shared, so tests never touch other databases. Still to come (#20): a migrated template
cloned per test (`CREATE DATABASE ... TEMPLATE`, design section 11.5), a template per
pytest-xdist worker, and the nightly PostgreSQL 14-18 matrix.

## Troubleshooting
- `connection refused` -> `docker compose ps`; port clash -> stop the other service or change the
  host port in `docker-compose.yml` **and** every document that mentions 26432 (docs-sync rule).
- `too many connections` during concurrency spikes -> `max_connections` is 300; check for leaked
  connections before raising it.
- `all predefined address pools have been fully subnetted` -> Docker ran out of networks for new
  compose projects (too many leftover networks). Ask the maintainer before pruning: it affects
  other projects on the machine.
- Wipe the durable volume: `docker compose --profile durable down -v`.
