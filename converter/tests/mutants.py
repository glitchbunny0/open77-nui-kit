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
    ('escape-ident', 'css_values.py', r"(?:\\[0-9a-fA-F]{1,6}[ \t\n]?|\\[^\n0-9a-fA-F]|[\w\u00a0-\uffff-])*')",
     r"[\w\u00a0-\uffff-]*')", 'unit escape'),
    # implied <html>/<head>/<body>, content outside the body (L6-2, L6-12, L7-1)
    ('implied-html', 'html_parse.py', "html = Element('html', [], first.line", "html = Element('div', [], first.line",
     'fixture 11-no-tags'),
    ('no-body-flow', 'html_parse.py', '_adopt(body, before, 0)', '_adopt(body, [], 0)', 'fixture 12-no-body'),
    ('head-flow', 'html_parse.py', 'before = moved + before', 'before = before', 'fixture 01-markup'),
    ('after-body', 'html_parse.py', '_adopt(body, after)', '_adopt(body, [])', 'fixture 01-markup'),
    # values RmlUi parses differently (L5)
    ('translate-1arg', 'css_props.py', "if name == 'translate' and len(args) == 1:", "if name == 'translate' and len(args) == 0:",
     'fixture 13-values'),
    ('skew-1arg', 'css_props.py', "if name == 'skew' and len(args) == 1:", "if name == 'skew' and len(args) == 0:",
     'fixture 13-values'),
    ('scale-pct', 'css_props.py', "a[0][0] == 'num' and a[0][2] == '%' else a", "a[0][0] == 'num' and a[0][2] == '%%' else a",
     'fixture 13-values'),
    ('transition-dropped-item', 'css_props.py', 'if named and not props:', 'if False:', 'fixture 13-values'),
    ('transition-all-alone', 'css_props.py', "if 'all' in (props or ['all']) and len(items) > 1:",
     "if 'all' in (props or ['all']) and len(items) > 99:", 'fixture 13-values'),
    ('radial-size-first', 'css_props.py', 'words = shape + size', 'words = size + shape', 'fixture 13-values'),
    ('gradient-in-space', 'css_props.py', "    if 'in' in words:\n        k = words.index('in')",
     "    if 'in' in []:\n        k = words.index('in')", 'fixture 13-values'),
    ('position-4value', 'css_props.py', '    if len(words) <= 2:\n        return list(words)',
     '    if len(words) <= 4:\n        return list(words)', 'fixture 13-values'),
    ('webkit-gradient', 'css_props.py', '    if legacy:   # the prefixed form', '    if False:   # the prefixed form',
     'fixture 13-values'),
    ('tile-modes', 'css_props.py', "('no-repeat', 'repeat'): 'repeat-y'}.get(xy, 'scale-none')",
     "('no-repeat', 'repeat'): 'repeat-y'}.get((), 'scale-none')", 'fixture 13-values'),
    ('align-px', 'css_props.py', "x, y = [v[:-2] + 'px' if v.endswith('dp') else v for v in (x, y)]", 'pass',
     'fixture 13-values'),
    ('align-unreadable', 'css_props.py', 'if not al and al is not None:', 'if not al:', 'fixture 13-values'),
    ('path-quoted', 'css_props.py', 'parts = [_quote_path(src)]', 'parts = [src]', 'fixture 13-values'),
    ('gradient-tiled', 'css_props.py', "if period.endswith('dp') and tiles:", 'if False:', 'fixture 13-values'),
    ('gradient-tiled-origin', 'css_props.py', 'if out[0][1] > 0:', 'if False:', 'fixture 13-values'),
    ('gradient-sized-report', 'css_props.py', "issues.append(Issue(f'{what} {name}() sized {size}'",
     "(lambda *a: None)(Issue(f'{what} {name}() sized {size}'", 'fixture 13-values'),
    ('lab-pass', 'css_values.py', '        return _cielab(t)', "        raise ValueIssue('lab')", 'unit lab'),
    ('lab-pass-gradient', 'css_values.py', "if re.match(r'^(ok)?(lab|lch)\\(', n):", 'if False:', 'fixture 13-values'),
    ('lch-hue-rad', 'css_values.py', "math.degrees(x[1]) if x[2] == 'rad' else x[1]", 'x[1]', 'unit lch hue'),
    ('hsl-hue-rad', 'css_values.py', 'hh = math.degrees(hh)', 'hh = hh', 'unit hsl hue'),
    ('hsl-half-up', 'css_values.py', 'int(math.floor(x + 0.5 + 1e-7))', 'int(round(x))', 'unit hsl half'),
    ('colour-name-unknown', 'css_props.py', "        if bad:\n            issues.append(Issue(f'{n}: {s}', f'RmlUi has no colour",
     "        if False:\n            issues.append(Issue(f'{n}: {s}', f'RmlUi has no colour", 'fixture 13-values'),
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
