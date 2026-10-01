-- Equivalent of running PAYROLL-PROCESSOR: reads EMPLOYEE.DAT and writes
-- PAYROLL_REPORT.TXT in the PAYROLL_DIR directory object.
SET SERVEROUTPUT ON SIZE UNLIMITED FORMAT WRAPPED
EXEC payroll_processor.run(p_directory => 'PAYROLL_DIR', p_emp_file => 'EMPLOYEE.DAT', p_report_file => 'PAYROLL_REPORT.TXT')
