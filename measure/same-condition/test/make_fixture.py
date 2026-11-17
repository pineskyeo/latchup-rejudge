#!/usr/bin/env python3
"""Expected judgment from latchup_rejudge.py for the C++ equivalence test.

Writes one block per case:
    name n_grid sign
    V values (m points)
    nsnap vt vh vt1 vh1 leg_vt leg_vh     (0-based indices, -1 = none)
"""
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.normpath(os.path.join(HERE, "..", "..", ".."))
sys.path.insert(0, ROOT)
import latchup_rejudge as L  # noqa: E402

FIND_START, DV_ABS, DV_REL, MAIN_FRAC = 6, 0.05, 0.03, 0.7


def case(name, v, sign, n_grid):
    i = [sign * 1e-7 * 1.05 ** (k + 1) for k in range(len(v))]
    res, ev, _ = L.new_judge(v, i, FIND_START, DV_ABS, DV_REL, 0.5, 3,
                             rule="main", main_frac=MAIN_FRAC)
    leg = L.legacy_judge(v, i, FIND_START, pad_to=n_grid)
    idx = lambda num: -1 if num is None else num - 1
    vt1, vh1 = (ev[0] if ev else (-1, -1))
    return "%s %d %d\n%s\n%d %d %d %d %d %d %d\n" % (
        name, n_grid, sign, " ".join(repr(x) for x in v), len(ev),
        idx(res["VT_NUM"]), idx(res["VH_NUM"]), vt1, vh1,
        idx(leg["VT_NUM"]), idx(leg["VH_NUM"]))


def main(out):
    curves = L.read_curves([os.path.join(ROOT, "examples", "sample_lup.log")])
    blocks = []
    for c in curves:
        name = "%s_run%d" % (c["key"][-1], c["run"])
        v = c["v"]
        sign = -1 if L.polarity(c["i"]) < 0 else 1
        blocks.append(case(name, v, sign, len(v)))
    # negative injection: same shapes, flipped sign
    v0 = curves[1]["v"]
    blocks.append(case("negative", [-x for x in v0], -1, len(v0)))
    # stop on I1end before the grid ends: legacy scans the zero tail
    blocks.append(case("early_stop", curves[1]["v"][:200], 1, 260))
    # no snapback at all
    blocks.append(case("monotonic", [0.01 * k for k in range(80)], 1, 80))
    with open(out, "w") as f:
        f.write("".join(blocks))
    print("%d cases -> %s" % (len(blocks), out))


if __name__ == "__main__":
    main(sys.argv[1])
