#!/usr/bin/env python3
"""html2rml fixture tests: every fixtures/<name>/index.html is converted and compared with its snapshot
(expected.rml, expected.rcss, expected.report.txt), the converted document must pass rml-check (real RmlUi), and a
fixture's layout.json (if any) states what real RmlUi computes for it (colours, sizes: `rmlhost layout`).

  converter/tests/run.py [--regen] [--no-check] [--unit[=LABEL]] [NAME ...]

--regen rewrites the snapshots from the current converter (review the diff before committing). A fixture may hold
args.txt (extra html2rml options), cases.json (the cases for rml-check; default: one empty case) and layout.json:
  {"cases": [...] (default: cases.json), "expect": [{"case": NAME (default: the first), "sel": "#id" | ".class" |
   "tag", "nth": N (default 0: the Nth element the selector picks), FIELD: VALUE, ...}]}
FIELD is a field of `rmlhost layout`'s element output (bg, color, w, h, x, y, bt, btc, op, ...).
--unit runs the unit tests of the value layer only (=LABEL: those whose label starts with LABEL); NAME runs only those
fixtures. Output goes to $NUIKIT_TMP when set (the kit's suite contract), else converter/tests/.out.
HTML2RML_KIT names the kit whose bin/rml-check and host are used (default: this one; the mutation runs point it at the
real kit while they import a mutated converter).
"""
import contextlib, difflib, io, json, os, re, shutil, signal, subprocess, sys, types

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(os.path.dirname(HERE))
TOOLS = os.environ.get('HTML2RML_KIT') or KIT
sys.path.insert(0, KIT)
sys.dont_write_bytecode = True
from converter import css_values as V  # noqa: E402
from converter import css_props as P  # noqa: E402
from converter.cli import main as cli_main  # noqa: E402
from converter.convert import report_md  # noqa: E402

UNITS = V.Units(1.0, (1920, 1080), 16)


def conv(s, look=None):
    t = V.tokenize(s)
    t = V.resolve_vars(t, look or (lambda n: None))
    t = V.convert_units(t, UNITS, [])
    t = V.fold_math(t)
    t = V.convert_colors(t)
    return V.ser(t)


def raises(fn):
    try:
        fn()
    except V.ValueIssue:
        return True
    return False


# the value layer on its own: (label, thunk, want)
UNIT = [
    ('calc multiply', lambda: conv('calc(80 * 0.5px)'), '40dp'),
    ('calc parens', lambda: conv('calc((2px + 4px) * 3)'), '18dp'),
    ('calc negative', lambda: conv('calc(10px - -2px)'), '12dp'),
    ('min', lambda: conv('min(10px, 2vw)'), '10dp'),
    ('vw', lambda: conv('50vw'), '960dp'),
    ('rem', lambda: conv('2rem'), '32dp'),
    ('ms', lambda: conv('250ms'), '0.25s'),
    ('rgba alpha', lambda: conv('rgba(255, 97, 89, .5)'), '#FF615980'),
    ('rgb slash', lambda: conv('rgb(255 97 89 / 22%)'), '#FF615938'),
    ('hsl', lambda: conv('hsl(0, 100%, 50%)'), '#FF0000'),
    ('hsl hue in rad', lambda: conv('hsl(2.0944rad, 100%, 50%)'), '#00FF00'),
    ('hsl half rounds up', lambda: conv('hsla(332, 100%, 25%, 0)'), '#80003C00'),
    ('lab passes as RmlUi reads it', lambda: conv('lab(50% 40 59.5)'), 'lab(50% 40 59.5)'),
    ('oklch passes, alpha kept', lambda: conv('oklch(63% 0.25 30deg / 0.8)'), 'oklch(63% 0.25 30 / 0.8)'),
    ('lch hue in rad as degrees', lambda: conv('lch(50% 40 1rad)'), 'lch(50% 40 57.2958)'),
    ('color-mix() fails', lambda: raises(lambda: conv('color-mix(in srgb, red, blue)')), True),
    ("exponential tween is RmlUi's e^(7.24(t-1))", lambda: round(P._tween_fn('exponential-in')(0.5), 4), 0.0268),
    ('back tweens are fitted', lambda: P.fit_tween((.34, 1.56, .64, 1))[0], 'back-out'),
    ('named', lambda: conv('rebeccapurple'), '#663399'),
    ('nested fallback', lambda: conv('var(--a, var(--b, 3px))', lambda n: {'--b': '5px'}.get(n)), '5dp'),
    ('calc mixing % and px fails', lambda: raises(lambda: conv('calc(100% - 20px)')), True),
    ('a var() cycle fails', lambda: raises(lambda: conv('var(--x)', lambda n: 'var(--x)')), True),
    # CSS escapes: decoded, and never a hang (a lone backslash, an escape at the end)
    ('report: a row stays one line', lambda: [l for l in report_md(types.SimpleNamespace(
        page='p.html', name='p', canvas=(1, 1), units=V.Units(), fonts=[], report=types.SimpleNamespace(items=[
            {'file': 'a.css', 'line': 1, 'kind': 'css', 'what': 'a\n  b', 'todo': 'c\nd'}]))).splitlines()
        if l.startswith('| a.css')], ['| a.css:1 | a b | c d |']),
    ('escape: hex code points', lambda: V.tokenize(r'\5FAE\8F6F, x'),
     [('ident', '\u5fae\u8f6f'), ('comma',), ('ws',), ('ident', 'x')]),
    ('escape: digit after a dash', lambda: V.tokenize(r'-\31 x'), [('ident', '-1x')]),
    ('escape: a lone backslash', lambda: V.tokenize('a\\'), [('ident', 'a'), ('delim', '\\')]),
]


