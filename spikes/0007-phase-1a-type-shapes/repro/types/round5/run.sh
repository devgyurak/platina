#!/usr/bin/env bash
# Spike 0007 type reproduction, round 5 (type-reviewer). Run from the repository root.
# Raw output: spikes/0007-phase-1a-type-shapes/results/repro-types/round5/. A checker exit other
# than 0 or 1 (a crash, a missing file) fails the script.
set -euo pipefail
D=spikes/0007-phase-1a-type-shapes/repro/types/round5
R=spikes/0007-phase-1a-type-shapes/results/repro-types/round5
mkdir -p "$R"
ROOT=$PWD
{ uv run python -V; uv run pyright --version; uv run mypy --version; } >"$R/versions.txt"

# 1. Both checkers agree: rounds 1-4's files (E13 and R17 adapted to where(pred, /, *preds)),
#    pass_r5 (R17 with an unpacked list, relation where, query path) and fail_r5 (F32-F34, H1, H2).
uv run python -m tools.typetests "$D/lib.pyi" "$D/domain.py" "$D/pass_r2.py" "$D/pass_nullable.py" \
  "$D/pass_r4.py" "$D/pass_r5.py" "$D/fail_r2.py" "$D/fail_r4.py" "$D/fail_r5.py" "$D/pass_runtime_r2.py" "$D/pass_runtime_r4.py" \
  "$D/pass_flat_path.py" 2>&1 | tee "$R/typetests.txt"

# 2. Per checker: Annotated metadata; owned= with a bool (round 4) and with constants (round 5, a).
for f in probe_annotated_repro probe_owned_flag_repro probe_owned_flag_r5; do
  (cd "$D" && uv run pyright "$f.py" >"$ROOT/$R/$f-pyright.txt" 2>&1 || test $? -eq 1)
  (cd "$D" && uv run mypy --strict --show-error-codes --no-incremental "$f.py" \
    >"$ROOT/$R/$f-mypy.txt" 2>&1 || test $? -eq 1)
done

# 3. Variants: one TypeVar made covariant each; error lines lost / gained.
F="lib.pyi domain.py pass_r2.py pass_nullable.py pass_r4.py pass_r5.py fail_r2.py fail_r4.py fail_r5.py"
for v in path relop; do
  rm -rf "$D/variant_$v" && mkdir -p "$D/variant_$v"
  for f in $F; do [ "$f" = lib.pyi ] || cp "$D/$f" "$D/variant_$v/"; done
done
uv run python - "$D" <<'PY'
import sys
from pathlib import Path
d = Path(sys.argv[1]); s = (d / "lib.pyi").read_text()
for v, o in (("path", '_P_inv = TypeVar("_P_inv")'), ("relop", '_O_inv = TypeVar("_O_inv")')):
    assert s.count(o) == 1, o
    (d / f"variant_{v}" / "lib.pyi").write_text(s.replace(o, o[:-1] + ", covariant=True)"))
PY
uv run python "$D/lines.py" "$D" $F >"$R/lines-main.txt"
for v in variant_path variant_relop; do
  uv run python "$D/lines.py" "$D/$v" $F >"$R/lines-$v.txt"
  echo "== $v lost (main - variant):"; comm -23 "$R/lines-main.txt" "$R/lines-$v.txt"
  echo "== $v gained (variant - main):"; comm -13 "$R/lines-main.txt" "$R/lines-$v.txt"
done | tee "$R/variants.txt"
