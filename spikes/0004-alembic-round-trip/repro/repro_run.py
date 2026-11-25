"""Spike 0004 reproduction runner: `repro_run.py setup|teardown|<item> <config> <naming>`."""

import sys

import repro_harness as h

if __name__ == "__main__":
    if sys.argv[1] == "setup":
        h.create_db()
    elif sys.argv[1] == "teardown":
        print(h.drop_db())
    else:
        from repro_states import ITEMS

        item, config, naming = sys.argv[1:4]
        for sc in ITEMS[item]:
            h.run(sc, config, naming)
