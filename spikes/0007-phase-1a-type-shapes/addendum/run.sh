#!/usr/bin/env bash
# Spike 0007 addendum for ADR-0010, from the repository root. Output: results/addendum/ (git-ignored).
# Assembles one directory with the addendum stub, the spike's unchanged domain, probes and use
# cases, and the addendum probes, then runs every file through both checkers (tools/typetests).
set -euo pipefail
D=spikes/0007-phase-1a-type-shapes
A=$D/addendum
W=$D/results/addendum
rm -rf "$W" && mkdir -p "$W"
{ uv run python -V; uv run pyright --version; uv run mypy --version; } >"$W/versions.txt"
cp "$A/lib.pyi" "$A/domain_addendum.py" "$A/pass_addendum.py" "$A/fail_addendum.py" "$W/"
cp "$D/domain.py" "$D/pass_shapes.py" "$D/fail_shapes.py" "$D/probe_runtime_only.py" "$D"/uc*.py "$W/"
sha256sum "$D/lib.pyi" "$A/lib.pyi" "$D/domain.py" >"$W/hashes.txt"
diff "$D/lib.pyi" "$A/lib.pyi" >"$W/stub.diff" || test $? -eq 1
# shellcheck disable=SC2046
uv run python -m tools.typetests $(cd "$W" && ls lib.pyi domain.py domain_addendum.py *.py | sort -u | sed "s|^|$W/|") 2>&1 \
  | tee "$W/typetests.txt"
