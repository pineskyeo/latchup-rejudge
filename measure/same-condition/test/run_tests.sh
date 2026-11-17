#!/usr/bin/env bash
# Build and run the "same measurement, fixed judgment" equivalence test.
#   CORTEX  cortex checkout (default ../../../../cortex): stub TIS + original
#           latchup_supply_io for the measurement-unchanged check
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CORTEX="${CORTEX:-$HERE/../../../../cortex}"
ALG="$CORTEX/sdk/algorithms"
OUT="${TMPDIR:-/tmp}/lup3rj_test"
mkdir -p "$OUT"
rm -f "$OUT"/*_LUP.log

# 1. the judgment block is pasted into POR and DOE: it must be identical
blk() { sed -n '/^\/\* ---- judgment/,/^\/\* ---- end judgment/p' "$1"; }
if ! diff <(blk "$HERE/../por/P9K_M_latchup3_rj.cpp") <(blk "$HERE/../doe/latchup_supply_io_rj.cpp") >/dev/null; then
    echo "FAIL: judgment block differs between POR and DOE"; exit 1
fi
echo "ok:   judgment block identical in POR and DOE"

# 2. expected values from latchup_rejudge.py
python3 "$HERE/make_fixture.py" "$OUT/fixture.txt"

# 3. C++ equivalence
g++ -std=gnu++98 -Wall -Wextra \
    -I"$HERE/stub" -I"$ALG/latchup__supply_io" \
    -DCORTEX_STUB_TIS="\"$ALG/test/stub/tis.h\"" \
    -DCORTEX_ORIG_SRC="\"$ALG/latchup__supply_io/latchup_supply_io.cpp\"" \
    -DLUP_LOG_DIR="\"$OUT/\"" \
    -o "$OUT/test_same_condition" "$HERE/test_same_condition.cpp"
"$OUT/test_same_condition" "$OUT/fixture.txt"

# 4. the POR LUP log keeps the legacy format: latchup_rejudge.py reads it back
python3 - "$OUT" "$HERE/../../.." <<'PY'
import glob, os, sys
out, root = sys.argv[1], sys.argv[2]
sys.path.insert(0, root)
import latchup_rejudge as L
logs = glob.glob(os.path.join(out, "*_LUP.log"))
assert len(logs) == 1, logs
curves = L.read_curves(logs)
lines = open(os.path.join(out, "fixture.txt")).read().splitlines()
exp = {lines[k].split()[0]: lines[k + 1].split() for k in range(0, len(lines), 3)}
assert len(curves) == len(exp), (len(curves), len(exp))
for c in curves:
    v = exp[c["key"][-1]]
    assert len(c["v"]) == len(v) and all(abs(float(a) - b) < 1e-9 for a, b in zip(v, c["v"])), c["key"]
print("ok:   POR LUP log: %d curves, legacy columns, read back by latchup_rejudge.py" % len(curves))
PY
