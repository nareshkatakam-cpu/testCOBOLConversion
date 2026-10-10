# PeopleSoft setup for ZPAYPROC

`sqr/ZPAYPROC.sqr` is the SQR conversion of PAYROLL-PROCESSOR. In PeopleSoft it runs as
an *SQR Process* that the Application Engine program `Z_PAYPROC` schedules and waits for.
The `Z` prefix marks customer objects; rename consistently if your site uses another.

```
Run control page ──> AE Z_PAYPROC ── SCHEDULE: CreateProcessRequest("SQR Process", "ZPAYPROC")
                                 └─ WAIT:     poll PSPRCSRQST.RUNSTATUS, abort AE on failure
                     SQR ZPAYPROC ── reads PS_Z_RUNCTL_PAYPRC (same OPRID / RUN_CNTL_ID)
                                 └─ EMPLOYEE file ──> PAYROLL_REPORT file, messages to the .out log
```

## 1. Records (Application Designer)

**Z_RUNCTL_PAYPRC** (SQL table, run control)

| Field          | Type      | Key | Notes                                                    |
|----------------|-----------|-----|----------------------------------------------------------|
| OPRID          | Char 30   | Yes | delivered field                                          |
| RUN_CNTL_ID    | Char 30   | Yes | delivered field                                          |
| Z_EMP_FILE     | Char 254  |     | full path of the employee file, as seen by the PS server |
| Z_REPORT_FILE  | Char 254  |     | full path of the report file to write                    |

Blank file fields fall back to `EMPLOYEE.DAT` / `PAYROLL_REPORT.TXT` in the SQR's
working directory. Build the record, add it to a run control page with the
`PRCSRUNCNTL` subpage, and register the component in a menu/permission list as usual.

**Z_PAYPROC_AET** (derived/work or SQL table, AE state record)

| Field            | Key | Notes                                       |
|------------------|-----|---------------------------------------------|
| PROCESS_INSTANCE | Yes | populated by AE                             |
| OPRID            |     | populated by AE from the request            |
| RUN_CNTL_ID      |     | populated by AE from the request            |
| PRCSINSTANCE     |     | process instance of the scheduled SQR       |
| RUNSTATUS        |     | final PSPRCSRQST.RUNSTATUS of the SQR       |

## 2. Application Engine program Z_PAYPROC

Properties: default state record `Z_PAYPROC_AET`, *Disable Restart* checked.

| Section | Step     | Action     | Source                                                    | Step settings                       |
|---------|----------|------------|-----------------------------------------------------------|-------------------------------------|
| MAIN    | SCHEDULE | PeopleCode | `appengine/Z_PAYPROC.MAIN.SCHEDULE.OnExecute.pcode`       | Commit: **After Step**; On Return: Abort |
| MAIN    | WAIT     | PeopleCode | `appengine/Z_PAYPROC.MAIN.WAIT.OnExecute.pcode`           | On Return: Abort                    |

The commit after SCHEDULE is required: the SQR request row is only visible to Process
Scheduler once the AE commits. WAIT polls every 10 seconds for up to an hour; adjust
`&pollMillis` / `&maxPolls` as needed.

## 3. Process definitions (PeopleTools > Process Scheduler > Processes)

| Process type        | Name      | Settings                                                              |
|---------------------|-----------|-----------------------------------------------------------------------|
| SQR Process         | ZPAYPROC  | same component/process groups as the AE; no run control page needed   |
| Application Engine  | Z_PAYPROC | component = the run control component from step 1                     |

Copy `sqr/ZPAYPROC.sqr` to a directory in the Process Scheduler server's SQR path
(`PS_CUST_HOME/sqr` or `PS_HOME/sqr`). It uses only delivered includes:
`setenv.sqc` and `stdapi.sqc` (which brings in `prcsapi.sqc` / `prcsdef.sqc`).

## 4. Behaviour under Process Scheduler

- `Stdapi-Init` picks up the process instance, OPRID and run control ID; the SQR then
  reads `Z_EMP_FILE` / `Z_REPORT_FILE` from `PS_Z_RUNCTL_PAYPRC`.
- `INVALID ...` messages (COBOL `DISPLAY`) go to the SQR `.out` log in the Process Monitor.
- If the employee (or report) file cannot be opened, the SQR logs
  `ERROR OPENING ... FILE: <path>`, writes no report, and sets the request to
  **Error** (RUNSTATUS 3) via `Update-Prcs-Run-Status`; step WAIT then aborts the AE.
- Otherwise `Stdapi-Term` marks the request **Success**.

## Running the SQR standalone

```
sqr sqr/ZPAYPROC.sqr <user>/<password>@<db> -i$PS_HOME/sqr/ -xb
```

Press Enter at the `Stdapi-Init` prompts; the SQR reads `EMPLOYEE.DAT` and writes
`PAYROLL_REPORT.TXT` in the current directory, exactly like the COBOL program.