class Hang(Exception):
    pass


def with_timeout(sec, fn):
    def alarm(*_):
        raise Hang(f'no result in {sec} s')
    old = signal.signal(signal.SIGALRM, alarm)
    signal.alarm(sec)
    try:
        return fn()
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def unit_tests(only=None):
    fails = []
    for label, fn, want in UNIT:
        if only and not label.startswith(only):
            continue
        try:
            got = with_timeout(5, fn)
        except Exception as e:   # noqa: BLE001 - a crash or a hang fails that check
            got = f'{type(e).__name__}: {e}'
        if got != want:
            fails.append(f'{label}: got {got!r}, want {want!r}')
    return fails


_HOST = []


def host():
    if not _HOST:
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'scripts', 'build.py')], capture_output=True)
        if r.returncode != 0:
            raise RuntimeError('building the host failed:\n' + r.stderr.decode('utf-8', 'replace'))
        _HOST.append(r.stdout.decode('utf-8').strip().splitlines()[-1])
    return _HOST[0]


def picks(els, sel):
    if sel.startswith('#'):
        return [e for e in els if e.get('id') == sel[1:]]
    if sel.startswith('.'):
        return [e for e in els if sel[1:] in (e.get('cls') or '').split()]
    return [e for e in els if e.get('tag') == sel]


def layout_check(d, out, rml):
    """layout.json: what real RmlUi computes for the converted document -> list of failures"""
    spec = json.load(open(os.path.join(d, 'layout.json')))
    cases = spec.get('cases')
    if cases is None:
        cp = os.path.join(d, 'cases.json')
        cases = json.load(open(cp)) if os.path.exists(cp) else [{'name': 'default'}]
    fj = os.path.join(out, 'fonts.json')
    with open(fj, 'w') as fh:
        json.dump({'x|400': {'ascent': 900, 'descent': 300, 'def': 500, 'adv': {}}}, fh)
    m = re.search(r'data-model="([^"]+)"', rml)
    r = subprocess.run([host(), 'layout', os.path.join(out, 'page.rml'), m.group(1) if m else 'm', fj],
                       input=json.dumps(cases), capture_output=True, text=True)
    try:
        res = {c['name']: c['els'] for c in json.loads(r.stdout)}
    except (ValueError, KeyError, TypeError):
        return ['no layout output: ' + (r.stdout + r.stderr)[:300]]
    bad = []
    for x in spec['expect']:
        case = x.get('case') or cases[0]['name']
        els = picks(res.get(case, []), x['sel'])
        k = x.get('nth', 0)
        if k >= len(els):
            bad.append(f'{case}: {x["sel"]}[{k}] not found ({len(els)} picked)')
            continue
        for f, want in x.items():
            if f not in ('case', 'sel', 'nth') and els[k].get(f) != want:
                bad.append(f'{case}: {x["sel"]}[{k}] {f} = {els[k].get(f)!r}, want {want!r}')
    return bad


