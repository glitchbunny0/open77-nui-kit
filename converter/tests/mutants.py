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
    ('keyword-case', 'css_props.py', "if kws and any(t[0] == 'ident' and t[1] != t[1].lower() for t in toks):",
     'if False:', 'fixture 13-values'),
    ('back-tween', 'css_props.py', "'circular', 'back', 'linear')", "'circular', 'linear')", 'fixture 13-values'),
    ('exp-tween', 'css_props.py', 'math.exp(7.24 * (t - 1))', '2 ** (10 * (t - 1))', 'unit exponential'),
    ('border-zero', 'css_props.py', " or width in ('0', '0dp'):", ':', 'fixture 13-values'),
    ('string-quote', 'css_values.py', """re.sub(r'(?<!\\\\)"', r'\\\\"', t[1])""", 't[1]', 'fixture 13-values'),
    ('animation-count-0', 'css_props.py', "        if count == '0':\n            continue", "        if False:\n            continue",
     'fixture 13-values'),
    ('calc-spaces', 'css_values.py', '    _spaced(args)\n', '    pass\n', 'fixture 13-values'),
    ('calc-zero-number', 'css_values.py', 'if a[1] != b[1]:   # a unitless 0', 'if a[1] != b[1] and a[0] and b[0]:   #',
     'fixture 13-values'),
    ('block-parens', 'css_parse.py', '            elif parens:\n                pass', '            elif False:\n                pass',
     'fixture 13-values'),
    ('bad-string', 'css_parse.py', "while j < n and text[j] != c and text[j] != '\\n':", 'while j < n and text[j] != c:',
     'fixture 13-values'),
    ('path-semicolon', 'css_props.py', "        if re.search(r'[;{}]', src):", '        if False:', 'fixture 13-values'),
    # currentColor (L5-10, L7-3)
    ('currentcolor-rule', 'convert.py', "ctx.color = color if d.name != 'color' else None", 'ctx.color = None',
     'fixture 05-colours'),
    ('currentcolor-cascade', 'convert.py', 'color = color or self.cascade_color(matched)', 'color = color',
     'fixture 05-colours'),
    ('currentcolor-note', 'convert.py', "in d.value.lower():\n                self.cascade_color_note(file, d, color)",
     "in d.value.lower():\n                pass", 'fixture 05-colours'),
    # the rem root size (L5-9)
    ('rem-root', 'convert.py', 'self.units.root_px = self.casc.font_dp(self.top) * self.units.ppd',
     'self.units.root_px = 16.0', 'fixture 13-values'),
    ('rem-root-unread', 'cascade.py', "self.unread.append((el, v))   # a font size", "pass   # a font size",
     'fixture 12-no-body'),
    # the static cascade (L6-1..6, L6-14, L6-15, L7-2, L7-9) and the markup L6's surviving mutants missed
    ('spec-classes', 'selector.py', 'b = len(self.classes) + len(self.attrs)', 'b = len(self.attrs)', 'fixture 14-cascade'),
    ('inline-ignored', 'cascade.py', "if d.name == name and (d.important or not (inline and inline[1])):", 'if False:',
     'fixture 14-cascade'),
    ('tie-first-wins', 'cascade.py', 'rank = (name in imp, spec, order)', 'rank = (name in imp, spec, -order)',
     'fixture 14-cascade'),
    ('attr-quote-unescaped', 'convert.py', """.replace('"', '&quot;')""", '', 'fixture 14-cascade'),
    ('var-differs-report', 'convert.py', 'if len(vals) > 1 and key not in report_once and name not in quiet:', 'if False:',
     'fixture 14-cascade'),
    ('important-var-rank', 'cascade.py', 'rank = (name in imp, spec, order)', 'rank = (False, spec, order)',
     'fixture 14-cascade'),
    ('important-var-report', 'convert.py', "for d in it.decls:\n                if d.name.startswith('--') and d.important:",
     "for d in it.decls:\n                if False:", 'fixture 14-cascade'),
    ('var-at-declaring-element', 'cascade.py', "elif name.startswith('--') and 'var(' in v:", 'elif False:',
     'fixture 14-cascade'),
    ('assume-pseudos', 'cascade.py', "| {('pseudo', n, a) for n, a in c.pseudos if n != 'not'}", '| set()',
     'fixture 14-cascade'),
    ('assume-attrs', 'cascade.py', "{('attr',) + tuple(a) for a in c.attrs}", 'set()', 'fixture 14-cascade'),
    ('data-for-structural', 'selector.py', "or 'data-for' in el.attrs):", '):', 'fixture 14-cascade'),
    ('override-must-hold', 'convert.py', "if not hit:\n                                    break   # the override's",
     "if False:\n                                    break   # the override's", 'fixture 14-cascade'),
    ('virtual-subject', 'convert.py', "or self.virtual(sel) \\", "\\", 'fixture 14-cascade'),
    ('root-setters', 'convert.py', "if S.ser_sel(e[0]) in (':root', 'html', 'body'):", 'if False:', 'fixture 14-cascade'),
    ('restate-order', 'convert.py', 'and not self.later_sets(d.name, rank, els, S.specificity(nsel))]', ']',
     'fixture 14-cascade'),
    ('root-class', 'selector.py', "                c2.classes.append(ROOT_CLASS)\n                c2.tag = 'body' if c2.tag in ('html', 'body') else c2.tag",
     "                c2.tag = 'body'", 'fixture 14-cascade'),
    ('root-merge-report', 'convert.py', 'if other and other[0] != d.value.strip():', 'if False:', 'fixture 14-cascade'),
    ('hidden-class', 'selector.py', "HIDDEN_CLASS = 'html2rml-hidden'", "HIDDEN_CLASS = 'hidden'", 'fixture 14-cascade'),
    # @import variants, sheets a browser does not apply, root-relative/query hrefs (L6-7, L6-17, L6-20)
    ('import-late', 'convert.py', '        if late:\n', '        if False:\n', 'fixture 10-at-rules'),
    ('import-supports', 'convert.py', '        if sm:\n', '        if False:\n', 'fixture 10-at-rules'),
    ('import-media', 'convert.py', 'if rest and not self.media_ok(rest)[0]:', 'if False:', 'fixture 10-at-rules'),
    ('import-layer', 'convert.py', '        if lm:\n', '        if False:\n', 'fixture 10-at-rules'),
    ('href-query', 'convert.py', "u = href.strip().split('#')[0].split('?')[0]", 'u = href.strip()', 'fixture 10-at-rules'),
    ('sheet-disabled', 'convert.py', "if 'disabled' in el.attrs:", 'if False:', 'fixture 10-at-rules'),
    ('sheet-alternate', 'convert.py', "elif 'alternate' in rel:", 'elif False:', 'fixture 10-at-rules'),
    ('sheet-type', 'convert.py', "elif typ not in ('text/css', ''):", 'elif False:', 'fixture 10-at-rules'),
    ('sheet-template', 'convert.py', "skip = 'it is inside a <template>' if anc.tag == 'template' else None", 'skip = None',
     'fixture 10-at-rules'),
    # --vars native (the plan's ruling; L6-1, L6-3, L6-4, L7-4 natively)
    ('native-off', 'convert.py', "if self.vars == 'native' and not self.quiet:", 'if False:', 'fixture 15-native'),
    ('native-custom-lines', 'convert.py',
     "            clines = self.custom_lines([d for d in it.decls if d.name.startswith('--')], file) \\",
     "            clines = [] and self.custom_lines([d for d in it.decls if d.name.startswith('--')], file) \\",
     'fixture 15-native'),
    ('native-inline-custom', 'convert.py',
     "        clines = self.custom_lines([d for d in all_d if d.name.startswith('--')], self.page) \\",
     "        clines = [] and self.custom_lines([d for d in all_d if d.name.startswith('--')], self.page) \\",
     'fixture 15-native'),
    ('native-string-guard', 'convert.py', "if any(t[0] == 'str' for t in toks) and len(toks) > 1:", 'if False:',
     'fixture 15-native'),
    ('native-probe', 'convert.py', "raws.append(V.ser([('num', 12.3457, t[0][2])]))", 'pass', 'fixture 15-native'),
    ('native-template-check', 'convert.py', '                    if run({n: raw}) != tmpl:', '                    if False:',
     'fixture 15-native'),
    ('native-differs-quiet', 'convert.py', 'and key not in report_once and name not in quiet:', 'and key not in report_once:',
     'fixture 15-native'),
    ('native-folded-restated', 'convert.py', 'used = sorted(set(used) | self.last_folded)', 'used = sorted(set(used))',
     'fixture 15-native'),
    ('keyframes-custom-report', 'convert.py', "                if d.name.startswith('--'):\n                    self.report.add(self.where(file), d.line, 'css', f'{d.name} inside @keyframes'",
     "                if False:\n                    self.report.add(self.where(file), d.line, 'css', f'{d.name} inside @keyframes'",
     'fixture 15-native'),
    ('root-lone-body', 'selector.py', "if n == 'root' and len(sel) == 1 and not", "if False and len(sel) == 1 and not",
     'fixture 10-at-rules'),
    ('inline-important-report', 'convert.py', "        for d in all_d:\n            if d.name.startswith('--') and d.important:",
     "        for d in all_d:\n            if False:", 'fixture 14-cascade'),
    ('native-var-text', 'convert.py', "                except ValueIssue:\n                    txt = None", "                except KeyError:\n                    txt = None",
     'fixture 15-native'),
    # markup: implied end tags, <div/>, attributes, SVG, bindings with paths, selectors the markup can't match (L6-9..18)
    ('implied-end-tags', 'html_parse.py', "while len(self.stack) > 1 and self.stack[-1].tag in IMPLIED_END.get(tag, ()):",
     'while False:', 'fixture 01-markup'),
    ('div-slash', 'html_parse.py', 'if tag not in VOID and not any(e.tag in FOREIGN for e in self.stack) and tag not in FOREIGN:',
     'if False:', 'fixture 01-markup'),
    ('binding-src', 'convert.py', "if k == 'src' and tag == 'img' and '{{' in (v or ''):", 'if False:', 'fixture 01-markup'),
    ('binding-path', 'convert.py', "if re.match(r'^data-(attr-src|attr-href|style-[\\w-]+)$', k) and",
     "if False and re.match(r'^data-(attr-src|attr-href|style-[\\w-]+)$', k) and", 'fixture 01-markup'),
    ('size-attr-drop', 'convert.py', "if k in ('width', 'height') and tag not in ('img', 'input') + tuple(SIZE_ATTR_TAGS):",
     'if False:', 'fixture 14-cascade'),
    ('svg-extra', 'convert.py', 'if extra:   # gradients', 'if False:   # gradients', 'fixture 02-svg'),
    ('svg-path-attrs', 'convert.py', "self.report.add(where, p.line, 'markup', f'<path {k}>', 'dropped')", 'pass',
     'fixture 02-svg'),
    ('svg-url-paint', 'convert.py', "if v.lower().startswith('url('):", 'if False:', 'fixture 02-svg'),
    ('attr-lowercase', 'selector.py', 'name, op, val = m.group(1).lower(), m.group(2), m.group(3)',
     'name, op, val = m.group(1), m.group(2), m.group(3)', 'fixture 14-cascade'),
    ('attr-dropped-rule', 'convert.py', "                if n not in KEEP_ATTRS:\n                    raise",
     "                if False:\n                    raise", 'fixture 14-cascade'),
    ('type-attr-rule', 'convert.py', "if n == 'type' and op == '=' and (v or 'text') not in INPUT_TYPES:", 'if False:',
     'fixture 14-cascade'),
    ('size-attr-rule', 'convert.py', "if n in ('width', 'height') and c.tag not in ('img', 'input'):", 'if False:',
     'fixture 14-cascade'),
    ('data-for-last-child', 'convert.py', "if last and any('data-for' in el.attrs", "if False and any('data-for' in el.attrs",
     'fixture 14-cascade'),
    ('span-wrap-report', 'convert.py', "            if hits:\n                self.report.add(self.where(None), el.line, 'markup', f'bare text",
     "            if False:\n                self.report.add(self.where(None), el.line, 'markup', f'bare text",
     'fixture 14-cascade'),
    ('script-hex-literal', 'convert.py', "and len(s) < 60 and not re.fullmatch(r'#[0-9A-Fa-f]{3,8}', s))", 'and len(s) < 60)',
     'fixture 01-markup'),
    ('report-one-line', 'convert.py', "cell = lambda x: ' '.join(x.split()).replace('|', '/')",
     "cell = lambda x: x.replace('|', '/')", 'unit report'),
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
