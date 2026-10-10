#!/usr/bin/env python3
"""Minimal interpreter for the SQR subset used by sqr/ZPAYPROC.sqr.

There is no freely available SQR runtime, so test/compare_sqr.sh uses this to execute
the SQR source as written and compare it with the COBOL original. It implements only
what ZPAYPROC.sqr uses (#include/#define, global and local procedures with
parameters, let/if/while/do/display/open/read/write/close/commit, and the string and
numeric functions called), with DECIMAL arithmetic as declared in its setup section.
BEGIN-SELECT blocks are parsed but fail if executed (no database here).

Usage: sqr_subset.py PROGRAM.sqr [-I include_dir ...]
"""
import argparse
import os
import re
import sys
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, getcontext

getcontext().prec = 38


class SqrError(Exception):
    pass


# ---------------------------------------------------------------- preprocessing

def strip_comment(line):
    out, in_str = [], False
    for ch in line:
        if ch == "'":
            in_str = not in_str
        elif ch == "!" and not in_str:
            break
        out.append(ch)
    return "".join(out).rstrip()


def preprocess(path, include_dirs, defines):
    lines = []
    with open(path) as f:
        raw = f.read().splitlines()
    for text in raw:
        for name, value in defines.items():
            text = text.replace("{" + name + "}", value)
        stripped = text.strip()
        low = stripped.lower()
        if low.startswith("#include"):
            name = re.match(r"#include\s+'([^']+)'", stripped, re.I).group(1)
            for d in [os.path.dirname(path)] + include_dirs:
                candidate = os.path.join(d, name)
                if os.path.exists(candidate):
                    lines += preprocess(candidate, include_dirs, defines)
                    break
            else:
                raise SqrError(f"include not found: {name}")
            continue
        if low.startswith("#define"):
            _, name, value = stripped.split(None, 2)
            defines[name] = strip_comment(value).strip()
            continue
        if re.search(r"\{\w+\}", strip_comment(text)):
            raise SqrError(f"undefined substitution variable: {text}")
        line = strip_comment(text)
        if line.strip():
            lines.append(line)
    return lines


# ---------------------------------------------------------------- expressions

TOKEN_RE = re.compile(r"""
    \s*(?:
      (?P<str>'(?:[^']|'')*')
    | (?P<num>\d+(?:\.\d*)?|\.\d+)
    | (?P<var>[$#&][A-Za-z_][\w.-]*)
    | (?P<op>\|\||<>|!=|>=|<=|[-+*/()=<>,])
    | (?P<word>[A-Za-z_]\w*)
    )""", re.X)


def tokenize(expr):
    pos, tokens = 0, []
    expr = expr.rstrip()
    while pos < len(expr):
        m = TOKEN_RE.match(expr, pos)
        if not m or m.end() == pos:
            raise SqrError(f"cannot tokenize: {expr[pos:]!r}")
        pos = m.end()
        kind = m.lastgroup
        val = m.group(kind)
        if kind == "str":
            val = val[1:-1].replace("''", "'")
        elif kind == "word":
            val = val.lower()
        tokens.append((kind, val))
    return tokens


def to_dec(v):
    if isinstance(v, Decimal):
        return v
    raise SqrError(f"numeric value expected, got {v!r}")


def to_str(v):
    if isinstance(v, str):
        return v
    raise SqrError(f"string value expected, got {v!r}")


def f_substr(s, start, length):
    start, length = int(to_dec(start)), int(to_dec(length))
    s = to_str(s)
    return s[start - 1:start - 1 + length] if length > 0 else ""


def f_pad(s, length, pad, left):
    s, length, pad = to_str(s), int(to_dec(length)), to_str(pad)
    if len(s) >= length:
        return s[:length]
    fill = (pad * length)[:length - len(s)]
    return fill + s if left else s + fill


def f_trunc(n, places):
    return to_dec(n).quantize(Decimal(1).scaleb(-int(to_dec(places))), rounding=ROUND_DOWN)


