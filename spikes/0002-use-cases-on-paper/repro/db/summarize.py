# TEMPORARY (spike 0002): the reproducer's code below is kept byte-identical, so lint and
# formatting are suppressed for this file until the maintainer decides how to treat it.
# ruff: noqa: SIM115
# fmt: off
"""Condense SUMMARY lines of part_c output: one line per scenario, short."""
import re
import sys

for line in open(sys.argv[1]):
    if not line.startswith("SUMMARY"):
        continue
    f = [x.strip() for x in line.split(" | ")]
    label, order, inter, first, read, data = f[1], f[3].replace("write order ", ""), f[4], f[5].replace("first writer ", ""), f[6].replace("step-2 read by ", ""), f[7].replace("data ", "")
    rest = f[8:]
    io = rest.pop(0).replace("index order ", "")
    p1 = rest[0].replace("plan1: ", "").split(";")[0]
    p2 = rest[1].replace("plan2: ", "").split(";")[0]

    def sh(x: str) -> str:
        x = re.sub(r"\(after an observed lock wait at: ([A-Z]+)[^)]*\)+", r"(waited at \1)", x)
        x = x.replace("(no lock wait)", "").replace("SerializationFailure: ", "").replace("UniqueViolation: ", "")
        x = x.replace("could not serialize access due to ", "")
        return x.strip()
    print(f"{label:20} {order:2} {inter:14} first={first} data={data:3} read={read:4} idx={io:16} | {sh(rest[2])} | {sh(rest[3])} | {rest[4].replace('final ', '').replace('redemptions(coupon 1) users=', 'red=')} | {p1} / {p2}")
