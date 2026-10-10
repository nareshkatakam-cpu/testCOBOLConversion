#!/usr/bin/env python3
"""COBOL vs SQR data validation.

Runs the original COBOL program (GnuCOBOL) and the SQR conversion on a set of employee
files and reconciles the outputs record by record:

  * every input record is classified ACCEPTED (has a report detail line) or REJECTED
    (has INVALID... messages) by each program, and the two classifications must agree
  * for accepted records, EMP-ID / NAME / DEPT / GROSS / NET must match
  * for rejected records, the INVALID... messages must match
  * TOTAL EMPLOYEES PROCESSED and TOTAL PAYROLL must match
  * control checks on each program's own output: detail count = total count and
    sum(net) = total payroll (modulo the 9(4) count / 6 printed payroll digits), accepted + rejected =
    input records, headers as expected
  * the report files must be byte-identical, apart from KNOWN DIFFERENCES below

Known difference (reported, not a failure): when WS-TOTAL-PAYROLL is $1,000,000 or more
its high-order digit does not fit TOT-PAYROLL $Z,ZZZ,Z9.99. GnuCOBOL then stops zero
suppression ($1,061,301.88 -> "$0,613,01.88") while the SQR applies standard suppression
to the truncated value ("$  613,01.88"). The printed value is the same.

Datasets: test/data/*.DAT, a generated edge-case file, generated random files and a
volume file (see --help), plus a missing-input-file case.

Results go to --results-dir (default test/results): per-dataset inputs/outputs,
reconciliation.csv (one row per input record) and summary.md. Exit status 1 on any
mismatch.

By default the SQR is executed with test/sqr_subset.py; set --sqr-cmd / SQR_CMD to use a
real SQR runtime (it is run in the dataset directory, which contains EMPLOYEE.DAT).
"""
import argparse
import csv
import os
import shlex
import shutil
import subprocess
import sys
import tempfile
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "test"))
import generate_data  # noqa: E402

REPORT_WIDTH = 80
HDR_1 = " " * 28 + "PAYROLL PROCESSING REPOR" + " " * 28
HDR_2 = "=" * REPORT_WIDTH
FIELDS = ["emp_id", "name", "dept", "gross", "net"]


# ---------------------------------------------------------------- running programs

def compile_cobol(workdir):
    exe = workdir / "payroll"
    subprocess.run(["cobc", "-x", "-ftext-column=255", "-o", str(exe), str(ROOT / "sampleCOBOLprogram")],
                   check=True, stderr=subprocess.DEVNULL)
    return exe


def run_program(cmd, rundir, input_file):
    rundir.mkdir(parents=True, exist_ok=True)
    if input_file is not None:
        shutil.copyfile(input_file, rundir / "EMPLOYEE.DAT")
    env = dict(os.environ, COB_LS_FIXED="TRUE")
    proc = subprocess.run(cmd, cwd=rundir, env=env, input="\n\n\n", capture_output=True, text=True)
    (rundir / "console.txt").write_text(proc.stdout)
    if proc.stderr:
        (rundir / "stderr.txt").write_text(proc.stderr)
    report = rundir / "PAYROLL_REPORT.TXT"
    return {
        "returncode": proc.returncode,
        "console": proc.stdout,
        "stderr": proc.stderr,
        "report": report.read_text() if report.exists() else None,
    }


# ---------------------------------------------------------------- parsing

def read_input(path):
    text = Path(path).read_text()
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    records = []
    for n, line in enumerate(lines, 1):
        rec = line[:45].ljust(45)
        records.append({"line": n, "raw": line, "emp_id": rec[0:5], "name": rec[5:30], "dept": rec[30:34]})
    return records


def money(text):
    digits = text.replace("$", "").replace(",", "").strip()
    return Decimal(digits) if digits else None


def parse_report(report):
    """Split a report into header lines, detail records and totals."""
    out = {"headers": [], "details": [], "totals": None, "errors": []}
    if report is None:
        out["errors"].append("no report file")
        return out
    lines = report.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    for n, line in enumerate(lines, 1):
        if len(line) != REPORT_WIDTH:
            out["errors"].append(f"report line {n} is {len(line)} characters, expected {REPORT_WIDTH}")
    if len(lines) < 4:
        out["errors"].append(f"report has {len(lines)} lines, expected at least 4")
        return out
    out["headers"] = [lines[0], lines[1], lines[-2]]
    for line in lines[2:-2]:
        out["details"].append({
            "emp_id": line[0:5], "name": line[8:33], "dept": line[35:39],
            "gross_text": line[43:52], "net_text": line[56:65],
            "gross": money(line[43:52]), "net": money(line[56:65]),
        })
    tot = lines[-1]
    out["totals"] = {"count_text": tot[39:43], "payroll_text": tot[62:74],
                     "count": int(tot[39:43]) if tot[39:43].strip().isdigit() else None,
                     "payroll": money(tot[62:74]),
                     "labels_ok": tot[:39].rstrip() == "TOTAL EMPLOYEES PROCESSED:"
                     and tot[48:62] == "TOTAL PAYROLL:"}
    return out


