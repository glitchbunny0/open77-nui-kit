#!/usr/bin/env python3
"""Mutation runs for html2rml's checks: each mutant is a copy of converter/ with ONE planted bug, and the check named
with it (a fixture, or a unit test label) must turn red on that copy alone. A mutant whose `old` text is not found
exactly once fails the run too (the converter moved: update the mutant).

  converter/tests/mutants.py [ID ...]          (runs into $NUIKIT_TMP, or a fresh temp dir)
"""
import os, shutil, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(os.path.dirname(HERE))

# (id, file under converter/, old, new, check) - check: 'fixture NAME' or 'unit LABEL'
MUTANTS = [
]


def run(ids):
    tmp = os.environ.get('NUIKIT_TMP') or tempfile.mkdtemp(prefix='html2rml-mut-')
    env = dict(os.environ, HTML2RML_KIT=KIT, PYTHONDONTWRITEBYTECODE='1')
    bad = 0
    for mid, fn, old, new, check in MUTANTS:
        if ids and mid not in ids:
            continue
        d = os.path.join(tmp, 'mutant-' + mid)
        shutil.rmtree(d, ignore_errors=True)
        shutil.copytree(os.path.join(KIT, 'converter'), os.path.join(d, 'converter'),
                        ignore=shutil.ignore_patterns('.out', '__pycache__'))
        p = os.path.join(d, 'converter', fn)
        src = open(p, encoding='utf-8').read()
        if src.count(old) != 1:
            print(f'FAIL {mid}: the planted text occurs {src.count(old)} times in {fn} (want 1)')
            bad += 1
            continue
        with open(p, 'w', encoding='utf-8') as fh:
            fh.write(src.replace(old, new))
        kind, _, what = check.partition(' ')
        cmd = [sys.executable, os.path.join(d, 'converter', 'tests', 'run.py')]
        cmd += ['--unit=' + what] if kind == 'unit' else [what]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, env=dict(env, NUIKIT_TMP=d), timeout=120)
            rc = r.returncode
        except subprocess.TimeoutExpired:
            rc = 'timeout'
        if rc == 0:
            print(f'FAIL {mid}: {check} stayed green with the bug planted')
            bad += 1
        else:
            print(f'ok   {mid}: {check} red')
    print(f'mutants: {len([m for m in MUTANTS if not ids or m[0] in ids]) - bad} red, {bad} missed')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(run(sys.argv[1:]))
