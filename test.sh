#!/usr/bin/env bash
# greenscan self-test: runs the script against bundled demo data and
# asserts (a) exit code 1, (b) at least one finding in every class except
# A (which the demo data omits to keep the demo noise-free).
set -euo pipefail
cd "$(dirname "$0")"
out=$(python3 greenscan.py --dry-run --no-color || test $? -eq 1)
echo "$out"
echo "$out" | grep -q "E. continue-on-fail" || { echo "missing coaf_risk finding"; exit 1; }
echo "$out" | grep -q "B. missed run"    || { echo "missing missed_run finding"; exit 1; }
echo "$out" | grep -q "C. silent failure" || { echo "missing early_end finding"; exit 1; }
echo "$out" | grep -q "D. empty output"  || { echo "missing empty_output finding"; exit 1; }
echo "$out" | grep -q "F. zombie"        || { echo "missing zombie finding"; exit 1; }
python3 greenscan.py --dry-run --no-color >/dev/null
code=$?
[ "$code" = "1" ] || { echo "expected exit 1, got $code"; exit 1; }
echo "self-test ok"
