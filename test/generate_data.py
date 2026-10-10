#!/usr/bin/env python3
"""Generate EMPLOYEE.DAT-format test files for COBOL vs SQR data validation.

EMP-RECORD layout (45 bytes, LINE SEQUENTIAL):
  EMP-ID X(5) | EMP-NAME X(25) | EMP-DEPT X(4) | EMP-HOURS 9(3)V99 | EMP-HOURLY-RATE 9(3)V99 | EMP-TYPE X(1)

Profiles:
  edge   - fixed list of boundary cases (overtime threshold, overflow, rounding, bad data)
  mixed  - seeded random mix of valid and invalid records
  volume - valid records only (use > 9999 records to exercise counter wrap-around)

Usage: generate_data.py --profile mixed --seed 7 --records 500 --out FILE
"""
import argparse
import random

NAMES = ["ALICE", "BOB", "CAROL", "DAVID", "EVE", "FRANK", "GRACE", "HENRY", "IVY", "JACK",
         "KATE", "LEO", "MIA", "NOAH", "OLIVIA", "PAUL", "QUINN", "RUTH", "SAM", "TINA"]
SURNAMES = ["JOHNSON", "SMITH", "WHITE", "BROWN", "JONES", "GARCIA", "MILLER", "DAVIS",
            "WILSON", "TAYLOR", "THOMAS", "MOORE", "MARTIN", "LEE", "PEREZ", "CLARK"]
DEPTS = ["ENG ", "OPS ", "FIN ", "HR  ", "EXEC", "SALE", "IT  ", "LGL "]


def record(emp_id, name, dept, hours, rate, emp_type):
    """hours/rate are 5-char raw fields, or ints (hundredths) to be zero padded."""
    if isinstance(hours, int):
        hours = f"{hours:05d}"
    if isinstance(rate, int):
        rate = f"{rate:05d}"
    return f"{emp_id:<5.5}{name:<25.25}{dept:<4.4}{hours}{rate}{emp_type}"


def edge_records():
    r = []
    add = lambda *a: r.append(record(*a))
    add("X0001", "OT THRESHOLD 40.00", "OPS ", 4000, 2500, "H")
    add("X0002", "OT THRESHOLD 40.01", "OPS ", 4001, 2500, "H")
    add("X0003", "OT THRESHOLD 39.99", "OPS ", 3999, 2500, "H")
    add("X0004", "HOURLY MAX", "OPS ", 99999, 99999, "H")
    add("X0005", "SALARIED MAX", "EXEC", 99999, 99999, "S")
    add("X0006", "GROSS JUST UNDER WRAP", "EXEC", 99999, 10000, "S")
    add("X0007", "GROSS EXACT 100000", "EXEC", 50000, 20000, "S")
    add("X0008", "ZERO HOURS", "OPS ", 0, 2500, "H")
    add("X0009", "ZERO RATE", "OPS ", 4000, 0, "S")
    add("X0010", "MIN NONZERO", "FIN ", 1, 1, "S")
    add("X0011", "TAX HALF CENT UP", "FIN ", 100, 2, "S")
    add("X0012", "TAX HALF CENT 0.06", "FIN ", 100, 6, "S")
    add("X0013", "TAX QUARTER CENT", "FIN ", 100, 1, "S")
    add("X0014", "TAX THREE QTR CENT", "FIN ", 100, 3, "S")
    add("X0015", "OT FRACTION", "OPS ", 4033, 1777, "H")
    add("X0016", "OT HALF CENT TRUNC", "OPS ", 4001, 1, "H")
    add("X0017", "SALARIED FRACTION", "FIN ", 1234, 5678, "S")
    add("X0018", "HOURS LEADING SPACE", "HR  ", " 4000", 2000, "H")
    add("X0019", "HOURS TRAILING SPACE", "HR  ", "4000 ", 2000, "H")
    add("X0020", "HOURS PLUS SIGN", "HR  ", "+4000", 2000, "H")
    add("X0021", "HOURS MINUS SIGN", "HR  ", "-4000", 2000, "H")
    add("X0022", "HOURS DECIMAL POINT", "HR  ", "40.00", 2000, "H")
    add("X0023", "RATE LETTERS", "HR  ", 4000, "ABCDE", "H")
    add("X0024", "RATE ALL SPACES", "HR  ", 4000, "     ", "S")
    add("X0025", "BOTH NON NUMERIC", "HR  ", "4O000", "2O000", "S")
    add("X0026", "TYPE LOWER S", "HR  ", 4000, 2000, "s")
    add("X0040", "TYPE LOWER H", "HR  ", 4500, 2000, "h")
    add("X0027", "TYPE SPACE", "HR  ", 4000, 2000, " ")
    add("X0028", "TYPE DIGIT", "HR  ", 4000, 2000, "1")
    add("X0029", "ALL BAD", "HR  ", "?????", "     ", "Z")
    r.append(record("X0030", "SHORT NO TYPE", "ENG ", 4000, 2000, "")[:44])
    r.append("X0031")
    r.append("")
    r.append(record("X0032", "LONG LINE", "ENG ", 4000, 2000, "H") + "TRAILING-GARBAGE-1234567890")
    r.append(record("X0033", "LONG LINE BAD TYPE", "ENG ", 4000, 2000, "") + "XHS")
    add("     ", "BLANK ID", "ENG ", 4000, 2000, "H")
    add("X0035", "", "", 4000, 2000, "S")
    add("X0036", "PUNCT !@#$%^&*()_+=", "ENG ", 4000, 2000, "H")
    add("X0001", "DUPLICATE ID", "OPS ", 4000, 2500, "H")
    return r


