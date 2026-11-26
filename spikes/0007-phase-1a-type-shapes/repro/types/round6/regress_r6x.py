"""Round 6, stage 4: does every round-5 line keep its verdict on the reproducer's stub?

Usage: python regress_r6x.py SPIKE REPRO RESULTS. Copies the author's round-5 files (SPIKE, not
SPIKE/round6) into RESULTS/r5files-main (with the round-5 stub) and RESULTS/r5files-mine (with
REPRO's stub), lists the errors of both checkers as `checker file line code` with errors_r6x.py,
and prints the lines that differ. Exits 2 when a checker crashed.
"""

import shutil
import subprocess
import sys
from pathlib import Path

FILES = [
    "pass_shapes.py",
    "fail_shapes.py",
    "probe_runtime_only.py",
    "uc01_payment.py",
    "uc02_refund.py",
    "uc03_coupon_checkout.py",
    "uc04_stock_allocation.py",
    "uc05_seat_hold.py",
    "uc06_order_merge.py",
    "uc07_expire_orders.py",
    "uc08_transfer_a.py",
    "uc08_transfer_b.py",
    "uc09_profile_edit.py",
    "uc10_payment_approval.py",
    "probe_annotated.py",
    "probe_owned_flag.py",
    "probe_owner_widen.py",
]


def errors(build: Path, helper: Path) -> set[str]:
    r = subprocess.run(
        [sys.executable, str(helper), str(build), *FILES], capture_output=True, text=True
    )
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        sys.exit(2)
    return set(r.stdout.splitlines())


def main() -> int:
    spike, repro, results = (Path(a) for a in sys.argv[1:4])
    found: dict[str, set[str]] = {}
    for name, stub in (("main", spike.joinpath("lib.pyi")), ("mine", repro.joinpath("lib.pyi"))):
        build = results.joinpath(f"r5files-{name}")
        build.mkdir(parents=True, exist_ok=True)
        for f in [*FILES, "domain.py"]:
            shutil.copy(spike.joinpath(f), build)
        shutil.copy(stub, build.joinpath("lib.pyi"))
        found[name] = errors(build, repro.joinpath("errors_r6x.py"))
        results.joinpath(f"r5files-{name}.txt").write_text("\n".join(sorted(found[name])) + "\n")
    print("== lost with the reproducer's stub (main - mine):")
    print("\n".join(sorted(found["main"] - found["mine"])))
    print("== gained with the reproducer's stub (mine - main):")
    print("\n".join(sorted(found["mine"] - found["main"])))
    return 0


if __name__ == "__main__":
    sys.exit(main())