def messages(console):
    return [line.rstrip() for line in console.splitlines() if line.startswith(("INVALID", "ERROR"))]


def classify(records, parsed, msgs):
    """Map each input record to its detail line or its rejection messages, in file order."""
    details = list(parsed["details"])
    msgs = [m for m in msgs if m.startswith("INVALID")]
    result, problems = {}, []
    d = m = 0
    for rec in records:
        det = details[d] if d < len(details) else None
        if det and (det["emp_id"], det["name"], det["dept"]) == (rec["emp_id"], rec["name"], rec["dept"]):
            result[rec["line"]] = {"status": "ACCEPTED", "detail": det, "messages": []}
            d += 1
            continue
        mine = []
        for prefix in ("INVALID NUMERIC DATA FOR EMP: ", "INVALID EMPLOYEE TYPE FOR EMP: "):
            if m < len(msgs) and msgs[m] == (prefix + rec["emp_id"]).rstrip():
                mine.append(msgs[m])
                m += 1
        result[rec["line"]] = {"status": "REJECTED" if mine else "MISSING", "detail": None, "messages": mine}
    if d < len(details):
        problems.append(f"{len(details) - d} detail line(s) not matched to an input record")
    if m < len(msgs):
        problems.append(f"{len(msgs) - m} message(s) not matched to an input record")
    return result, problems


def control_checks(name, records, parsed, classes):
    """Checks on one program's output alone."""
    errs = list(parsed["errors"])
    if parsed["headers"]:
        if parsed["headers"][0] != HDR_1:
            errs.append("header line 1 differs from HDR-LINE-1")
        if parsed["headers"][1] != HDR_2 or parsed["headers"][2] != HDR_2:
            errs.append("separator line differs from HDR-LINE-2")
    tot = parsed["totals"]
    if tot:
        if not tot["labels_ok"]:
            errs.append("totals line labels differ")
        n = len(parsed["details"])
        if tot["count"] != n % 10000:
            errs.append(f"total count {tot['count']} != detail lines {n} (mod 10000)")
        # TOT-PAYROLL $Z,ZZZ,Z9.99 shows only 6 integer digits of WS-TOTAL-PAYROLL 9(7)V99.
        net_sum = sum((x["net"] or Decimal(0)) for x in parsed["details"]) % Decimal(1_000_000)
        if tot["payroll"] != net_sum:
            errs.append(f"total payroll {tot['payroll']} != sum of net {net_sum} (mod 1,000,000)")
    missing = [ln for ln, c in classes.items() if c["status"] == "MISSING"]
    if missing:
        errs.append(f"{len(missing)} input record(s) neither reported nor rejected (lines {missing[:10]})")
    return [f"{name}: {e}" for e in errs]


# ---------------------------------------------------------------- reconciliation

