sample COBOL program from Google

## Oracle PL/SQL conversion

`plsql/` contains the conversion of `sampleCOBOLprogram` (PAYROLL-PROCESSOR) to an Oracle
PL/SQL package, `payroll_processor`.

| COBOL                                   | PL/SQL                                              |
|-----------------------------------------|-----------------------------------------------------|
| `SELECT ... ASSIGN TO` files            | `UTL_FILE` in the `PAYROLL_DIR` directory object    |
| `EMP-RECORD`                            | `payroll_processor.emp_record_t` / `parse_record`   |
| `2100-VALIDATE-RECORD`                  | `validate_record`                                   |
| `2200-CALCULATE-PAY`                    | `calculate_pay`                                     |
| `WS-REPORT-LINES`                       | `header_line_1/2`, `data_line`, `totals_line`       |
| `DISPLAY`                               | `DBMS_OUTPUT.PUT_LINE`                              |
| `0000-MAIN`                             | `payroll_processor.run`                             |

COBOL data semantics are preserved: unsigned fixed-point fields truncate (not round) excess
decimals and high-order digits (`fit_numeric`), `COMPUTE ... ROUNDED` rounds half away from
zero, and numeric-edited pictures are reproduced by `edit_numeric`.

### Install and run

```sql
-- as DBA (edit the path/schema first)
@plsql/setup_directory.sql
-- as the package owner
@plsql/install.sql
@plsql/run_payroll.sql
```

### Equivalence test

`test/compare.sh` compiles the original COBOL with GnuCOBOL, runs both versions against every
file in `test/data/` (plus a missing-input case) and diffs the reports and console output.
See the script header for prerequisites.

## PeopleSoft SQR conversion

`sqr/ZPAYPROC.sqr` converts `sampleCOBOLprogram` to SQR for PeopleSoft. It is scheduled
from the Application Engine program `Z_PAYPROC` (PeopleCode in `peoplesoft/appengine/`),
reads its file names from run control record `Z_RUNCTL_PAYPRC`, and reports status
through the delivered Process Scheduler API (`stdapi.sqc`). Setup steps are in
[`peoplesoft/README.md`](peoplesoft/README.md).

| COBOL                         | SQR (`ZPAYPROC.sqr`)                                  |
|-------------------------------|-------------------------------------------------------|
| `SELECT ... ASSIGN TO` files  | `open ... for-reading` / `for-writing`; paths from run control |
| `0000-MAIN`                   | `begin-program` / `Process-Main`                      |
| `1000-INITIALIZE`             | `Initialize-Processing`                               |
| `1100-READ-EMPLOYEE`          | `Read-Employee`                                       |
| `2000-PROCESS-DATA`           | `Process-Employee` (+ `Parse-Employee-Record`)        |
| `2100-VALIDATE-RECORD`        | `Validate-Record` / `Is-Numeric-Field`                |
| `2200-CALCULATE-PAY`          | `Calculate-Pay`                                       |
| `2300-ACCUMULATE-TOTALS`      | `Accumulate-Totals`                                   |
| `2400-WRITE-REPORT-LINE`      | `Write-Report-Line`                                   |
| `3000-TERMINATE`              | `Terminate-Processing`                                |
| `DISPLAY`                     | `display` (Process Monitor `.out` log)                |
| `STOP RUN` on open error      | request set to Error, no report written               |

All arithmetic uses `DECIMAL` (`default-numeric=decimal(38)`), with the same COBOL
semantics as the PL/SQL version (`Fit-Numeric`, `round(...)`, `Edit-Numeric`).

### Equivalence test

`test/compare_sqr.sh` runs the COBOL original and the SQR on every file in `test/data/`
(plus a missing-input case) and diffs the reports and messages. With no SQR runtime
available it executes the SQR source with `test/sqr_subset.py`, an interpreter for the
subset of SQR that `ZPAYPROC.sqr` uses (PeopleSoft includes stubbed in
`test/sqr_stubs/`); set `SQR_CMD` to run it against a real SQR installation.

### Data validation (no PeopleSoft needed)

`test/validate.py` runs the COBOL original and the SQR on many employee files and
reconciles the outputs record by record. Needs only `cobc` (GnuCOBOL 3.x) and `python3`.

```bash
python3 test/validate.py                       # fixtures + edge cases + 3 x 1000 random + 10,050-record volume file
python3 test/validate.py --random-files 10 --records 5000 --seed 42
python3 test/validate.py my_employees.DAT      # also validate your own files
SQR_CMD="sqr $PWD/sqr/ZPAYPROC.sqr ..." python3 test/validate.py   # real SQR runtime
```

For every input record it checks that both programs accept or reject it the same way,
that EMP-ID, name, department, gross and net match for accepted records, and that the
`INVALID ...` messages match for rejected ones. It also compares the totals and
control totals (detail count, sum of net pay, accepted + rejected = input records), the
report headers and widths, the missing-input-file behavior, and the report bytes.
Results go to `test/results/`: `summary.md`, `reconciliation.csv` (one row per input
record) and each program's report/console output per dataset. Exit status is 1 on any
mismatch.

Test files come from `test/generate_data.py` (deterministic for a given `--seed`):

```bash
python3 test/generate_data.py --profile edge   --out edge.DAT     # hand-picked edge cases
python3 test/generate_data.py --profile mixed  --records 1000 --seed 7 --out mixed.DAT
python3 test/generate_data.py --profile volume --records 10050 --out volume.DAT
```

Edge cases cover overtime boundaries (39.99 / 40.00 / 40.01 hours), maximum hours and
rates, gross-pay overflow, rounding of tax, bad numeric fields (spaces, signs, decimal
points, letters), bad and lower-case employee types, blank, short and long lines and
duplicate IDs. `mixed` is about 80% valid random records and 20% invalid ones; `volume`
is all valid and wraps the `9(4)` employee counter.

**Known difference.** When the payroll total reaches $1,000,000 its top digit doesn't
fit the `$Z,ZZZ,Z9.99` picture. GnuCOBOL then stops suppressing leading zeros
(`$0,613,01.88`), while the SQR (like the PL/SQL version) suppresses them as usual
(`$  613,01.88`); the printed value is the same. The validator reports this as
"PASS (known difference)" rather than a failure. Any other difference fails.

GitHub Actions (`.github/workflows/validate.yml`) runs `test/compare_sqr.sh` and
`test/validate.py` on every pull request and uploads `summary.md` and
`reconciliation.csv`.
