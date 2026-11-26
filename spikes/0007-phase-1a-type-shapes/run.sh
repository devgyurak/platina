#!/usr/bin/env bash
# Spike 0007: every type check of the write-up, from the repository root. Output: results/.
set -euo pipefail
D=spikes/0007-phase-1a-type-shapes
R=$D/results
mkdir -p "$R"

{ uv run python -V; uv run pyright --version; uv run mypy --version; } >"$R/versions.txt"

# 1. Stub, domain, the shape probes and the rewritten use cases under both checkers.
uv run python -m tools.typetests "$D/lib.pyi" "$D/domain.py" "$D/pass_shapes.py" \
  "$D/fail_shapes.py" "$D/probe_runtime_only.py" "$D/uc01_payment.py" "$D/uc02_refund.py" \
  "$D/uc03_coupon_checkout.py" "$D/uc04_stock_allocation.py" "$D/uc05_seat_hold.py" \
  "$D/uc06_order_merge.py" "$D/uc07_expire_orders.py" "$D/uc08_transfer_a.py" \
  "$D/uc08_transfer_b.py" "$D/uc09_profile_edit.py" "$D/uc10_payment_approval.py" 2>&1 \
  | tee "$R/typetests.txt"

# 2. The checkers disagree inside Annotated[...] metadata by design: run the probe directly.
(cd "$D" && uv run pyright probe_annotated.py >"results/probe_annotated-pyright.txt" 2>&1 || test $? -eq 1)
(cd "$D" && uv run mypy --strict --show-error-codes --no-incremental probe_annotated.py \
  >"results/probe_annotated-mypy.txt" 2>&1 || test $? -eq 1)
# Round 4 (independent review): `owned=` given a bool, and a declared type widening an owner.
for f in probe_owned_flag probe_owner_widen; do
  (cd "$D" && uv run pyright "$f.py" >"results/$f-pyright.txt" 2>&1 || test $? -eq 1)
  (cd "$D" && uv run mypy --strict --show-error-codes --no-incremental "$f.py" \
    >"results/$f-mypy.txt" 2>&1 || test $? -eq 1)
done

# 3. Variants: one TypeVar made covariant, nothing else changed. For each, the error lines of
#    fail_shapes.py are compared with the main stub's; the variant stub itself must stay clean
#    under both checkers.
errors() { # $1 dir -> "checker line" per error in fail_shapes.py, sorted
  (cd "$1" && uv run pyright --outputjson fail_shapes.py 2>/dev/null || test $? -eq 1) | uv run python -c '
import json, sys
d = json.load(sys.stdin)
for x in d["generalDiagnostics"]:
    if x["severity"] == "error":
        print("pyright", x["file"].rsplit("/", 1)[-1], x["range"]["start"]["line"] + 1)'
  (cd "$1" && uv run mypy --strict --show-error-codes --no-incremental fail_shapes.py 2>&1 || test $? -eq 1) \
    | sed -nE 's/^([^:]+):([0-9]+): error: .*/mypy \1 \2/p'
}
errors "$D" | sort -u >"$R/errors-main.txt"
for v in relop:_O_inv path:_P_inv; do
  name=${v%%:*} tv=${v##*:}
  V=$R/variant-$name-covariant
  rm -rf "$V" && mkdir -p "$V"
  cp "$D/domain.py" "$D/fail_shapes.py" "$V/"
  sed -E "s/^$tv = TypeVar\(\"$tv\"\)/$tv = TypeVar(\"$tv\", covariant=True)/" "$D/lib.pyi" >"$V/lib.pyi"
  if cmp -s "$D/lib.pyi" "$V/lib.pyi"; then echo "variant $name: substitution failed" >&2; exit 1; fi
  errors "$V" | sort -u >"$V/errors.txt"
  if grep -v ' fail_shapes.py ' "$V/errors.txt"; then echo "variant $name: errors outside fail_shapes.py" >&2; exit 1; fi
  # pyright does not report an imported stub's own diagnostics through fail_shapes.py: check it too
  if ! (cd "$V" && uv run pyright lib.pyi >pyright-stub.txt 2>&1); then
    echo "variant $name: the variant stub has pyright errors" >&2; exit 1
  fi
  echo "variant $name covariant - error lines lost (main - variant):" | tee "$R/variant-$name.txt"
  comm -23 "$R/errors-main.txt" "$V/errors.txt" | tee -a "$R/variant-$name.txt"
  echo "error lines gained (variant - main):" | tee -a "$R/variant-$name.txt"
  comm -13 "$R/errors-main.txt" "$V/errors.txt" | tee -a "$R/variant-$name.txt"
done

# 4. Round 6 (ADR-0011 probe): `Load.after(fn, missing=...) -> LoadAfter[E]` with the load
#    arguments on `.load(*paths: LoadPath[E])`, and no invariant `Path`. The build directory is
#    this directory's files with round6/ laid over them (round6/ holds only the changed and the
#    new files); everything the round-5 run checks is checked again against the round-6 stub.
B=$R/round6
rm -rf "$B" && mkdir -p "$B"
cp "$D"/*.py "$D/lib.pyi" "$B/"
cp "$D"/round6/*.py "$D/round6/lib.pyi" "$B/"
uv run python -m tools.typetests "$B/lib.pyi" "$B/domain.py" "$B/pass_shapes.py" \
  "$B/fail_shapes.py" "$B/probe_runtime_only.py" "$B/pass_r6.py" "$B/fail_r6.py" \
  "$B/uc01_payment.py" "$B/uc02_refund.py" "$B/uc03_coupon_checkout.py" \
  "$B/uc04_stock_allocation.py" "$B/uc05_seat_hold.py" "$B/uc06_order_merge.py" \
  "$B/uc07_expire_orders.py" "$B/uc08_transfer_a.py" "$B/uc08_transfer_b.py" \
  "$B/uc09_profile_edit.py" "$B/uc10_payment_approval.py" 2>&1 | tee "$R/round6-typetests.txt"
# Per checker: Annotated metadata (X1), the owner widening (W4/W5), and the full messages of the
# rejected lines (which argument each checker blames).
for f in probe_annotated probe_owner_widen probe_owner_variance probe_union_result fail_shapes \
  fail_r6; do
  (cd "$B" && uv run pyright "$f.py" >"results-$f-pyright.txt" 2>&1 || test $? -eq 1)
  (cd "$B" && uv run mypy --strict --show-error-codes --no-incremental "$f.py" \
    >"results-$f-mypy.txt" 2>&1 || test $? -eq 1)
done
# The owner variance and union-result probes against the round-5 stub, for comparison.
V=$R/round6-r5stub
rm -rf "$V" && mkdir -p "$V"
cp "$D/lib.pyi" "$D/domain.py" "$D/round6/probe_owner_variance.py" "$D/round6/probe_union_result.py" "$V/"
for f in probe_owner_variance probe_union_result; do
  (cd "$V" && uv run pyright "$f.py" >"results-$f-pyright.txt" 2>&1 || test $? -eq 1)
  (cd "$V" && uv run mypy --strict --show-error-codes --no-incremental "$f.py" \
    >"results-$f-mypy.txt" 2>&1 || test $? -eq 1)
done
