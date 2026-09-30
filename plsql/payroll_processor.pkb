CREATE OR REPLACE PACKAGE BODY payroll_processor AS

  c_record_length  CONSTANT PLS_INTEGER := 45;          -- EMP-RECORD
  c_report_width   CONSTANT PLS_INTEGER := 80;          -- REPORT-RECORD PIC X(80)
  c_max_linesize   CONSTANT PLS_INTEGER := 32767;
  c_reg_hours_max  CONSTANT NUMBER      := 40.00;
  c_ot_multiplier  CONSTANT NUMBER      := 1.5;
  c_tax_divisor    CONSTANT NUMBER      := 4.00;        -- WS-TAX-DIVISOR

  -- Report edit pictures
  c_pic_det_amount CONSTANT VARCHAR2(20) := '$ZZZZ9.99';    -- $Z(4)9.99
  c_pic_tot_count  CONSTANT VARCHAR2(20) := 'ZZZ9';
  c_pic_tot_amount CONSTANT VARCHAR2(20) := '$Z,ZZZ,Z9.99';

  FUNCTION fit_numeric (
    p_value      IN NUMBER,
    p_int_digits IN PLS_INTEGER,
    p_dec_digits IN PLS_INTEGER
  ) RETURN NUMBER DETERMINISTIC IS
  BEGIN
    RETURN MOD(TRUNC(ABS(NVL(p_value, 0)), p_dec_digits), POWER(10, p_int_digits));
  END fit_numeric;

  FUNCTION edit_numeric (
    p_value   IN NUMBER,
    p_picture IN VARCHAR2
  ) RETURN VARCHAR2 DETERMINISTIC IS
    l_int_digits  PLS_INTEGER := 0;
    l_dec_digits  PLS_INTEGER := 0;
    l_after_point BOOLEAN     := FALSE;
    l_value       NUMBER;
    l_digits      VARCHAR2(64);
    l_digit_pos   PLS_INTEGER := 0;
    l_suppressing BOOLEAN     := TRUE;
    l_char        VARCHAR2(1);
    l_digit       VARCHAR2(1);
    l_result      VARCHAR2(200);
  BEGIN
    FOR i IN 1 .. LENGTH(p_picture) LOOP
      l_char := SUBSTR(p_picture, i, 1);
      IF l_char = '.' THEN
        l_after_point := TRUE;
      ELSIF l_char IN ('Z', '9') THEN
        IF l_after_point THEN
          l_dec_digits := l_dec_digits + 1;
        ELSE
          l_int_digits := l_int_digits + 1;
        END IF;
      END IF;
    END LOOP;

    l_value  := fit_numeric(p_value, l_int_digits, l_dec_digits);
    l_digits := LPAD(TO_CHAR(l_value * POWER(10, l_dec_digits), 'FM' || RPAD('0', l_int_digits + l_dec_digits, '0')),
                     l_int_digits + l_dec_digits, '0');

    FOR i IN 1 .. LENGTH(p_picture) LOOP
      l_char := SUBSTR(p_picture, i, 1);
      CASE
        WHEN l_char IN ('Z', '9') THEN
          l_digit_pos := l_digit_pos + 1;
          l_digit     := SUBSTR(l_digits, l_digit_pos, 1);
          IF l_suppressing AND l_char = 'Z' AND l_digit = '0' THEN
            l_result := l_result || ' ';
          ELSE
            l_suppressing := FALSE;
            l_result      := l_result || l_digit;
          END IF;
        WHEN l_char = ',' THEN
          l_result := l_result || CASE WHEN l_suppressing THEN ' ' ELSE ',' END;
        WHEN l_char = '.' THEN
          l_suppressing := FALSE;
          l_result      := l_result || '.';
        ELSE
          l_result := l_result || l_char;
      END CASE;
    END LOOP;

    RETURN l_result;
  END edit_numeric;

  FUNCTION pic_x (
    p_value  IN VARCHAR2,
    p_length IN PLS_INTEGER
  ) RETURN VARCHAR2 DETERMINISTIC IS
  BEGIN
    RETURN RPAD(NVL(SUBSTR(p_value, 1, p_length), ' '), p_length);
  END pic_x;

  FUNCTION is_numeric_field (p_value IN VARCHAR2) RETURN BOOLEAN IS
  BEGIN
    RETURN p_value IS NOT NULL AND REGEXP_LIKE(p_value, '^[0-9]+$');
  END is_numeric_field;

  -- 1100-READ-EMPLOYEE (record layout)
  FUNCTION parse_record (p_line IN VARCHAR2) RETURN emp_record_t IS
    l_rec  VARCHAR2(45) := pic_x(p_line, c_record_length);
    l_emp  emp_record_t;
  BEGIN
    l_emp.emp_id        := SUBSTR(l_rec,  1,  5);
    l_emp.emp_name      := SUBSTR(l_rec,  6, 25);
    l_emp.emp_dept      := SUBSTR(l_rec, 31,  4);
    l_emp.emp_hours_raw := SUBSTR(l_rec, 35,  5);
    l_emp.emp_rate_raw  := SUBSTR(l_rec, 40,  5);
    l_emp.emp_type      := SUBSTR(l_rec, 45,  1);

    IF is_numeric_field(l_emp.emp_hours_raw) THEN
      l_emp.emp_hours := TO_NUMBER(l_emp.emp_hours_raw) / 100;
    END IF;
    IF is_numeric_field(l_emp.emp_rate_raw) THEN
      l_emp.emp_hourly_rate := TO_NUMBER(l_emp.emp_rate_raw) / 100;
    END IF;

    RETURN l_emp;
  END parse_record;

  -- 2100-VALIDATE-RECORD
  FUNCTION validate_record (p_emp IN emp_record_t) RETURN BOOLEAN IS
    l_valid BOOLEAN := TRUE;
  BEGIN
    IF NOT is_numeric_field(p_emp.emp_hours_raw) OR NOT is_numeric_field(p_emp.emp_rate_raw) THEN
      DBMS_OUTPUT.PUT_LINE('INVALID NUMERIC DATA FOR EMP: ' || p_emp.emp_id);
      l_valid := FALSE;
    END IF;
    IF NVL(p_emp.emp_type, ' ') NOT IN ('H', 'S') THEN
      DBMS_OUTPUT.PUT_LINE('INVALID EMPLOYEE TYPE FOR EMP: ' || p_emp.emp_id);
      l_valid := FALSE;
    END IF;
    RETURN l_valid;
  END validate_record;

  -- 2200-CALCULATE-PAY
  PROCEDURE calculate_pay (
    p_emp       IN  emp_record_t,
    p_gross_pay OUT NUMBER,
    p_net_pay   OUT NUMBER
  ) IS
    l_reg_hours  NUMBER;
    l_ot_hours   NUMBER;
    l_tax_amount NUMBER;
  BEGIN
    CASE p_emp.emp_type
      WHEN 'S' THEN
        p_gross_pay := fit_numeric(p_emp.emp_hours * p_emp.emp_hourly_rate, 5, 2);
      WHEN 'H' THEN
        IF p_emp.emp_hours > c_reg_hours_max THEN
          l_reg_hours := c_reg_hours_max;
          l_ot_hours  := fit_numeric(p_emp.emp_hours - c_reg_hours_max, 3, 2);
        ELSE
          l_reg_hours := p_emp.emp_hours;
          l_ot_hours  := 0;
        END IF;
        p_gross_pay := fit_numeric((l_reg_hours * p_emp.emp_hourly_rate)
                                   + (l_ot_hours * p_emp.emp_hourly_rate * c_ot_multiplier), 5, 2);
    END CASE;

    l_tax_amount := fit_numeric(ROUND(p_gross_pay / c_tax_divisor, 2), 5, 2);
    p_net_pay    := fit_numeric(p_gross_pay - l_tax_amount, 5, 2);
  END calculate_pay;

  FUNCTION header_line_1 RETURN VARCHAR2 IS
  BEGIN
    RETURN pic_x(' ', 28)
        || pic_x('PAYROLL PROCESSING REPORT', 24)
        || pic_x(' ', 28);
  END header_line_1;

  FUNCTION header_line_2 RETURN VARCHAR2 IS
  BEGIN
    RETURN RPAD('=', c_report_width, '=');
  END header_line_2;

  FUNCTION data_line (p_emp IN emp_record_t, p_gross_pay IN NUMBER, p_net_pay IN NUMBER) RETURN VARCHAR2 IS
  BEGIN
    RETURN pic_x(p_emp.emp_id, 5)
        || pic_x(' ', 3)
        || pic_x(p_emp.emp_name, 25)
        || pic_x(' ', 2)
        || pic_x(p_emp.emp_dept, 4)
        || pic_x(' ', 4)
        || edit_numeric(p_gross_pay, c_pic_det_amount)
        || pic_x(' ', 4)
        || edit_numeric(p_net_pay, c_pic_det_amount)
        || pic_x(' ', 13);
  END data_line;

  FUNCTION totals_line (p_total_employees IN NUMBER, p_total_payroll IN NUMBER) RETURN VARCHAR2 IS
  BEGIN
    RETURN pic_x('TOTAL EMPLOYEES PROCESSED:', 39)
        || edit_numeric(p_total_employees, c_pic_tot_count)
        || pic_x(' ', 5)
        || pic_x('TOTAL PAYROLL:', 14)
        || edit_numeric(p_total_payroll, c_pic_tot_amount)
        || pic_x(' ', 6);
  END totals_line;

  PROCEDURE write_report_record (p_file IN UTL_FILE.FILE_TYPE, p_line IN VARCHAR2) IS
  BEGIN
    UTL_FILE.PUT_LINE(p_file, pic_x(p_line, c_report_width));
  END write_report_record;

  -- 1100-READ-EMPLOYEE
  PROCEDURE read_employee (
    p_file IN            UTL_FILE.FILE_TYPE,
    p_line    OUT NOCOPY VARCHAR2,
    p_eof  IN OUT        BOOLEAN
  ) IS
  BEGIN
    UTL_FILE.GET_LINE(p_file, p_line, c_max_linesize);
  EXCEPTION
    WHEN NO_DATA_FOUND THEN
      p_eof := TRUE;
  END read_employee;

  PROCEDURE close_files (
    p_emp_file    IN OUT UTL_FILE.FILE_TYPE,
    p_report_file IN OUT UTL_FILE.FILE_TYPE
  ) IS
  BEGIN
    IF UTL_FILE.IS_OPEN(p_emp_file) THEN
      UTL_FILE.FCLOSE(p_emp_file);
    END IF;
    IF UTL_FILE.IS_OPEN(p_report_file) THEN
      UTL_FILE.FCLOSE(p_report_file);
    END IF;
  END close_files;

  -- 0000-MAIN
  PROCEDURE run (
    p_directory   IN VARCHAR2 DEFAULT c_default_directory,
    p_emp_file    IN VARCHAR2 DEFAULT c_default_emp_file,
    p_report_file IN VARCHAR2 DEFAULT c_default_report_file
  ) IS
    l_emp_file        UTL_FILE.FILE_TYPE;
    l_report_file     UTL_FILE.FILE_TYPE;
    l_line            VARCHAR2(32767);
    l_eof             BOOLEAN := FALSE;
    l_emp             emp_record_t;
    l_gross_pay       NUMBER;
    l_net_pay         NUMBER;
    l_total_employees NUMBER := 0;   -- WS-TOTAL-EMPLOYEES PIC 9(4)
    l_total_payroll   NUMBER := 0;   -- WS-TOTAL-PAYROLL   PIC 9(7)V99
  BEGIN
    -- 1000-INITIALIZE
    BEGIN
      l_emp_file := UTL_FILE.FOPEN(p_directory, p_emp_file, 'r', c_max_linesize);
    EXCEPTION
      WHEN UTL_FILE.INVALID_PATH OR UTL_FILE.INVALID_OPERATION OR UTL_FILE.ACCESS_DENIED
           OR UTL_FILE.INVALID_FILENAME THEN
        DBMS_OUTPUT.PUT_LINE('ERROR OPENING EMPLOYEE FILE: ' || SQLERRM);
        RETURN;
    END;

    l_report_file := UTL_FILE.FOPEN(p_directory, p_report_file, 'w', c_max_linesize);
    write_report_record(l_report_file, header_line_1);
    write_report_record(l_report_file, header_line_2);
    read_employee(l_emp_file, l_line, l_eof);

    -- 2000-PROCESS-DATA
    WHILE NOT l_eof LOOP
      l_emp := parse_record(l_line);

      IF validate_record(l_emp) THEN
        calculate_pay(l_emp, l_gross_pay, l_net_pay);

        -- 2300-ACCUMULATE-TOTALS
        l_total_employees := fit_numeric(l_total_employees + 1, 4, 0);
        l_total_payroll   := fit_numeric(l_total_payroll + l_net_pay, 7, 2);

        -- 2400-WRITE-REPORT-LINE
        write_report_record(l_report_file, data_line(l_emp, l_gross_pay, l_net_pay));
      END IF;

      read_employee(l_emp_file, l_line, l_eof);
    END LOOP;

    -- 3000-TERMINATE
    write_report_record(l_report_file, header_line_2);
    write_report_record(l_report_file, totals_line(l_total_employees, l_total_payroll));
    close_files(l_emp_file, l_report_file);
  EXCEPTION
    WHEN OTHERS THEN
      close_files(l_emp_file, l_report_file);
      RAISE;
  END run;

END payroll_processor;
/