def run_fixture(d, out, regen, check):
    # the fixture is converted from a copy next to the output (out/../../fixtures/NAME): the relative asset paths in
    # the snapshots do not depend on where the run writes
    src = os.path.join(os.path.dirname(os.path.dirname(out)), 'fixtures', os.path.basename(d))
    if os.path.realpath(src) != os.path.realpath(d):
        shutil.rmtree(src, ignore_errors=True)
        shutil.copytree(d, src)
    page = os.path.join(src, 'index.html')
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    ap = os.path.join(d, 'args.txt')
    args = open(ap).read().split() if os.path.exists(ap) else []
    try:
        with contextlib.redirect_stdout(io.StringIO()):
            with_timeout(30, lambda: cli_main([page, '--out', out, '--name', 'page', '--report', 'json'] + args))
    except Exception as e:   # noqa: BLE001
        return ['convert'], f'FAIL: conversion raised {type(e).__name__}: {e}', 0
    got = {'expected.rml': open(os.path.join(out, 'page.rml')).read(),
           'expected.rcss': open(os.path.join(out, 'page.rcss')).read()}
    rep = json.load(open(os.path.join(out, 'page.report.json')))
    got['expected.report.txt'] = ''.join(f'{i["kind"]:8} {i["file"]}:{i["line"]}  {i["what"]}  =>  {i["todo"]}\n'
                                         for i in rep['items'])
    bad = []
    for fn, txt in got.items():
        p = os.path.join(d, fn)
        if regen:
            with open(p, 'w') as fh:
                fh.write(txt)
            continue
        want = open(p).read() if os.path.exists(p) else ''
        if want != txt:
            bad.append(fn)
            sys.stdout.writelines(difflib.unified_diff(want.splitlines(True), txt.splitlines(True), fn, 'now', n=1))
    status = 'regen' if regen else ('ok' if not bad else 'FAIL ' + ', '.join(bad))
    if check:
        cases = os.path.join(d, 'cases.json')
        if not os.path.exists(cases):
            cases = os.path.join(out, 'cases.json')
            with open(cases, 'w') as fh:
                json.dump([{'name': 'default', 'model': {}}] if 'data-model' in got['expected.rml']
                          else [{'name': 'default'}], fh)
        # warnings a fixture causes on purpose (a missing image it tests), one regex a line
        allow = os.path.join(d, 'rml-check-allow.txt')
        extra = [a for ln in (open(allow).read().splitlines() if os.path.exists(allow) else []) if ln for a in ('--allow', ln)]
        r = subprocess.run([sys.executable, os.path.join(TOOLS, 'bin', 'rml-check'), os.path.join(out, 'page.rml'),
                            cases, '--quiet'] + extra, capture_output=True, text=True)
        if r.returncode != 0:
            bad.append('rml-check')
            status += ' / rml-check FAIL:\n' + r.stdout + r.stderr
        else:
            status += ' / rml-check ok'
        if os.path.exists(os.path.join(d, 'layout.json')):
            lb = layout_check(d, out, got['expected.rml'])
            if lb:
                bad.append('layout')
                status += ' / layout FAIL:\n  ' + '\n  '.join(lb)
            else:
                status += ' / layout ok'
    return bad, status, len(rep['items'])


def main(argv):
    regen = '--regen' in argv
    check = '--no-check' not in argv
    unit = [a for a in argv if a == '--unit' or a.startswith('--unit=')]
    only = [a for a in argv if not a.startswith('--')]
    fails = []
    if not only:
        fails = unit_tests((unit[0].partition('=')[2] or None) if unit else None)
        print(f'unit: {"ok" if not fails else "FAIL"}')
        for f in fails:
            print('  ' + f)
        if unit:
            return 1 if fails else 0
    fx = os.path.join(HERE, 'fixtures')
    tmp = os.environ.get('NUIKIT_TMP')
    outroot = os.path.join(tmp, 'html2rml-fixtures') if tmp else os.path.join(HERE, '.out')
    missing = sorted(set(only) - set(os.listdir(fx)))
    if missing:
        print('no such fixture: ' + ', '.join(missing))
        return 1
    n = 0
    for name in sorted(os.listdir(fx)):
        d = os.path.join(fx, name)
        if (only and name not in only) or not os.path.exists(os.path.join(d, 'index.html')):
            continue
        n += 1
        bad, status, items = run_fixture(d, os.path.join(outroot, '.out', name), regen, check)
        print(f'{name}: {status}  ({items} reported)')
        if bad:
            fails.append(name)
    print(f'{n} fixtures, {len(fails)} failing')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
