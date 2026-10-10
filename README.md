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