def reconcile(dataset, input_file, cobol, sqr, csv_rows):
    records = read_input(input_file)
    side = {}
    issues = []
    for name, run in (("COBOL", cobol), ("SQR", sqr)):
        parsed = parse_report(run["report"])
        msgs = messages(run["console"])
        classes, problems = classify(records, parsed, msgs)
        issues += [f"{name}: {p}" for p in problems]
        issues += control_checks(name, records, parsed, classes)
        side[name] = {"parsed": parsed, "classes": classes}

    mismatched_records = 0
    for rec in records:
        c, s = side["COBOL"]["classes"][rec["line"]], side["SQR"]["classes"][rec["line"]]
        diffs = []
        if c["status"] != s["status"]:
            diffs.append("status")
        cd, sd = c["detail"] or {}, s["detail"] or {}
        for f in FIELDS:
            if cd.get(f) != sd.get(f):
                diffs.append(f)
        if c["messages"] != s["messages"]:
            diffs.append("messages")
        if diffs:
            mismatched_records += 1
        csv_rows.append({
            "dataset": dataset, "line": rec["line"], "emp_id": rec["emp_id"],
            "cobol_status": c["status"], "sqr_status": s["status"],
            "cobol_gross": cd.get("gross", ""), "sqr_gross": sd.get("gross", ""),
            "cobol_net": cd.get("net", ""), "sqr_net": sd.get("net", ""),
            "cobol_messages": " | ".join(c["messages"]), "sqr_messages": " | ".join(s["messages"]),
            "result": "MISMATCH" if diffs else "MATCH", "mismatched_fields": " ".join(diffs),
        })
    if mismatched_records:
        issues.append(f"{mismatched_records} record(s) differ between COBOL and SQR")

    ct, st = side["COBOL"]["parsed"]["totals"] or {}, side["SQR"]["parsed"]["totals"] or {}
    for key in ("count", "payroll"):
        if ct.get(key) != st.get(key):
            issues.append(f"total {key}: COBOL {ct.get(key)} vs SQR {st.get(key)}")
    if messages(cobol["console"]) != messages(sqr["console"]):
        issues.append("console messages differ")
    report_identical = cobol["report"] == sqr["report"]
    known = []
    if not report_identical:
        if (cobol["report"] is not None and sqr["report"] is not None
                and known_total_difference(cobol["report"], sqr["report"],
                                           side["COBOL"]["parsed"], side["SQR"]["parsed"])):
            known.append(f"total payroll >= $1,000,000: GnuCOBOL prints {ct['payroll_text'].strip()!r}, "
                         f"SQR prints {st['payroll_text'].strip()!r} (same value, zero suppression differs)")
        else:
            issues.append("report files are not byte-identical")
    for name, run in (("COBOL", cobol), ("SQR", sqr)):
        if run["returncode"] != 0:
            issues.append(f"{name} exited with status {run['returncode']}: {run['stderr'].strip()[:200]}")

    accepted = sum(1 for c in side["COBOL"]["classes"].values() if c["status"] == "ACCEPTED")
    return {
        "dataset": dataset, "records": len(records), "accepted": accepted,
        "rejected": len(records) - accepted,
        "cobol_total": ct.get("payroll_text", "").strip(), "sqr_total": st.get("payroll_text", "").strip(),
        "mismatched_records": mismatched_records, "report_identical": report_identical,
        "issues": issues, "known": known,
    }


def missing_input_case(cobol_cmd, sqr_cmd, workdir):
    cobol = run_program(cobol_cmd, workdir / "missing-input" / "cobol", None)
    sqr = run_program(sqr_cmd, workdir / "missing-input" / "sqr", None)
    issues = []
    for name, run in (("COBOL", cobol), ("SQR", sqr)):
        if run["report"] is not None:
            issues.append(f"{name} wrote a report without an input file")
        if not any(m.startswith("ERROR OPENING EMPLOYEE FILE: ") for m in messages(run["console"])):
            issues.append(f"{name} did not report ERROR OPENING EMPLOYEE FILE")
    return {"dataset": "missing-input", "records": 0, "accepted": 0, "rejected": 0,
            "cobol_total": "-", "sqr_total": "-", "mismatched_records": 0,
            "report_identical": True, "issues": issues, "known": []}


def unsuppressed_total(value):
    digits = f"{value:09.2f}"
    return f"${digits[0]},{digits[1:4]},{digits[4:]}"


def known_total_difference(cobol_report, sqr_report, cobol_parsed, sqr_parsed):
    """True if the reports differ only by GnuCOBOL's unsuppressed overflowed total."""
    c_lines, s_lines = cobol_report.split("\n"), sqr_report.split("\n")
    if len(c_lines) != len(s_lines):
        return False
    diff = [i for i, (a, b) in enumerate(zip(c_lines, s_lines)) if a != b]
    if len(diff) != 1 or not c_lines[diff[0]].startswith("TOTAL EMPLOYEES PROCESSED:"):
        return False
    ct, st = cobol_parsed["totals"] or {}, sqr_parsed["totals"] or {}
    if ct.get("count") != st.get("count") or ct.get("payroll") != st.get("payroll"):
        return False
    gross_total = sum((x["net"] or Decimal(0)) for x in cobol_parsed["details"])
    c_text, s_text = ct["payroll_text"], st["payroll_text"]
    return (gross_total >= 1_000_000 and c_text == unsuppressed_total(ct["payroll"])
            and c_lines[diff[0]].replace(c_text, s_text) == s_lines[diff[0]])


# ---------------------------------------------------------------- main

def build_datasets(args, data_dir):
    datasets = []
    if not args.no_fixtures:
        datasets += [(p.stem, p) for p in sorted((ROOT / "test" / "data").glob("*.DAT"))]
    for f in args.files:
        datasets.append((Path(f).stem, Path(f)))
    data_dir.mkdir(parents=True, exist_ok=True)

    def gen(name, profile, seed, records):
        path = data_dir / f"{name}.DAT"
        lines = generate_data.generate(profile, seed, records)
        path.write_text("".join(line + "\n" for line in lines))
        datasets.append((name, path))

    if args.edge:
        gen("GEN_EDGE", "edge", 0, 0)
    for i in range(args.random_files):
        seed = args.seed + i
        gen(f"GEN_MIXED_S{seed}", "mixed", seed, args.records)
    if args.volume:
        gen(f"GEN_VOLUME_{args.volume}", "volume", args.seed, args.volume)
    return datasets


