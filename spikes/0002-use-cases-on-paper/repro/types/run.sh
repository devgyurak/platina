#!/usr/bin/env bash
# Reruns the type reproduction of spike 0002 (see ../README.md). Glue written when the sources were
# moved here, not part of the reproducer's code. Usage, from the repository root:
#   bash spikes/0002-use-cases-on-paper/repro/types/run.sh [output dir]
# The output dir defaults to the git-ignored spikes/0002-use-cases-on-paper/results/repro-types.
set -euo pipefail

ROOT=$(pwd)
D=$ROOT/spikes/0002-use-cases-on-paper
R=${1:-$D/results/repro-types}
UV=(uv run --project "$ROOT")
MYPY=("${UV[@]}" mypy --strict --show-error-codes --no-incremental)
F16=(lib.pyi domain.py uc01_payment.py uc02_refund.py uc03_coupon_checkout.py
  uc04_stock_allocation.py uc05_seat_hold.py uc06_order_merge.py uc07_expire_orders.py
  uc08_transfer.py uc09_profile_edit.py uc10_payment_approval.py fail_findings.py
  probe_accepted.py probe_annotated_metadata.py probe_column_key.py)

mkdir -p "$R"

# a copy of the spike per variant, with the variant's patch applied to lib.pyi
for v in base hash tight tight-ref tight-after; do
  rm -rf "${R:?}/$v" && mkdir -p "$R/$v"
  cp "$D"/lib.pyi "$D"/domain.py "$D"/uc*.py "$D"/fail_findings.py "$D"/probe_*.py "$R/$v/"
  if [ "$v" != base ]; then patch -s "$R/$v/lib.pyi" < "$D/repro/types/patches/$v.patch"; fi
done
cp "$D"/repro/types/x*.py "$R/base/"

# the 16 files under both checkers, per variant (non-zero exits are expected: some files fail on purpose)
for v in base hash tight tight-ref tight-after; do
  (
    cd "$R/$v"
    "${UV[@]}" pyright "${F16[@]}" > "../$v-pyright-16.txt" || true
    "${MYPY[@]}" "${F16[@]}" > "../$v-mypy-16.txt" || true
  )
done

# the reproducer's probes
for p in x1_extra x13_reveal x51_same_type; do
  (
    cd "$R/base"
    "${UV[@]}" pyright "$p.py" > "../$p-pyright.txt" || true
    "${MYPY[@]}" "$p.py" > "../$p-mypy.txt" || true
  )
done

# spike 0001's pinned files against this stub, without and with hash.patch
for v in regress0001 regress0001-hash; do
  rm -rf "${R:?}/$v" && mkdir -p "$R/$v"
  cp "$ROOT"/spikes/0001-type-surface/round2/{domain,pass,fail}_final_declared.py "$R/$v/"
  cp "$D/lib.pyi" "$R/$v/lib_final_declared.pyi"
  if [ "$v" = regress0001-hash ]; then
    patch -s "$R/$v/lib_final_declared.pyi" < "$D/repro/types/patches/hash.patch"
  fi
  "${UV[@]}" python -m tools.typetests "$R/$v/lib_final_declared.pyi" \
    "$R/$v/domain_final_declared.py" "$R/$v/pass_final_declared.py" \
    "$R/$v/fail_final_declared.py" > "$R/$v.txt" 2>&1 || true
done

for f in "$R"/*-16.txt "$R"/x*-*.txt "$R"/regress0001*.txt; do
  printf '%s: %s\n' "$(basename "$f")" "$(tail -1 "$f")"
done
