CREATE OR REPLACE PACKAGE payroll_processor AUTHID DEFINER AS
  -- Oracle PL/SQL conversion of COBOL program PAYROLL-PROCESSOR (sampleCOBOLprogram).
  --
  -- Reads the fixed-width employee file (EMP-RECORD, 45 bytes per line) and writes the
  -- 80-column payroll report, both through UTL_FILE in the given DIRECTORY object.
  -- COBOL DISPLAY output is written to DBMS_OUTPUT.

  c_default_directory   CONSTANT VARCHAR2(128) := 'PAYROLL_DIR';
  c_default_emp_file    CONSTANT VARCHAR2(255) := 'EMPLOYEE.DAT';
  c_default_report_file CONSTANT VARCHAR2(255) := 'PAYROLL_REPORT.TXT';

  -- EMP-RECORD
  TYPE emp_record_t IS RECORD (
    emp_id          VARCHAR2(5),   -- PIC X(5)
    emp_name        VARCHAR2(25),  -- PIC X(25)
    emp_dept        VARCHAR2(4),   -- PIC X(4)
    emp_hours_raw   VARCHAR2(5),   -- PIC 9(3)V99 (as read)
    emp_rate_raw    VARCHAR2(5),   -- PIC 9(3)V99 (as read)
    emp_type        VARCHAR2(1),   -- PIC X(1): 'H' = hourly, 'S' = salaried
    emp_hours       NUMBER(5,2),
    emp_hourly_rate NUMBER(5,2)
  );

  -- 0000-MAIN
  PROCEDURE run (
    p_directory   IN VARCHAR2 DEFAULT c_default_directory,
    p_emp_file    IN VARCHAR2 DEFAULT c_default_emp_file,
    p_report_file IN VARCHAR2 DEFAULT c_default_report_file
  );

  -- Building blocks, exposed for reuse and unit testing.
  FUNCTION parse_record (p_line IN VARCHAR2) RETURN emp_record_t;

  FUNCTION validate_record (p_emp IN emp_record_t) RETURN BOOLEAN;

  PROCEDURE calculate_pay (
    p_emp       IN  emp_record_t,
    p_gross_pay OUT NUMBER,
    p_net_pay   OUT NUMBER
  );

  -- Stores p_value into an unsigned PIC 9(p_int_digits)V9(p_dec_digits) field:
  -- sign dropped, excess decimals truncated, excess high-order digits truncated.
  FUNCTION fit_numeric (
    p_value      IN NUMBER,
    p_int_digits IN PLS_INTEGER,
    p_dec_digits IN PLS_INTEGER
  ) RETURN NUMBER DETERMINISTIC;

  -- Moves p_value into a numeric-edited field. Supports picture symbols
  -- '$' (fixed insertion), 'Z', '9', ',' and '.', e.g. '$Z(4)9.99' expanded as '$ZZZZ9.99'.
  FUNCTION edit_numeric (
    p_value   IN NUMBER,
    p_picture IN VARCHAR2
  ) RETURN VARCHAR2 DETERMINISTIC;

  -- Moves p_value into a PIC X(p_length) field (truncate or pad with spaces).
  FUNCTION pic_x (
    p_value  IN VARCHAR2,
    p_length IN PLS_INTEGER
  ) RETURN VARCHAR2 DETERMINISTIC;

  FUNCTION header_line_1 RETURN VARCHAR2;
  FUNCTION header_line_2 RETURN VARCHAR2;
  FUNCTION data_line (p_emp IN emp_record_t, p_gross_pay IN NUMBER, p_net_pay IN NUMBER) RETURN VARCHAR2;
  FUNCTION totals_line (p_total_employees IN NUMBER, p_total_payroll IN NUMBER) RETURN VARCHAR2;
END payroll_processor;
/
