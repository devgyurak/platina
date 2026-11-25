#!/usr/bin/env bash
# Reruns the database reproduction of spike 0002 (see ../README.md). Glue written when the sources
# were moved here, not part of the reproducer's code. Needs `make db-up` (port 26432, or
# PLATINA_TEST_DSN). Usage, from the repository root:
#   bash spikes/0002-use-cases-on-paper/repro/db/run.sh [output dir] [part ...]
# Parts: a b c (default: all). The output dir defaults to the git-ignored
# spikes/0002-use-cases-on-paper/results/repro-db.
set -euo pipefail

ROOT=$(pwd)
D=$ROOT/spikes/0002-use-cases-on-paper
S=$D/repro/db
R=${1:-$D/results/repro-db}
shift || true
PARTS=("${@:-a b c}")
PY=(uv run --project "$ROOT" python)
mkdir -p "$R"

for part in ${PARTS[*]}; do
  case "$part" in
    a)
      "${PY[@]}" "$S/part_a.py" > "$R/partA-verified.txt"
      "${PY[@]}" "$D/db_increment_conflicts.py" > "$R/partA-original-script.txt"
      ;;
    b)
      "${PY[@]}" "$S/part_b.py" > "$R/partB.txt"
      "${PY[@]}" "$S/part_b_three.py" > "$R/partB-three-sessions.txt"
      "${PY[@]}" "$S/part_b_timeout.py" > "$R/partB-timeout.txt"
      ;;
    c)
      "${PY[@]}" "$S/part_c.py" asked > "$R/partC-asked.txt"
      "${PY[@]}" "$S/part_c.py" extra > "$R/partC-extra.txt"
      "${PY[@]}" "$S/summarize.py" "$R/partC-asked.txt" > "$R/partC-asked-summary.txt"
      "${PY[@]}" "$S/summarize.py" "$R/partC-extra.txt" > "$R/partC-extra-summary.txt"
      ;;
    *) echo "unknown part: $part" >&2; exit 2 ;;
  esac
done
ls -1 "$R"