def f_round(n, places):
    return to_dec(n).quantize(Decimal(1).scaleb(-int(to_dec(places))), rounding=ROUND_HALF_UP)


def f_to_number(s):
    try:
        return Decimal(to_str(s).strip())
    except Exception:
        return Decimal(0)


FUNCTIONS = {
    "substr": f_substr,
    "rpad": lambda s, n, p: f_pad(s, n, p, False),
    "lpad": lambda s, n, p: f_pad(s, n, p, True),
    "length": lambda s: Decimal(len(to_str(s))),
    "rtrim": lambda s, c: to_str(s).rstrip(to_str(c)),
    "ltrim": lambda s, c: to_str(s).lstrip(to_str(c)),
    "isblank": lambda s: Decimal(1 if to_str(s).strip() == "" else 0),
    "trunc": f_trunc,
    "round": f_round,
    "abs": lambda n: abs(to_dec(n)),
    "power": lambda a, b: to_dec(a) ** int(to_dec(b)),
    "to_number": f_to_number,
}


class Expr:
    def __init__(self, tokens, lookup):
        self.t, self.i, self.lookup = tokens, 0, lookup

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else (None, None)

    def take(self, val=None):
        tok = self.peek()
        if val is not None and tok[1] != val:
            raise SqrError(f"expected {val!r}, got {tok!r}")
        self.i += 1
        return tok

    def parse(self):
        v = self.p_or()
        if self.i != len(self.t):
            raise SqrError(f"trailing tokens: {self.t[self.i:]}")
        return v

    def p_or(self):
        v = self.p_and()
        while self.peek() == ("word", "or"):
            self.take()
            r = self.p_and()
            v = Decimal(1 if (v or r) else 0)
        return v

    def p_and(self):
        v = self.p_not()
        while self.peek() == ("word", "and"):
            self.take()
            r = self.p_not()
            v = Decimal(1 if (v and r) else 0)
        return v

    def p_not(self):
        if self.peek() == ("word", "not"):
            self.take()
            return Decimal(0 if self.p_not() else 1)
        return self.p_cmp()

    def p_cmp(self):
        v = self.p_concat()
        op = self.peek()[1]
        if op in ("=", "<>", "!=", "<", ">", "<=", ">="):
            self.take()
            r = self.p_concat()
            if type(v) is not type(r):
                raise SqrError(f"type mismatch comparing {v!r} {op} {r!r}")
            res = {"=": v == r, "<>": v != r, "!=": v != r, "<": v < r,
                   ">": v > r, "<=": v <= r, ">=": v >= r}[op]
            return Decimal(1 if res else 0)
        return v

    def p_concat(self):
        v = self.p_add()
        while self.peek()[1] == "||":
            self.take()
            v = to_str(v) + to_str(self.p_add())
        return v

    def p_add(self):
        v = self.p_mul()
        while self.peek()[1] in ("+", "-"):
            op = self.take()[1]
            r = to_dec(self.p_mul())
            v = to_dec(v) + r if op == "+" else to_dec(v) - r
        return v

    def p_mul(self):
        v = self.p_unary()
        while self.peek()[1] in ("*", "/"):
            op = self.take()[1]
            r = to_dec(self.p_unary())
            v = to_dec(v) * r if op == "*" else to_dec(v) / r
        return v

    def p_unary(self):
        if self.peek()[1] == "-":
            self.take()
            return -to_dec(self.p_unary())
        return self.p_atom()

    def p_atom(self):
        kind, val = self.take()
        if kind == "str":
            return val
        if kind == "num":
            return Decimal(val)
        if kind == "var":
            return self.lookup(val)
        if val == "(":
            v = self.p_or()
            self.take(")")
            return v
        if kind == "word" and val in FUNCTIONS:
            self.take("(")
            args = []
            if self.peek()[1] != ")":
                args.append(self.p_or())
                while self.peek()[1] == ",":
                    self.take()
                    args.append(self.p_or())
            self.take(")")
            return FUNCTIONS[val](*args)
        raise SqrError(f"unexpected token {val!r}")


# ---------------------------------------------------------------- program

