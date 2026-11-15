#!/usr/bin/env python3
"""html2rml fixture tests: every fixtures/<name>/index.html is converted and compared with its snapshot
(expected.rml, expected.rcss, expected.report.txt), and the converted document must pass rml-check (real RmlUi).

  converter/tests/run.py [--regen] [--no-check] [NAME ...]

--regen rewrites the snapshots from the current converter (review the diff before committing). A fixture may hold
args.txt (extra html2rml options) and cases.json (the cases for rml-check; default: one empty case).
"""
import difflib, json, os, shutil, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
KIT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, KIT)
sys.dont_write_bytecode = True
from converter.convert import convert, report_md  # noqa: E402
from converter import css_values as V  # noqa: E402
from converter.cli import main as cli_main  # noqa: E402


def report_txt(c):
    return ''.join(f'{i["kind"]:8} {i["file"]}:{i["line"]}  {i["what"]}  =>  {i["todo"]}\n' for i in c.report.items)


def unit_tests():
    """the value layer on its own"""
    fails = []

    def eq(got, want, what):
        if got != want:
            fails.append(f'{what}: got {got!r}, want {want!r}')
    U = V.Units(1.0, (1920, 1080), 16)

    def conv(s, look=None):
        t = V.tokenize(s)
        t = V.resolve_vars(t, look or (lambda n: None))
        t = V.convert_units(t, U, [])
        t = V.fold_math(t)
        t = V.convert_colors(t)
        return V.ser(t)
    eq(conv('calc(80 * 0.5px)'), '40dp', 'calc multiply')
    eq(conv('calc((2px + 4px) * 3)'), '18dp', 'calc parens')
    eq(conv('calc(10px - -2px)'), '12dp', 'calc negative')
    eq(conv('min(10px, 2vw)'), '10dp', 'min')
    eq(conv('50vw'), '960dp', 'vw')
    eq(conv('2rem'), '32dp', 'rem')
    eq(conv('250ms'), '0.25s', 'ms')
    eq(conv('rgba(255, 97, 89, .5)'), '#FF615980', 'rgba alpha')
    eq(conv('rgb(255 97 89 / 22%)'), '#FF615938', 'rgb slash')
    eq(conv('hsl(0, 100%, 50%)'), '#FF0000', 'hsl')
    eq(conv('rebeccapurple'), '#663399', 'named')
    eq(conv('var(--a, var(--b, 3px))', lambda n: {'--b': '5px'}.get(n)), '5dp', 'nested fallback')
    try:
        conv('calc(100% - 20px)')
        fails.append('calc mixing % and px must fail')
    except V.ValueIssue:
        pass
    try:
        conv('var(--x)', lambda n: 'var(--x)')
        fails.append('a var() cycle must fail')
    except V.ValueIssue:
        pass
    return fails


def main(argv):
    regen = '--regen' in argv
    check = '--no-check' not in argv
    only = [a for a in argv if not a.startswith('--')]
    fails = unit_tests()
    print(f'unit: {"ok" if not fails else "FAIL"}')
    for f in fails:
        print('  ' + f)
    fx = os.path.join(HERE, 'fixtures')
    outroot = os.path.join(HERE, '.out')
    n = 0
    for name in sorted(os.listdir(fx)):
        if only and name not in only:
            continue
        d = os.path.join(fx, name)
        page = os.path.join(d, 'index.html')
        if not os.path.exists(page):
            continue
        n += 1
        out = os.path.join(outroot, name)
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(out)
        args = open(os.path.join(d, 'args.txt')).read().split() if os.path.exists(os.path.join(d, 'args.txt')) else []
        import io, contextlib
        with contextlib.redirect_stdout(io.StringIO()):
            cli_main([page, '--out', out, '--name', 'page', '--report', 'json'] + args)
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
            r = subprocess.run([sys.executable, os.path.join(KIT, 'bin', 'rml-check'), os.path.join(out, 'page.rml'),
                                cases, '--quiet'], capture_output=True, text=True)
            if r.returncode != 0:
                bad.append('rml-check')
                status += ' / rml-check FAIL:\n' + r.stdout + r.stderr
            else:
                status += ' / rml-check ok'
        print(f'{name}: {status}  ({len(rep["items"])} reported)')
        if bad:
            fails.append(name)
    print(f'{n} fixtures, {len(fails)} failing')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
