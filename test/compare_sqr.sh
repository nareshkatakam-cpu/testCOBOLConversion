#!/usr/bin/env bash
# Runs the original COBOL program (GnuCOBOL) and the SQR conversion (sqr/ZPAYPROC.sqr)
# on every file in test/data and diffs the report files and the program messages
# (INVALID.../ERROR... lines; SQR adds its own banner lines to the console).
#
# Prerequisites: cobc (GnuCOBOL 3.x) and python3 on PATH.
#
# By default the SQR source is executed by test/sqr_subset.py (an interpreter for the
# SQR subset ZPAYPROC.sqr uses) with PeopleSoft include stubs from test/sqr_stubs.
# To use a real SQR runtime instead, set SQR_CMD to a command that runs ZPAYPROC
# standalone in the current directory, e.g.
#   SQR_CMD="sqr $PWD/sqr/ZPAYPROC.sqr sysadm/pw@HRDEV -i$PS_HOME/sqr/ -xb" test/compare_sqr.sh
#
# Set RESULTS_DIR to keep each case's report/console output from both programs.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SQR_CMD="${SQR_CMD:-python3 $ROOT/test/sqr_subset.py $ROOT/sqr/ZPAYPROC.sqr -I $ROOT/test/sqr_stubs}"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

# Fixed-format source with text past column 72.
cobc -x -ftext-column=255 -o "$WORK/payroll" "$ROOT/sampleCOBOLprogram" 2>/dev/null

run_cobol() {
  local input="$1" out="$2"
  mkdir -p "$out"
  if [[ -n "$input" ]]; then cp "$input" "$out/EMPLOYEE.DAT"; fi
  (cd "$out" && COB_LS_FIXED=TRUE "$WORK/payroll" > console.txt)
}

run_sqr() {
  local input="$1" out="$2"
  mkdir -p "$out"
  if [[ -n "$input" ]]; then cp "$input" "$out/EMPLOYEE.DAT"; fi
  # Empty answers to any Stdapi-Init prompts = standalone run (no process instance).
  (cd "$out" && printf '\n\n\n' | $SQR_CMD > console.txt)
}

messages() { grep -E '^(INVALID|ERROR)' "$1" | sed 's/ *$//' || true; }

status=0
for input in "$ROOT"/test/data/*.DAT; do
  name="$(basename "$input" .DAT)"
  run_cobol "$input" "$WORK/$name/cobol"
  run_sqr "$input" "$WORK/$name/sqr"
  if diff "$WORK/$name/cobol/PAYROLL_REPORT.TXT" "$WORK/$name/sqr/PAYROLL_REPORT.TXT" \
     && diff <(messages "$WORK/$name/cobol/console.txt") <(messages "$WORK/$name/sqr/console.txt"); then
    echo "PASS $name"
  else
    echo "FAIL $name"; status=1
  fi
done

# Missing input file: both must refuse to produce a report.
run_cobol "" "$WORK/missing/cobol"
run_sqr "" "$WORK/missing/sqr"
if [[ ! -e "$WORK/missing/cobol/PAYROLL_REPORT.TXT" && ! -e "$WORK/missing/sqr/PAYROLL_REPORT.TXT" ]] \
   && grep -q '^ERROR OPENING EMPLOYEE FILE: ' "$WORK/missing/cobol/console.txt" \
   && grep -q '^ERROR OPENING EMPLOYEE FILE: ' "$WORK/missing/sqr/console.txt"; then
  echo "PASS missing-input"
else
  echo "FAIL missing-input"; status=1
fi

if [[ -n "${RESULTS_DIR:-}" ]]; then
  mkdir -p "$RESULTS_DIR"
  cp -r "$WORK"/. "$RESULTS_DIR"/
  rm -f "$RESULTS_DIR/payroll"
fi

exit $status
