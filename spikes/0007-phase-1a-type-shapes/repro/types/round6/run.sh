#!/usr/bin/env bash
# Spike 0007 type reproduction, round 6 (type-reviewer): the receiver form of `Load.after`.
set -euo pipefail
S=spikes/0007-phase-1a-type-shapes
D=$S/repro/types/round6
R=$S/results/repro-types/round6
ROOT=$PWD
rm -rf "$R" && mkdir -p "$R"
{ uv run python -V; uv run pyright --version; uv run mypy --version; } >"$R/versions.txt"
shasum -a 256 "$S/lib.pyi" "$S/domain.py" "$D/lib.pyi" "$D/domain.py" "$S/round6/lib.pyi" >"$R/hashes.txt"
diff "$S/lib.pyi" "$D/lib.pyi" >"$R/stub-diff.txt" || test $? -eq 1

# 1. Both checkers agree: the reproducer's stub, the domain, Q1/Q2 and own lines.
uv run python -m tools.typetests "$D/lib.pyi" "$D/domain.py" "$D/pass_r6x.py" "$D/fail_r6x.py" 2>&1 \
  | tee "$R/typetests.txt"

# 2. Per checker on the reproducer's stub: Annotated (X1), widening (W1-W16), variance (V1-V5).
#    Both checkers resolve the lib import to the stub next to the checked file. A checker exit
#    other than 0 or 1 (a crash, a missing file) fails the script.
for f in probe_annotated_r6x probe_widen_r6x probe_variance_r6x; do
  uv run pyright "$D/$f.py" >"$R/$f-pyright.txt" 2>&1 || test $? -eq 1
  uv run mypy --strict --show-error-codes --no-incremental "$D/$f.py" >"$R/$f-mypy.txt" 2>&1 \
    || test $? -eq 1
done

# 3. The variance probe against the round-5 stub (with the invariant Path).
mkdir -p "$R/r5stub"
cp "$S/lib.pyi" "$S/domain.py" "$D/probe_variance_r6x.py" "$R/r5stub/"
uv run pyright "$R/r5stub/probe_variance_r6x.py" >"$R/r5stub/probe_variance_r6x-pyright.txt" 2>&1 \
  || test $? -eq 1
uv run mypy --strict --show-error-codes --no-incremental "$R/r5stub/probe_variance_r6x.py" \
  >"$R/r5stub/probe_variance_r6x-mypy.txt" 2>&1 || test $? -eq 1

# 4. "Every other round-5 line keeps its verdict": the author's round-5 files (not round6/) with
#    the round-5 stub and with the reproducer's stub; the errors (checker file line code) that
#    differ are printed. Only `Load.after(fn, path, ...)` lines may differ.
uv run python "$D/regress_r6x.py" "$S" "$D" "$R" | tee "$R/r5files-diff.txt"

# 5. W6-W8 in round 5's form, against the round-5 stub: is the widening new in round 6?
cp "$D/probe_widen_r5form_x.py" "$R/r5stub/"
uv run pyright "$R/r5stub/probe_widen_r5form_x.py" >"$R/r5stub/probe_widen_r5form_x-pyright.txt" 2>&1 \
  || test $? -eq 1
uv run mypy --strict --show-error-codes --no-incremental "$R/r5stub/probe_widen_r5form_x.py" \
  >"$R/r5stub/probe_widen_r5form_x-mypy.txt" 2>&1 || test $? -eq 1

# 6. Variant: LoadAfter.load takes round 5's invariant Path[E] (Relation.load keeps LoadPath).
#    Does it close W6-W8 and W14, and do the pass/fail files keep their verdicts?
mkdir -p "$R/variant_path"
uv run python "$D/variant_r6x.py" "$D/lib.pyi" "$R/variant_path/lib.pyi"
cp "$D/domain.py" "$D/pass_r6x.py" "$D/fail_r6x.py" "$D/probe_widen_r6x.py" "$R/variant_path/"
uv run python -m tools.typetests "$R/variant_path/lib.pyi" "$R/variant_path/pass_r6x.py" \
  "$R/variant_path/fail_r6x.py" >"$R/variant_path/typetests.txt" 2>&1 || test $? -eq 1
uv run pyright "$R/variant_path/probe_widen_r6x.py" >"$R/variant_path/probe_widen_r6x-pyright.txt" 2>&1 \
  || test $? -eq 1
uv run mypy --strict --show-error-codes --no-incremental "$R/variant_path/probe_widen_r6x.py" \
  >"$R/variant_path/probe_widen_r6x-mypy.txt" 2>&1 || test $? -eq 1

# 7. The reproducer's files against the author's round-6 stub (only `round6/lib.pyi` is read;
#    the author's run.sh need not have run).
mkdir -p "$R/author_stub"
cp "$S/round6/lib.pyi" "$D/domain.py" "$D/pass_r6x.py" "$D/fail_r6x.py" "$R/author_stub/"
for f in probe_annotated_r6x probe_widen_r6x probe_variance_r6x; do cp "$D/$f.py" "$R/author_stub/"; done
uv run python -m tools.typetests "$R/author_stub/pass_r6x.py" "$R/author_stub/fail_r6x.py" 2>&1 \
  | tee "$R/author_stub/typetests.txt"
for f in probe_annotated_r6x probe_widen_r6x probe_variance_r6x; do
  uv run pyright "$R/author_stub/$f.py" >"$R/author_stub/$f-pyright.txt" 2>&1 || test $? -eq 1
  uv run mypy --strict --show-error-codes --no-incremental "$R/author_stub/$f.py" \
    >"$R/author_stub/$f-mypy.txt" 2>&1 || test $? -eq 1
done

# 8. Union results (write-up N1 / N2, the reproducer's N3x-N8x, C1x, M1x-M8x). The no-path probe
#    runs against all three stubs; the path probes against the stub of their form. A checker exit
#    other than 0 or 1 fails the script.
U=$R/union
mkdir -p "$U/r6stub" "$U/r5stub" "$U/author_stub"
cp "$D/lib.pyi" "$D/domain.py" "$D/probe_union_r6x.py" "$D/probe_union_paths_r6x.py" "$U/r6stub/"
cp "$S/round6/lib.pyi" "$D/domain.py" "$D/probe_union_r6x.py" "$D/probe_union_paths_r6x.py" \
  "$U/author_stub/"
cp "$S/lib.pyi" "$S/domain.py" "$D/probe_union_r6x.py" "$D/probe_union_paths_r5form_x.py" "$U/r5stub/"
for p in r6stub/probe_union_r6x r6stub/probe_union_paths_r6x author_stub/probe_union_r6x \
  author_stub/probe_union_paths_r6x r5stub/probe_union_r6x r5stub/probe_union_paths_r5form_x; do
  uv run pyright "$U/$p.py" >"$U/$p-pyright.txt" 2>&1 || test $? -eq 1
  uv run mypy --strict --show-error-codes --no-incremental "$U/$p.py" >"$U/$p-mypy.txt" 2>&1 \
    || test $? -eq 1
done
