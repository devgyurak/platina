#!/usr/bin/env bash
# Spike 0007 addendum (ADR-0010) - independent type reproduction (type-reviewer).
# Run from the repository root (pyright strict applies to spikes/ only inside the repository).
# Sources: this directory. Raw output: spikes/0007-.../results/repro-types/addendum/ (git-ignored).
set -euo pipefail
S=spikes/0007-phase-1a-type-shapes
D=$S/repro/types/addendum
R=$S/results/repro-types/addendum
rm -rf "$R" && mkdir -p "$R"
{ uv run python -V; uv run pyright --version; uv run mypy --version; } >"$R/versions.txt"

# 0. Inputs: the spike's stub and domain this repro started from, and the copy's diff.
shasum -a 256 "$S/lib.pyi" "$S/domain.py" "$D/lib.pyi" "$D/domain.py" >"$R/hashes.txt"
cmp -s "$S/domain.py" "$D/domain.py" || { echo "domain.py differs from the spike's" >&2; exit 1; }
diff "$S/lib.pyi" "$D/lib.pyi" >"$R/lib.diff" || true

# 1. A1 / A2 / A3 probes: both checkers, every marked line with the expected codes.
uv run python -m tools.typetests "$D/lib.pyi" "$D/domain.py" "$D/domain_x.py" "$D/pass_x.py" \
  "$D/fail_x.py" 2>&1 | tee "$R/typetests-probes.txt"

# 2. A1 (iii): every file of the spike on the [0010] stub. The spike files are copied next to the
#    [0010] stub (mypy cannot take two `lib` modules in one run); the baseline uses the spike's stub.
SPIKE_FILES="domain.py pass_shapes.py fail_shapes.py probe_runtime_only.py uc01_payment.py
  uc02_refund.py uc03_coupon_checkout.py uc04_stock_allocation.py uc05_seat_hold.py
  uc06_order_merge.py uc07_expire_orders.py uc08_transfer_a.py uc08_transfer_b.py
  uc09_profile_edit.py uc10_payment_approval.py"
for v in baseline:"$S/lib.pyi" narrowed:"$D/lib.pyi"; do
  name=${v%%:*} stub=${v#*:}
  V=$R/spike-$name && mkdir -p "$V"
  cp "$stub" "$V/lib.pyi"
  args=("$V/lib.pyi")
  for f in $SPIKE_FILES; do cp "$S/$f" "$V/$f"; args+=("$V/$f"); done
  uv run python -m tools.typetests "${args[@]}" 2>&1 | tee "$R/typetests-spike-$name.txt"
done

# 3. Beyond the claims: raw per-checker output of probe_x.py (reveal_type, no markers).
(cd "$D" && uv run pyright probe_x.py >"../../../results/repro-types/addendum/probe_x-pyright.txt" 2>&1 || true)
(cd "$D" && uv run mypy --strict --show-error-codes --no-incremental probe_x.py \
  >"../../../results/repro-types/addendum/probe_x-mypy.txt" 2>&1 || true)

# 4. Variant: RowSet's entity bounded by Entity (`_E_inv = TypeVar("_E_inv", bound=Entity)`).
#    P5/P6 of probe_x.py must now fail in both; every spike file and probe must keep its verdict.
B=$R/variant-rowset-bound && mkdir -p "$B"
sed -E 's/^_E_inv = TypeVar\("_E_inv"\)/_E_inv = TypeVar("_E_inv", bound=Entity)/' "$D/lib.pyi" >"$B/lib.pyi"
if cmp -s "$D/lib.pyi" "$B/lib.pyi"; then echo "rowset variant: substitution failed" >&2; exit 1; fi
for f in domain.py domain_x.py pass_x.py fail_x.py probe_x.py; do cp "$D/$f" "$B/$f"; done
bargs=("$B/lib.pyi" "$B/domain.py" "$B/domain_x.py" "$B/pass_x.py" "$B/fail_x.py")
for f in $SPIKE_FILES; do [ "$f" = domain.py ] || { cp "$S/$f" "$B/$f"; bargs+=("$B/$f"); }; done
uv run python -m tools.typetests "${bargs[@]}" 2>&1 | tee "$R/typetests-variant-rowset-bound.txt"
(cd "$B" && uv run pyright probe_x.py >probe_x-pyright.txt 2>&1 || true)
(cd "$B" && uv run mypy --strict --show-error-codes --no-incremental probe_x.py >probe_x-mypy.txt 2>&1 || true)

# 5. Summary lines.
for f in "$R"/typetests-*.txt; do printf '%s: %s\n' "${f##*/}" "$(tail -n 1 "$f")"; done
