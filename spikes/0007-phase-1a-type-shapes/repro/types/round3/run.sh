#!/usr/bin/env bash
# Spike 0007 type reproduction, round 3 (type-reviewer). Run from the repository root.
# Raw output: spikes/0007-phase-1a-type-shapes/results/repro-types/round3/.
set -euo pipefail
D=spikes/0007-phase-1a-type-shapes/repro/types/round3
R=spikes/0007-phase-1a-type-shapes/results/repro-types/round3
mkdir -p "$R"
ROOT=$PWD
{ uv run python -V; uv run pyright --version; uv run mypy --version; } >"$R/versions.txt"

# 1. Both checkers agree: stub, domain, S1-S8 (pass), F1-F29 + E1-E14 (fail), nullable nested loads, R1-R15 (accepted).
uv run python -m tools.typetests "$D/lib.pyi" "$D/domain.py" "$D/pass_r2.py" "$D/pass_nullable.py" "$D/fail_r2.py" \
  "$D/pass_runtime_r2.py" "$D/pass_flat_path.py" 2>&1 | tee "$R/typetests.txt"

# 2. Per checker: raw fail output and Annotated metadata.
for f in fail_r2 probe_annotated_repro; do
  (cd "$D" && uv run pyright "$f.py" >"$ROOT/$R/$f-pyright.txt" 2>&1 || test $? -eq 1)
  (cd "$D" && uv run mypy --strict --show-error-codes --no-incremental "$f.py" \
    >"$ROOT/$R/$f-mypy.txt" 2>&1 || test $? -eq 1)
done

# 3. Variants: one TypeVar made covariant each; print error lines lost / gained.
for v in path relop; do
  rm -rf "$D/variant_$v" && mkdir -p "$D/variant_$v"
  cp "$D/domain.py" "$D/pass_r2.py" "$D/pass_nullable.py" "$D/fail_r2.py" "$D/variant_$v/"
done
uv run python - "$D" <<'PY'
import sys
from pathlib import Path
d = Path(sys.argv[1]); s = (d / "lib.pyi").read_text()
for v, o in (("path", '_P_inv = TypeVar("_P_inv")'), ("relop", '_O_inv = TypeVar("_O_inv")')):
    assert s.count(o) == 1, o
    (d / f"variant_{v}" / "lib.pyi").write_text(s.replace(o, o[:-1] + ", covariant=True)"))
PY
for x in . variant_path variant_relop; do
  uv run python "$D/lines.py" "$D/$x" lib.pyi domain.py pass_r2.py pass_nullable.py fail_r2.py >"$R/lines-$(basename "$x").txt"
done
mv "$R/lines-..txt" "$R/lines-main.txt"
for v in variant_path variant_relop; do
  echo "== $v lost (main - variant):"; comm -23 "$R/lines-main.txt" "$R/lines-$v.txt"
  echo "== $v gained (variant - main):"; comm -13 "$R/lines-main.txt" "$R/lines-$v.txt"
done | tee "$R/variants.txt"