class Procedure:
    def __init__(self, name, params, local, body):
        self.name, self.params, self.local, self.body = name, params, local, body


class Break(Exception):
    pass


class Interpreter:
    def __init__(self, lines):
        self.globals = {"#end-file": Decimal(0)}
        self.procs = {}
        self.program = None
        self.files = {}
        self.parse(lines)

    def parse(self, lines):
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            low = line.lower()
            if low == "begin-setup":
                while lines[i].strip().lower() != "end-setup":
                    i += 1
            elif low == "begin-program":
                j = self.find_end(lines, i, "end-program")
                self.program = lines[i + 1:j]
                i = j
            elif low.startswith("begin-procedure"):
                m = re.match(r"begin-procedure\s+([\w-]+)\s*(?:\((.*)\))?\s*(local)?\s*$", line, re.I)
                if not m:
                    raise SqrError(f"bad procedure header: {line}")
                params = [p.strip() for p in m.group(2).split(",")] if m.group(2) else []
                j = self.find_end(lines, i, "end-procedure")
                local = bool(m.group(2)) or bool(m.group(3))
                self.procs[m.group(1).lower()] = Procedure(m.group(1), params, local, lines[i + 1:j])
                i = j
            else:
                raise SqrError(f"unexpected top-level line: {line}")
            i += 1
        if self.program is None:
            raise SqrError("no begin-program section")

    @staticmethod
    def find_end(lines, i, end):
        for j in range(i + 1, len(lines)):
            if lines[j].strip().lower() == end:
                return j
        raise SqrError(f"missing {end}")

    # variables
    def make_lookup(self, frame):
        def lookup(name):
            key = name.lower()
            scope = self.scope_for(frame, key)
            if key not in scope:
                if key.startswith("&"):
                    raise SqrError(f"column variable not available: {name}")
                scope[key] = Decimal(0) if key.startswith("#") else ""
            return scope[key]
        return lookup

    def scope_for(self, frame, key):
        if key == "#end-file":
            return self.globals
        if frame is not None:
            if key[1:2] == "_" and key[0] in "$#&":
                return self.globals
            return frame
        return self.globals

    def setvar(self, frame, name, value):
        key = name.lower()
        if key.startswith("#") and not isinstance(value, Decimal):
            raise SqrError(f"cannot assign string to {name}")
        if key.startswith("$") and not isinstance(value, str):
            raise SqrError(f"cannot assign number to {name}")
        scope = self.scope_for(frame, key)
        if frame is not None and key[1:2] == "_":
            key = key[0] + key[2:]
        scope[key] = value

    def eval(self, expr, frame):
        return Expr(tokenize(expr), self.make_lookup(frame)).parse()

    # execution
    def run(self):
        self.exec_block(self.program, None)

    def exec_block(self, body, frame):
        i = 0
        while i < len(body):
            line = body[i].strip()
            low = line.lower()
            word = low.split()[0]
            if word == "if":
                j, else_at = self.match_block(body, i, "if", "end-if")
                if self.eval(line[2:], frame):
                    self.exec_block(body[i + 1:else_at if else_at else j], frame)
                elif else_at:
                    self.exec_block(body[else_at + 1:j], frame)
                i = j
            elif word == "while":
                j, _ = self.match_block(body, i, "while", "end-while")
                try:
                    while self.eval(line[5:], frame):
                        self.exec_block(body[i + 1:j], frame)
                except Break:
                    pass
                i = j
            elif low == "begin-select":
                raise SqrError("BEGIN-SELECT executed: no database in the test interpreter")
            else:
                self.exec_stmt(line, frame)
            i += 1

    @staticmethod
    def match_block(body, i, start, end):
        depth, else_at = 0, None
        for j in range(i, len(body)):
            w = body[j].strip().lower().split()[0]
            if w == start:
                depth += 1
            elif w == end:
                depth -= 1
                if depth == 0:
                    return j, else_at
            elif w == "else" and depth == 1 and start == "if":
                else_at = j
        raise SqrError(f"missing {end}")

    def exec_stmt(self, line, frame):
        low = line.lower()
        word = low.split()[0]
        if word == "let":
            m = re.match(r"let\s+([$#][\w.-]+)\s*=\s*(.*)$", line, re.I)
            self.setvar(frame, m.group(1), self.eval(m.group(2), frame))
        elif word == "do":
            self.call(line, frame)
        elif word == "display":
            m = re.match(r"display\s+(.*?)(\s+noline)?$", line, re.I)
            v = self.eval(m.group(1), frame)
            sys.stdout.write((v if isinstance(v, str) else str(v)) + ("" if m.group(2) else "\n"))
        elif word == "open":
            m = re.match(r"open\s+(\S+)\s+as\s+(\d+)\s+(for-reading|for-writing)\s+record=(\d+)(?::(vary|fixed))?"
                         r"(?:\s+status=(#[\w-]+))?\s*$", line, re.I)
            if not m:
                raise SqrError(f"unsupported open: {line}")
            name = self.eval(m.group(1), frame)
            try:
                self.files[int(m.group(2))] = open(name, "r" if m.group(3).lower() == "for-reading" else "w",
                                                   newline="\n")
                status = Decimal(0)
            except OSError:
                if not m.group(6):
                    raise SqrError(f"open failed: {name}")
                status = Decimal(-1)
            if m.group(6):
                self.setvar(frame, m.group(6), status)
        elif word == "read":
            m = re.match(r"read\s+(\d+)\s+into\s+(\$[\w-]+):(\d+)\s*$", line, re.I)
            text = self.files[int(m.group(1))].readline()
            if text == "":
                self.globals["#end-file"] = Decimal(1)
            else:
                self.globals["#end-file"] = Decimal(0)
                self.setvar(frame, m.group(2), text.rstrip("\n")[:int(m.group(3))])
        elif word == "write":
            m = re.match(r"write\s+(\d+)\s+from\s+(\$[\w-]+):(\d+)\s*$", line, re.I)
            width = int(m.group(3))
            value = to_str(self.eval(m.group(2), frame))
            self.files[int(m.group(1))].write(value[:width].ljust(width) + "\n")
        elif word == "close":
            self.files.pop(int(line.split()[1])).close()
        elif word == "break":
            raise Break()
        elif word == "commit":
            pass
        else:
            raise SqrError(f"unsupported statement: {line}")

    def call(self, line, frame):
        m = re.match(r"do\s+([\w-]+)\s*(?:\((.*)\))?\s*$", line, re.I)
        proc = self.procs.get(m.group(1).lower())
        if proc is None:
            raise SqrError(f"undefined procedure: {m.group(1)}")
        args = split_args(m.group(2)) if m.group(2) else []
        if len(args) != len(proc.params):
            raise SqrError(f"{proc.name}: expected {len(proc.params)} args, got {len(args)}")
        if not proc.local:
            self.exec_block(proc.body, None)
            return
        new_frame = {}
        for param, arg in zip(proc.params, args):
            name = param.lstrip(":")
            if not param.startswith(":"):
                self.setvar(new_frame, name, self.eval(arg, frame))
            else:
                new_frame[name.lower()] = Decimal(0) if name.startswith("#") else ""
        self.exec_block(proc.body, new_frame)
        for param, arg in zip(proc.params, args):
            if param.startswith(":"):
                self.setvar(frame, arg, new_frame[param[1:].lower()])


def split_args(text):
    args, depth, cur, in_str = [], 0, [], False
    for ch in text:
        if ch == "'":
            in_str = not in_str
        if not in_str:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            elif ch == "," and depth == 0:
                args.append("".join(cur).strip())
                cur = []
                continue
        cur.append(ch)
    args.append("".join(cur).strip())
    return args


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("program")
    ap.add_argument("-I", dest="include", action="append", default=[])
    a = ap.parse_args()
    try:
        Interpreter(preprocess(a.program, a.include, {})).run()
    except SqrError as e:
        sys.stdout.flush()
        print(f"sqr_subset: {e}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
