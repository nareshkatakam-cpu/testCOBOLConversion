-- Run as a DBA. Replace the path with the OS directory holding EMPLOYEE.DAT
-- (replaces the COBOL SELECT ... ASSIGN TO clauses) and the schema owning the package.
CREATE OR REPLACE DIRECTORY payroll_dir AS '/opt/payroll_data';
GRANT READ, WRITE ON DIRECTORY payroll_dir TO payroll;