def status(r):
    return "FAIL" if r["issues"] else "PASS (known difference)" if r["known"] else "PASS"


def write_summary(path, results, args, sqr_cmd):
    ok = all(not r["issues"] for r in results)
    lines = ["# COBOL vs SQR data validation", "",
             f"**Result: {'PASS' if ok else 'FAIL'}**", "",
             f"SQR runtime: `{sqr_cmd}`", "",
             "| Dataset | Records | Accepted | Rejected | COBOL total payroll | SQR total payroll | "
             "Mismatched records | Report identical | Result |",
             "|---|---:|---:|---:|---|---|---:|---|---|"]
    for r in results:
        lines.append(f"| {r['dataset']} | {r['records']} | {r['accepted']} | {r['rejected']} | "
                     f"`{r['cobol_total']}` | `{r['sqr_total']}` | {r['mismatched_records']} | "
                     f"{'yes' if r['report_identical'] else 'no (known difference)' if r['known'] else 'NO'} | "
                     f"{status(r)} |")
    failures = [r for r in results if r["issues"]]
    if failures:
        lines += ["", "## Issues", ""]
        for r in failures:
            lines += [f"- **{r['dataset']}**"] + [f"  - {i}" for i in r["issues"]]
    known = [r for r in results if r["known"]]
    if known:
        lines += ["", "## Known differences (not failures)", ""]
        for r in known:
            lines += [f"- **{r['dataset']}**"] + [f"  - {k}" for k in r["known"]]
    lines += ["", "Per-record detail: `reconciliation.csv`. Program outputs: `<dataset>/cobol`, `<dataset>/sqr`.", ""]
    path.write_text("\n".join(lines))
    return ok


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", help="additional employee files to validate")
    ap.add_argument("--results-dir", default=str(ROOT / "test" / "results"))
    ap.add_argument("--sqr-cmd", default=os.environ.get("SQR_CMD"),
                    help="command running ZPAYPROC standalone in the current directory (default: sqr_subset.py)")
    ap.add_argument("--random-files", type=int, default=3, help="number of random mixed files (default 3)")
    ap.add_argument("--records", type=int, default=1000, help="records per random file (default 1000)")
    ap.add_argument("--seed", type=int, default=1, help="first random seed (default 1)")
    ap.add_argument("--volume", type=int, default=10050,
                    help="records in the volume file, 0 to skip (default 10050: wraps the 9(4) counter)")
    ap.add_argument("--no-edge", dest="edge", action="store_false", help="skip the generated edge-case file")
    ap.add_argument("--no-fixtures", action="store_true", help="skip test/data/*.DAT")
    args = ap.parse_args()

    sqr_cmd_text = args.sqr_cmd or (f"python3 {ROOT}/test/sqr_subset.py {ROOT}/sqr/ZPAYPROC.sqr "
                                    f"-I {ROOT}/test/sqr_stubs")
    sqr_cmd = shlex.split(sqr_cmd_text)
    results_dir = Path(args.results_dir)
    if results_dir.exists():
        shutil.rmtree(results_dir)
    results_dir.mkdir(parents=True)

    with tempfile.TemporaryDirectory() as tmp:
        cobol_cmd = [str(compile_cobol(Path(tmp)))]
        datasets = build_datasets(args, results_dir / "generated")
        results, csv_rows = [], []
        for name, path in datasets:
            cobol = run_program(cobol_cmd, results_dir / name / "cobol", path)
            sqr = run_program(sqr_cmd, results_dir / name / "sqr", path)
            r = reconcile(name, path, cobol, sqr, csv_rows)
            results.append(r)
            print(f"{status(r)} {name}: {r['records']} records, "
                  f"{r['accepted']} accepted, {r['rejected']} rejected, total payroll {r['cobol_total'] or '-'}")
            for issue in r["issues"] + r["known"]:
                print(f"     {issue}")
        r = missing_input_case(cobol_cmd, sqr_cmd, results_dir)
        results.append(r)
        print(f"{'PASS' if not r['issues'] else 'FAIL'} missing-input")
        for issue in r["issues"]:
            print(f"     {issue}")

    with open(results_dir / "reconciliation.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(csv_rows[0].keys()) if csv_rows else ["dataset"])
        w.writeheader()
        w.writerows(csv_rows)
    ok = write_summary(results_dir / "summary.md", results, args, sqr_cmd_text)
    print(f"\n{'PASS' if ok else 'FAIL'}: results in {results_dir}")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
