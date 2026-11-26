#!/usr/bin/env bash
# Spike 0007 type reproduction (type-reviewer). Run from the repository root (pyright strict for
# spikes/ applies only inside the repository). Raw output: spikes/0007-.../results/repro-types/.
set -euo pipefail
D=spikes/0007-phase-1a-type-shapes/repro/types
R=spikes/0007-phase-1a-type-shapes/results/repro-types
mkdir -p "$R"
{ uv run python -V; uv run pyright --version; uv run mypy --version; } >"$R/versions.txt"

# 1. Lines both checkers agree on: stub, domain, S1-S8 (pass), F1-F20 + E1-E8 (fail), R1-R9 and
#    the flat path (both accept).
uv run python -m tools.typetests "$D/lib.pyi" "$D/domain.py" "$D/pass_repro.py" \
  "$D/fail_repro.py" "$D/pass_runtime_only.py" "$D/pass_flat_path.py" 2>&1 | tee "$R/typetests.txt"

# 2. Per checker: raw fail output, Annotated metadata, the Load.after owner join (G1-G6).
for f in fail_repro probe_annotated_repro probe_join probe_join_reveal; do
  (cd "$D" && uv run pyright "$f.py" >"../../results/repro-types/$f-pyright.txt" 2>&1 || true)
  (cd "$D" && uv run mypy --strict --show-error-codes --no-incremental "$f.py" \
    >"../../results/repro-types/$f-mypy.txt" 2>&1 || true)
done

# 3. Variants. RelOp with inferred variance: F11 (and E6) must now be "expected ..., got none".
uv run python -m tools.typetests "$D/variant_relop_inferred/fail_repro.py" \
  >"$R/variant-relop-inferred.txt" 2>&1 || true
#    Load.after(fn).load(*paths): the receiver fixes E; G1/G2/G4/F17 rejected by both.
uv run python -m tools.typetests "$D/variant_after_receiver/lib.pyi" \
  "$D/variant_after_receiver/fail_after_receiver.py" 2>&1 | tee "$R/variant-after-receiver.txt"
tail -n 1 "$R/variant-relop-inferred.txt"
