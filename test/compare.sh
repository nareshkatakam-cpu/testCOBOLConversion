#!/usr/bin/env bash
# Runs the original COBOL program (GnuCOBOL) and the PL/SQL conversion (Oracle via
# docker) on every file in test/data and diffs the report files and console output
# (console output ignoring trailing spaces, which SQL*Plus trims).
#
# Prerequisites:
#   - cobc (GnuCOBOL 3.x) on PATH
#   - a running Oracle container with the payroll_processor package installed and a
#     PAYROLL_DIR directory object mapped to $ORACLE_DATA_HOST_DIR, e.g.
#       docker run -d --name oracle -e ORACLE_PASSWORD=... -e APP_USER=payroll \
#         -e APP_USER_PASSWORD=payroll -v "$ORACLE_DATA_HOST_DIR":/opt/payroll_data \
#         gvenzl/oracle-free:23-slim-faststart
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ORACLE_CONTAINER="${ORACLE_CONTAINER:-oracle}"
ORACLE_CONNECT="${ORACLE_CONNECT:-payroll/payroll@localhost/FREEPDB1}"
ORACLE_DATA_HOST_DIR="${ORACLE_DATA_HOST_DIR:?set to the host directory mounted as PAYROLL_DIR}"
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

run_plsql() {
  local input="$1" out="$2"
  mkdir -p "$out"
  rm -f "$ORACLE_DATA_HOST_DIR/EMPLOYEE.DAT" "$ORACLE_DATA_HOST_DIR/PAYROLL_REPORT.TXT"
  if [[ -n "$input" ]]; then cp "$input" "$ORACLE_DATA_HOST_DIR/EMPLOYEE.DAT"; chmod 644 "$ORACLE_DATA_HOST_DIR/EMPLOYEE.DAT"; fi
  docker exec -i "$ORACLE_CONTAINER" sqlplus -s "$ORACLE_CONNECT" > "$out/console.txt" <<'SQL'
SET SERVEROUTPUT ON SIZE UNLIMITED FORMAT WRAPPED
SET FEEDBACK OFF HEADING OFF PAGESIZE 0 LINESIZE 32767
WHENEVER SQLERROR EXIT FAILURE
EXEC payroll_processor.run
EXIT
SQL
  if [[ -f "$ORACLE_DATA_HOST_DIR/PAYROLL_REPORT.TXT" ]]; then
    cp "$ORACLE_DATA_HOST_DIR/PAYROLL_REPORT.TXT" "$out/PAYROLL_REPORT.TXT"
  fi
}

status=0
for input in "$ROOT"/test/data/*.DAT; do
  name="$(basename "$input" .DAT)"
  run_cobol "$input" "$WORK/$name/cobol"
  run_plsql "$input" "$WORK/$name/plsql"
  if diff "$WORK/$name/cobol/PAYROLL_REPORT.TXT" "$WORK/$name/plsql/PAYROLL_REPORT.TXT" \
     && diff <(sed 's/ *$//' "$WORK/$name/cobol/console.txt") <(sed 's/ *$//' "$WORK/$name/plsql/console.txt"); then
    echo "PASS $name"
  else
    echo "FAIL $name"; status=1
  fi
done

# Missing input file: both must refuse to produce a report.
run_cobol "" "$WORK/missing/cobol"
run_plsql "" "$WORK/missing/plsql"
if [[ ! -e "$WORK/missing/cobol/PAYROLL_REPORT.TXT" && ! -e "$WORK/missing/plsql/PAYROLL_REPORT.TXT" ]] \
   && grep -q '^ERROR OPENING EMPLOYEE FILE: ' "$WORK/missing/cobol/console.txt" \
   && grep -q '^ERROR OPENING EMPLOYEE FILE: ' "$WORK/missing/plsql/console.txt"; then
  echo "PASS missing-input"
else
  echo "FAIL missing-input"; status=1
fi

exit $status
