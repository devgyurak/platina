#!/usr/bin/env bash
# ADR-0010 PostgreSQL experiments (spike 0007 addendum), from the repository root.
# Fast profile only (SPIKE_PG_DSN, default postgresql://platina:platina@localhost:26432/platina);
# every script creates and drops its own temporary database. Raw logs: results/addendum-pg/
# (git-ignored). Takes about 10 minutes.
set -euo pipefail
P=spikes/0007-phase-1a-type-shapes/addendum/pg
W=spikes/0007-phase-1a-type-shapes/results/addendum-pg
rm -rf "$W" && mkdir -p "$W"
run() { # name, args...
  local name=$1
  shift
  echo "== $name $*"
  uv run --group spike python "$P/$name.py" "$@" >"$W/$name.log" 2>&1
}
{ uv run --group spike python -V; uv run --group spike python -c \
  "import psycopg; print('psycopg', psycopg.__version__, psycopg.pq.__impl__, 'libpq', psycopg.pq.version())"; } \
  >"$W/versions.txt"
run q1 3                 # F1: plain child INSERT vs cascade delete, SERIALIZABLE and REPEATABLE READ
run q1e 3                # F1 (e): INSERT after the delete committed
run q2 5                 # F2: 23503 from a non-owned referrer - timing, diag, pipeline mode
run q3locks              # F3 + N3: SIRead locks (separate / root-only / CTE)
run q3pin 3              # F3: pinned interleavings with the zero-row child DELETE
run q3load 3 6 uuid4,uuid7 with,without,pad # F3: 40001 rates under a small load
run q4 3                 # F4: versioned root DELETE matching zero rows
run q4pipe 3             # F4 in pipeline mode
run n1_cte 3             # N1: one CTE statement for cascade + root
run n2_race 3            # N2: child INSERT + root bump racing the deleter
run n3_review 3           # N3: two root tables referencing each other; a non-owned insert racing the delete
echo "logs in $W"
