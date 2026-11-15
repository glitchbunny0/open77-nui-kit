#!/usr/bin/env python3
"""rmlhost checks: run the host binary given on the command line against the probe documents in this folder and
assert what it prints (check outline and clicks, layout numbers, parity dumps, errors on bad input).

  checks.py HOST [--only CHECK-PREFIX]

Prints "ok <check>" or "FAIL <check>: why" per check; exits 1 when any failed. Needs only the standard library.
"""
import json, os, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = os.path.abspath(sys.argv[1])
ONLY = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == '--only' else None
CHECKS = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


class Run:
    def __init__(self, r):
        self.rc, self.err = r.returncode, r.stderr.decode('utf-8', 'replace')
        try:
            self.out = r.stdout.decode('utf-8')   # strict: invalid UTF-8 from the host is a failure
            self.utf8 = True
        except UnicodeDecodeError as e:
            self.out, self.utf8 = r.stdout.decode('utf-8', 'replace'), str(e)


def host(mode, *args, cases, timeout=10):
    """Run the host in this folder. cases: a Python value (sent as json.dumps does by default, ASCII with \\u escapes,
    as the wrappers send it) or str/bytes sent as is."""
    data = cases if isinstance(cases, (str, bytes)) else json.dumps(cases)
    if isinstance(data, str):
        data = data.encode('utf-8')
    return Run(subprocess.run([HOST, mode, *args], input=data, capture_output=True, timeout=timeout, cwd=HERE))


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main():
    failed = 0
    for name, fn in CHECKS:
        if ONLY and not name.startswith(ONLY):
            continue
        try:
            fn()
            print('ok ' + name)
        except Exception as e:   # an assertion, a timeout, a crash in the check itself: all red
            failed += 1
            msg = str(e).replace('\n', ' | ')
            print(f'FAIL {name}: {type(e).__name__ + ": " if not isinstance(e, AssertionError) else ""}{msg[:600]}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