def random_valid(rng, emp_id):
    name = f"{rng.choice(NAMES)} {rng.choice(SURNAMES)}"
    dept = rng.choice(DEPTS)
    emp_type = rng.choice("HS")
    roll = rng.random()
    if roll < 0.03:
        hours, rate = rng.randint(90000, 99999), rng.randint(90000, 99999)
    elif emp_type == "H":
        hours = rng.choice([4000, rng.randint(0, 4000), rng.randint(4000, 8000), rng.randint(0, 99999)])
        rate = rng.randint(725, 15000)
    else:
        hours = rng.choice([8000, 16000, rng.randint(0, 20000)])
        rate = rng.randint(1000, 25000)
    return record(emp_id, name, dept, hours, rate, emp_type)


def random_invalid(rng, emp_id):
    base = random_valid(rng, emp_id)
    kind = rng.choice(["hours", "rate", "both", "type", "short", "long", "blank", "all"])
    junk = lambda: "".join(rng.choice("0123456789 ABCXYZ.-+?") for _ in range(5))
    if kind == "hours":
        return base[:34] + junk() + base[39:]
    if kind == "rate":
        return base[:39] + junk() + base[44:]
    if kind == "both":
        return base[:34] + junk() + junk() + base[44:]
    if kind == "type":
        return base[:44] + rng.choice("hsXZ 0*")
    if kind == "short":
        return base[:rng.randint(0, 44)]
    if kind == "long":
        return base + "".join(rng.choice("ABCDEFGH0123456789 ") for _ in range(rng.randint(1, 40)))
    if kind == "blank":
        return ""
    return base[:34] + junk() + junk() + rng.choice("hsXZ 0*")


def generate(profile, seed, records):
    if profile == "edge":
        return edge_records()
    rng = random.Random(seed)
    lines = []
    for i in range(records):
        emp_id = f"{chr(65 + (i // 10000) % 26)}{i % 10000:04d}"
        if profile == "mixed" and rng.random() < 0.2:
            lines.append(random_invalid(rng, emp_id))
        else:
            lines.append(random_valid(rng, emp_id))
    return lines


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", choices=["edge", "mixed", "volume"], default="mixed")
    ap.add_argument("--seed", type=int, default=1)
    ap.add_argument("--records", type=int, default=500)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    lines = generate(a.profile, a.seed, a.records)
    with open(a.out, "w", newline="\n") as f:
        f.write("".join(line + "\n" for line in lines))


if __name__ == "__main__":
    main()
