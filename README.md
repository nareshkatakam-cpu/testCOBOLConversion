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
