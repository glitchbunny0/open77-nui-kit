"""html2rml: a WebUI page (HTML + CSS, RmlUi binding syntax kept) -> an RmlUi document + sheet + a report of
everything that could not be mapped. Python 3 stdlib only."""
import json, os, re
from . import css_parse, css_props as CP, css_values as V, html_parse as H, selector as S
from .cascade import Cascade, align
from .css_props import Issue
from .css_values import ValueIssue

BLOCK = ['address', 'article', 'aside', 'blockquote', 'dd', 'details', 'dialog', 'div', 'dl', 'dt', 'fieldset',
         'figcaption', 'figure', 'footer', 'form', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'header', 'hgroup', 'hr',
         'legend', 'li', 'main', 'menu', 'nav', 'ol', 'p', 'pre', 'section', 'summary', 'ul', 'caption']
INLINE_BLOCK = ['button', 'select', 'textarea', 'progress', 'path']
TABLE = {'table': 'table', 'tr': 'table-row', 'td': 'table-cell', 'th': 'table-cell', 'thead': 'table-row-group',
         'tbody': 'table-row-group', 'tfoot': 'table-row-group', 'col': 'table-column',
         'colgroup': 'table-column-group'}
# the parts of a browser's default stylesheet that change the look (RmlUi has no default stylesheet)
UA = {
    'body': 'margin: 8px; font-size: 16px; color: #000000',
    'p': 'margin: 1em 0', 'dl': 'margin: 1em 0', 'blockquote': 'margin: 1em 40px', 'figure': 'margin: 1em 40px',
    'ul': 'margin: 1em 0; padding-left: 40px', 'ol': 'margin: 1em 0; padding-left: 40px', 'dd': 'margin-left: 40px',
    'h1': 'font-size: 2em; margin: 0.67em 0; font-weight: bold', 'h2': 'font-size: 1.5em; margin: 0.83em 0; font-weight: bold',
    'h3': 'font-size: 1.17em; margin: 1em 0; font-weight: bold', 'h4': 'margin: 1.33em 0; font-weight: bold',
    'h5': 'font-size: 0.83em; margin: 1.67em 0; font-weight: bold', 'h6': 'font-size: 0.67em; margin: 2.33em 0; font-weight: bold',
    'b': 'font-weight: bold', 'strong': 'font-weight: bold', 'th': 'font-weight: bold; text-align: center',
    'i': 'font-style: italic', 'em': 'font-style: italic', 'cite': 'font-style: italic', 'small': 'font-size: 0.833em',
    'u': 'text-decoration: underline', 's': 'text-decoration: line-through', 'del': 'text-decoration: line-through',
    'ins': 'text-decoration: underline', 'pre': 'white-space: pre; margin: 1em 0',
    'sub': 'vertical-align: sub; font-size: 0.83em', 'sup': 'vertical-align: super; font-size: 0.83em',
    'mark': 'background-color: #FFFF00; color: #000000', 'hr': 'border-top: 1px #808080; margin: 0.5em 0',
}
KNOWN_TAGS = set(BLOCK) | set(INLINE_BLOCK) | set(TABLE) | set(UA) | {
    'span', 'a', 'img', 'input', 'label', 'option', 'optgroup', 'br', 'code', 'kbd', 'samp', 'var', 'abbr', 'time',
    'data', 'q', 'bdi', 'bdo', 'wbr', 'output', 'meter'} - {'path'}
REPLACE_WITH_DIV = {'canvas', 'video', 'audio', 'iframe', 'object', 'embed', 'picture', 'math', 'slot', 'portal'}
FORM_ATTRS = {'type', 'value', 'name', 'checked', 'disabled', 'selected', 'placeholder', 'maxlength', 'size', 'min',
              'max', 'step', 'for', 'rows', 'cols', 'readonly', 'multiple'}
KEEP_ATTRS = {'id', 'class', 'src', 'width', 'height'} | FORM_ATTRS
DOC_ONLY_ATTRS = {'lang', 'xmlns'}
INPUT_TYPES = {'text', 'password', 'radio', 'checkbox', 'range', 'submit', 'button'}
BINDING = re.compile(r'^data-(model|for|if|visible|value|checked|rml|alias-[\w-]+|class-[\w-]+|style-[\w-]+|'
                     r'attr-[\w-]+|event-[\w-]+|attrif-[\w-]+)$')
SIZE_ATTR_TAGS = {'canvas', 'video', 'iframe', 'object', 'embed', 'table', 'td', 'th', 'col', 'colgroup'}
SVG_SHAPES = {'path', 'rect', 'circle', 'ellipse', 'line', 'polyline', 'polygon', 'g', 'use', 'text', 'image',
              'foreignobject', 'symbol'}
SVG_PAINT = ('fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray',
             'stroke-dashoffset', 'opacity', 'fill-opacity', 'stroke-opacity')


# declarations that take the text colour when they name none (a colourless border or shadow)
COLOUR_FALLBACK = {'border', 'border-top', 'border-right', 'border-bottom', 'border-left', 'box-shadow', 'text-shadow',
                   'filter'}


class Report:
    def __init__(self):
        self.items = []

    def add(self, file, line, kind, what, todo):
        item = {'file': file, 'line': line, 'kind': kind, 'what': what, 'todo': todo}
        if item not in self.items:   # a rule converted once per selector reports once
            self.items.append(item)


def _esc_text(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;')


def _esc_attr(s):
    return s.replace('&', '&amp;').replace('<', '&lt;').replace('"', '&quot;')


class Converter:
    def __init__(self, page, out, name=None, css=(), canvas=(1920, 1080), px_per_dp=1.0, root=None, vars_mode='fold'):
        self.page = os.path.abspath(page)
        self.pdir = os.path.dirname(self.page)
        self.out = os.path.abspath(out)
        self.name = name or os.path.splitext(os.path.basename(page))[0]
        self.extra_css = [os.path.abspath(c) for c in css]
        self.canvas = canvas
        self.root = os.path.abspath(root) if root else None
        self.units = V.Units(px_per_dp, canvas)
        self.report = Report()
        self.fonts = []
        self.hidden_used = False
        self.root_class_used = False
        self.vars = vars_mode
        self.quiet = False
        self.last_folded = set()
        self.native_memo = {}
        self.svg_rules = []
        self.svg_n = 0

    # ---- paths
    def rel(self, path):
        try:
            return os.path.relpath(path, self.root or self.pdir)
        except ValueError:
            return path

    def where(self, file):
        return self.rel(file) if file else self.rel(self.page)

    def asset_path(self, url, base_dir, issues, file=None, line=None):
        u = url.strip()
        if u.startswith('data:'):
            issues.append(Issue('a data: URL image', 'save it as a PNG file in the resource and point at that'))
            return None
        if re.match(r'^[a-z]+://', u):
            issues.append(Issue(f'remote image {u}', 'NativeUI loads files of your resource only: copy it in'))
            return None
        u = u.split('#')[0].split('?')[0]
        if u.startswith('/'):
            absp = os.path.normpath(os.path.join(self.root or self.pdir, u.lstrip('/')))
        else:
            absp = os.path.normpath(os.path.join(base_dir, u))
        if not os.path.exists(absp):
            issues.append(Issue(f'image {u} not found (looked at {self.rel(absp)})', 'check the path'))
        if self.root:
            rel = os.path.relpath(absp, self.root).replace(os.sep, '/')
            if not rel.startswith('../'):
                return '/' + rel
            issues.append(Issue(f'image {u} is outside --root', 'written relative to the output folder; copy it into '
                                'the resource'))
        return os.path.relpath(absp, self.out).replace(os.sep, '/')

    # ---- sheets
    def local_path(self, href, base_dir):
        """a page-relative or root-relative (/web/x.css, with --root) reference, query and fragment dropped"""
        u = href.strip().split('#')[0].split('?')[0]
        if u.startswith('/'):
            return os.path.normpath(os.path.join(self.root or self.pdir, u.lstrip('/')))
        return os.path.normpath(os.path.join(base_dir, u))

    def load_sheets(self, doc):
        """(file, base line, text) in cascade order: <link>/<style> in document order, then --css; the sheets a
        browser does not apply (disabled, alternate, not CSS, inside <template>) are reported and left out"""
        out = []
        for el in doc.root.walk():
            if el.tag not in ('link', 'style'):
                continue
            rel = (el.attrs.get('rel') or '').lower().split()
            if el.tag == 'link' and 'stylesheet' not in rel:
                continue
            anc, skip = el.parent, None
            while isinstance(anc, H.Element) and skip is None:
                skip = 'it is inside a <template>' if anc.tag == 'template' else None
                anc = anc.parent
            typ = (el.attrs.get('type') or 'text/css').lower().split(';')[0].strip()
            if 'disabled' in el.attrs:
                skip = 'it is disabled'
            elif 'alternate' in rel:
                skip = 'it is an alternate stylesheet'
            elif typ not in ('text/css', ''):
                skip = f'its type is {typ}'
            if skip:
                self.report.add(self.where(None), el.line, 'markup', f'<{el.tag}> {el.attrs.get("href") or ""}'.strip(),
                                f'a browser does not apply it ({skip}): left out')
                continue
            if el.tag == 'link':
                href = el.attrs.get('href') or ''
                if re.match(r'^[a-z]+://', href):
                    self.report.add(self.where(None), el.line, 'markup', f'remote stylesheet {href}',
                                    'copy it next to the page and link it locally')
                    continue
                p = self.local_path(href, self.pdir)
                if not os.path.exists(p):
                    self.report.add(self.where(None), el.line, 'markup', f'stylesheet {href} not found', 'check the path')
                    continue
                media = el.attrs.get('media')
                out.append((p, 1, open(p, encoding='utf-8').read(), media))
            else:
                txt = ''.join(c.text for c in el.children if isinstance(c, H.Text))
                out.append((self.page, el.line, txt, el.attrs.get('media')))
        for p in self.extra_css:
            out.append((p, 1, open(p, encoding='utf-8').read(), None))
        return out

    def parse_sheet(self, txt, line0, file):
        bad = set()
        items = css_parse.parse(txt, line0, bad)
        for line in sorted(bad):
            self.report.add(self.where(file), line, 'css', 'a string without its closing quote (it ends at the end of the line)',
                            'close the string: a browser drops the declaration it is in')
        return items

    def flatten(self, items, file, depth=0):
        """@media/@import/@supports resolved -> [(file, item)] of Rule and @keyframes, @font-face collected"""
        out = []
        rules_seen = False   # an @import after other rules is ignored by the browser
        for it in items:
            if isinstance(it, css_parse.Rule):
                out.append((file, it))
                rules_seen = True
                continue
            n = it.name
            if n not in ('import', 'charset', 'layer') or (n == 'layer' and it.block):
                rules_seen = rules_seen or n not in ('import', 'charset')
            if n == 'media':
                ok, why = self.media_ok(it.prelude)
                if why:
                    self.report.add(self.where(file), it.line, 'css', f'@media {it.prelude}: {why}',
                                    'write the rules for the design canvas')
                if ok:
                    out += self.flatten(it.block, file, depth + 1)
                else:
                    self.report.add(self.where(file), it.line, 'css',
                                    f'@media {it.prelude} does not apply to the {self.canvas[0]}x{self.canvas[1]} canvas: '
                                    f'{len(it.block)} rules left out', 'nothing to do, or convert with --canvas')
            elif n == 'import':
                out += self.css_import(it, file, depth, rules_seen)
            elif n.endswith('keyframes'):
                out.append((file, it))
            elif n == 'font-face':
                self.font_face(it, file)
            elif n == 'charset':
                pass   # the converter reads and writes UTF-8
            elif n == 'layer':
                if it.block:
                    out += self.flatten(it.block, file, depth + 1)
                self.report.add(self.where(file), it.line, 'css', '@layer (cascade layers)',
                                'RmlUi has no layers: its rules are kept in source order; check overrides')
            else:
                self.report.add(self.where(file), it.line, 'css', f'@{n} {it.prelude}'.strip(),
                                {'supports': 'RmlUi has no @supports: write the rules that apply',
                                 'container': 'RmlUi has no container queries'}.get(n, f'RmlUi has no @{n}: dropped'))
        return out

    def css_import(self, it, file, depth, late):
        """@import url [layer[(name)]] [supports(...)] [media]: inlined when a browser would apply it"""
        where = self.where(file)
        if late:
            self.report.add(where, it.line, 'css', f'@import {it.prelude} after other rules',
                            'a browser ignores it (and so does this converter): move it to the top of the sheet')
            return []
        m = re.match(r'''^(?:url\(\s*)?(["']?)([^"')\s]+)\1\s*\)?\s*(.*)$''', it.prelude, re.S)
        if not m:
            self.report.add(where, it.line, 'css', f'@import {it.prelude} could not be read', 'copy its rules in')
            return []
        href, rest = m.group(2), m.group(3).strip()
        lm = re.match(r'^layer(\([^)]*\))?\s*', rest, re.I)
        if lm:
            rest = rest[lm.end():]
            self.report.add(where, it.line, 'css', f'@import {href} into a cascade layer',
                            'RmlUi has no layers: its rules are kept in source order; check overrides')
        sm = re.match(r'^supports\(', rest, re.I)
        if sm:
            depth_, k = 0, 0
            for k, ch in enumerate(rest):
                depth_ += {'(': 1, ')': -1}.get(ch, 0)
                if depth_ == 0 and ch == ')':
                    break
            cond, rest = rest[len('supports('):k], rest[k + 1:].strip()
            self.report.add(where, it.line, 'css', f'@import {href} supports({cond})', 'RmlUi has no @supports: '
                            'left out, as @supports blocks are; copy in the rules that apply')
            return []
        if rest and not self.media_ok(rest)[0]:
            self.report.add(where, it.line, 'css', f'@import {href} for media {rest}', 'not for the canvas: left out')
            return []
        p = self.local_path(href, os.path.dirname(file))
        if re.match(r'^[a-z]+://', href) or not os.path.exists(p) or depth >= 8:
            self.report.add(where, it.line, 'css', f'@import {it.prelude} could not be read', 'copy its rules in')
            return []
        return self.flatten(self.parse_sheet(open(p, encoding='utf-8').read(), 1, p), p, depth + 1)

    def media_ok(self, prelude):
        """evaluate a media query list for the canvas -> (applies, note about what could not be evaluated)"""
        w, h = self.canvas
        notes = []

        def length(v):
            m = re.match(r'^(-?[\d.]+)(px|em|rem)?$', v.strip())
            if not m:
                return None
            x = float(m.group(1))
            return x * 16 if m.group(2) in ('em', 'rem') else x

        def feature(f):
            f = f.strip()
            m = re.match(r'^([\w-]+)\s*(?::\s*(.+))?$', f)
            if m:
                name, val = m.group(1).lower(), (m.group(2) or '').strip()
                for pre, op in (('min-', '>='), ('max-', '<=')):
                    if name.startswith(pre):
                        return feature(f'{name[len(pre):]} {op} {val}')
                if not val:
                    return {'color': True, 'hover': True, 'pointer': True, 'any-hover': True, 'any-pointer': True,
                            'monochrome': False, 'grid': False, 'width': True, 'height': True}.get(name, None)
                return feature(f'{name} = {val}')
            m = re.match(r'^([\w-]+)\s*(<=|>=|<|>|=)\s*(.+)$', f)
            if not m:
                m2 = re.match(r'^(.+?)\s*(<=|>=|<|>|=)\s*([\w-]+)$', f)
                if m2:
                    flip = {'<': '>', '>': '<', '<=': '>=', '>=': '<=', '=': '='}
                    return feature(f'{m2.group(3)} {flip[m2.group(2)]} {m2.group(1)}')
                notes.append(f'({f}) not understood, taken as false')
                return None
            name, op, val = m.group(1).lower(), m.group(2), m.group(3).strip()
            if name in ('width', 'height', 'device-width', 'device-height'):
                x = length(val)
                if x is None:
                    notes.append(f'({f}) not understood, taken as false')
                    return None
                have = w if 'width' in name else h
            elif name in ('aspect-ratio', 'device-aspect-ratio'):
                a, _, b = val.partition('/')
                try:
                    x = float(a) / float(b or 1)
                except ValueError:
                    return None
                have = w / h
            elif name == 'orientation':
                return (val == 'landscape') == (w >= h)
            elif name in ('resolution', 'min-resolution', 'max-resolution'):
                have, x = 1.0, float(re.match(r'[\d.]+', val).group(0)) if re.match(r'[\d.]+', val) else 1.0
                if val.endswith('dpi'):
                    x /= 96
            elif name == 'prefers-reduced-motion':
                return val == 'no-preference'
            elif name == 'prefers-color-scheme':
                notes.append(f'({f}) taken as false (no colour scheme in the game)')
                return val == 'light' and False
            elif name in ('hover', 'any-hover'):
                return val == 'hover'
            elif name in ('pointer', 'any-pointer'):
                return val == 'fine'
            else:
                notes.append(f'({f}) not understood, taken as false')
                return None
            return {'<=': have <= x + 1e-9, '>=': have >= x - 1e-9, '<': have < x, '>': have > x,
                    '=': abs(have - x) < 1e-9}[op]

        any_ok = False
        for q in [x.strip() for x in prelude.split(',') if x.strip()]:
            neg = False
            ql = q
            m = re.match(r'^(not|only)\s+(.*)$', ql, re.I)
            if m:
                neg = m.group(1).lower() == 'not'
                ql = m.group(2)
            parts = re.split(r'\s+and\s+', ql, flags=re.I)
            ok = True
            for p in parts:
                p = p.strip()
                if p.startswith('('):
                    r = feature(p[1:-1])
                    ok = ok and bool(r)
                elif p.lower() in ('all', 'screen'):
                    pass
                elif p.lower() == 'print':
                    ok = False
                else:
                    notes.append(f'media type {p} taken as false')
                    ok = False
            if neg:
                ok = not ok
            any_ok = any_ok or ok
        return any_ok, '; '.join(notes)

    def font_face(self, it, file):
        d = {x.name: x.value for x in it.block}
        fam = d.get('font-family', '').strip().strip('"\'')
        weight = d.get('font-weight', '400')
        style = d.get('font-style', 'normal')
        srcs = re.findall(r'''url\(\s*["']?([^"')]+)["']?\s*\)(?:\s*format\(\s*["']?([\w-]+)["']?\s*\))?''',
                          d.get('src', ''))
        local = [(u, f) for u, f in srcs if not re.match(r'^[a-z]+:', u)]
        pick = next(((u, f) for u, f in local if u.lower().endswith(('.ttf', '.otf')) or f in ('truetype', 'opentype')),
                    local[0] if local else None)
        todo = []
        path = None
        if pick:
            absp = os.path.normpath(os.path.join(os.path.dirname(file), pick[0]))
            path = os.path.relpath(absp, self.root or self.pdir).replace(os.sep, '/')
            if not pick[0].lower().endswith(('.ttf', '.otf')):
                todo.append('convert it to TTF first (NativeUI loads TTF/OTF)')
            if not os.path.exists(absp):
                todo.append(f'(file not found: {self.rel(absp)})')
        if ' ' in weight.strip():
            todo.append(f'a variable font ({weight}): NativeUI loads its default instance; check the weights')
        call = f'Open77.ui.loadFont("{path or "<path>.ttf"}", "{fam.lower()}")'
        if path and not self.root:
            todo.append('the path is from the page\'s folder: write it from your resource\'s root (or convert with --root)')
        self.fonts.append({'family': fam.lower(), 'weight': weight, 'style': style, 'path': path, 'call': call})
        self.report.add(self.where(file), it.line, 'font', f'@font-face {fam} {weight}{" " + style if style != "normal" else ""}',
                        'in the client before creating the document: ' + call + ('; ' + '; '.join(todo) if todo else ''))

    # ---- the static cascade (custom properties, font sizes)
    def custom_props(self, rules, doc):
        self.casc = Cascade(rules, doc, self.units)
        self.top = H.find(doc.root, 'html') or H.find(doc.root, 'body') or doc.root
        self.global_vars = {}
        for e in self.casc.entries:
            for n in e[3]:
                if n.startswith('--') and n not in self.global_vars:
                    v = self.casc.inherited(self.top, n)
                    if v is not None:
                        self.global_vars[n] = v

    def lookup_for(self, els, file, line, report_once, quiet=()):
        """the var() lookup for declarations applying to these elements (under the current assumption); a value that
        differs between them is reported, except for the names in `quiet` (RmlUi resolves those itself)"""
        def look(name):
            vals = []
            for el in els:
                v = self.casc.inherited(el, name)
                if v is not None and v not in vals:
                    vals.append(v)
            if not els:
                v = self.global_vars.get(name)
                vals = [v] if v is not None else []
            key = (name, file, line)
            if len(vals) > 1 and key not in report_once and name not in quiet:
                report_once.add(key)
                self.report.add(self.where(file), line, 'css',
                                f'var({name}) differs between the elements this rule matches ({", ".join(vals)})',
                                f'used {vals[0]}; split the rule per element')
            return vals[0] if vals else None
        return look

    @staticmethod
    def _chain(el):
        out = []
        while isinstance(el, H.Element):
            out.append(el)
            el = el.parent
        return out

    def overrides_of(self, name, els):
        """rules setting custom property `name` that reach none of these elements (nor their ancestors)"""
        out = []
        for e in self.casc.by_name.get(name, ()):
            if S.ser_sel(e[0]) in (':root', 'html', 'body'):
                continue   # set on the document root: it reaches every element
            hit = False
            for el in els:
                n = el
                while isinstance(n, H.Element) and not hit:
                    hit = S.matches(e[0], n)
                    n = n.parent
                if hit:
                    break
            if not hit:
                out.append(e)
        return out

    def virtual(self, sel):
        """elements a rule targets that only a script builds (`.list b` with an empty .list): one stand-in per page
        element its ancestor part matches, so the cascade sees what they inherit there"""
        if len(sel) < 2 or sel[-1][0] not in (' ', '>'):
            return []
        anchors = [el for el in self.all_els if S.matches(sel[:-1], el, True)]
        c = sel[-1][1]
        out = []
        for a in anchors:
            attrs = [(n, v if v is not None else '') for n, op, v in c.attrs]
            if c.classes:
                attrs.append(('class', ' '.join(c.classes)))
            if c.id:
                attrs.append(('id', c.id))
            v = H.Element(c.tag if c.tag not in (None, '*') else 'div', attrs, a.line, a)
            v.virtual = True
            out.append(v)
        self._virtual += out   # kept alive: the cascade memo is keyed by id()
        return out

    def root_merge(self, flat):
        """html (or :root) and body are two boxes in a browser, one in RmlUi: a property both set lands twice on
        <body>, and the html value can win there"""
        seen = {}
        for file, it in flat:
            if not isinstance(it, css_parse.Rule) or not it.decls:
                continue
            for t in S.split_list(it.prelude):
                try:
                    sel = S.parse_one(t)
                except S.SelectorIssue:
                    continue
                c = sel[-1][1]
                if len(sel) != 1 or c.classes or c.id or c.attrs or [p for p in c.pseudos if p[0] != 'root']:
                    continue
                who = 'body' if c.tag == 'body' else 'html' if c.tag == 'html' or ('root', None) in c.pseudos else None
                for d in (it.decls if who else ()):
                    if d.name.startswith('--'):
                        continue
                    other = seen.get(('html' if who == 'body' else 'body', d.name))
                    if other and other[0] != d.value.strip():
                        self.report.add(self.where(file), d.line, 'css', f'{d.name} set on both html and body '
                                        f'({other[0]} at line {other[1]}, {d.value.strip()} here)',
                                        'RmlUi has one root element: both land on <body> and the later one wins there; '
                                        'a browser gives each box its own. Keep one')
                    seen[(who, d.name)] = (d.value.strip(), d.line)

    def check_markup_names(self, sel):
        """a selector naming an attribute the conversion drops or rewrites never matches in RmlUi"""
        for _, c in sel:
            for n, op, v in c.attrs:
                if n.startswith('data-') or n in ('id', 'class', 'style', 'hidden'):
                    continue
                if n in ('width', 'height') and c.tag not in ('img', 'input'):
                    raise S.SelectorIssue(f'[{n}]', 'the conversion writes width/height attributes as inline sizes '
                                          '(or drops them): the rule never matches; select a class instead')
                if n == 'type' and op == '=' and (v or 'text') not in INPUT_TYPES:
                    raise S.SelectorIssue(f'[type="{v}"]', 'RmlUi has no such input type: the input is written as '
                                          'text and the rule never matches; select a class instead')
                if n not in KEEP_ATTRS:
                    raise S.SelectorIssue(f'[{n}]', 'the conversion drops this attribute (RmlUi has no use for it): '
                                          'the rule never matches; select a class instead')

    def check_repeated(self, sel, text, file, line, all_els):
        """RmlUi keeps a data-for's template element after its copies: :last-child and its kind never match them"""
        c = sel[-1][1]
        last = [n for n, _ in c.pseudos if n in ('last-child', 'nth-last-child', 'last-of-type', 'nth-last-of-type',
                                                  'only-child', 'only-of-type')]
        if last and any('data-for' in el.attrs and S.matches(sel, el, 'relaxed') for el in all_els):
            self.report.add(self.where(file), line, 'selector', f'{text}: :{last[0]} on data-for rows',
                            'RmlUi keeps the data-for template after the rows: it never matches one (measured); give '
                            'the last row a class from the model (data-class-last="i == n - 1")')

    def rule_rank(self, sel, file, it):
        for e in self.casc.entries:
            if e[4] == file and e[5] == it.line and S.ser_sel(e[0]) == S.ser_sel(sel):
                return e[1], e[2]
        return None

    def later_sets(self, name, rank, els, nspec):
        """a rule after this one (by specificity, then order) sets `name` on all these elements, so it wins in every
        state, and a re-statement of specificity nspec would beat it in RmlUi: the re-statement must not be written"""
        return rank is not None and any((e[1], e[2]) > rank and e[1] < nspec
                                        and all(S.matches(e[0], x, 'relaxed') for x in els)
                                        for e in self.casc.by_name.get(name, ()))

    # ---- rules
    def convert_rules(self, flat, doc):
        body = H.find(doc.root, 'body') or doc.root
        all_els = list(body.walk())
        self.all_els, self._virtual, self.flat, self._setters = all_els, [], flat, None
        self.keyframe_names = {it.prelude.strip() for _, it in flat if isinstance(it, css_parse.AtRule)}
        # which elements other rules give a decorator, a mask or a background colour (a shorthand resets them in
        # CSS; the RCSS gets the reset only where it can matter), and the cascade of layer sizes/positions/repeats
        self.layer_src = []
        self.sets = {'decorator': set(), 'mask-image': set(), 'background-color': set()}
        order = 0
        for _, it in flat:
            if not isinstance(it, css_parse.Rule) or not it.decls:
                continue
            order += 1
            sels = []
            for t in S.split_list(it.prelude):
                try:
                    sels.append(S.parse_one(t))
                except S.SelectorIssue:
                    pass
            hits = {id(el) for el in all_els for sel in sels if S.matches(sel, el, 'relaxed')}
            fields = {'background': {}, 'mask': {}}
            for d in it.decls:
                n = d.name.replace('-webkit-', '')
                if n in ('background', 'background-image') and ('url(' in d.value or 'gradient' in d.value):
                    self.sets['decorator'] |= hits
                if n in ('mask', 'mask-image'):
                    self.sets['mask-image'] |= hits
                if n == 'background-color' or (n == 'background' and not re.match(r'^\s*(url\(|[\w-]*gradient\()', d.value)):
                    self.sets['background-color'] |= hits
                g = 'mask' if n.startswith('mask') else 'background' if n.startswith('background') else None
                if g is None:
                    continue
                try:
                    toks = V.strip_ws(V.convert_units(V.resolve_vars(V.tokenize(d.value),
                                                                     lambda k: self.global_vars.get(k)), self.units, []))
                except ValueIssue:
                    continue
                if n in ('background', 'mask'):
                    L = CP._layer(V.words(V.strip_ws(V.split(toks)[0])), [], n)
                    fields[g] = {'size': L['size'], 'pos': L['pos'], 'repeat': L['repeat'],
                                 'image': L['image'] not in (None, ('none',))}
                elif n in ('background-image', 'mask-image'):
                    fields[g]['image'] = 'none' not in d.value
                elif n.endswith(('-size', '-position', '-repeat')):
                    key = {'size': 'size', 'position': 'pos', 'repeat': 'repeat'}[n.rsplit('-', 1)[1]]
                    fields[g][key] = [V.ser([x]) if x[0] != 'num' else CP.len_str(x)
                                      for w in V.words(V.split(toks)[0]) for x in w]
            for g, f in fields.items():
                if f:
                    for sel in sels:
                        self.layer_src.append((sel, S.specificity(sel), order, g, f, it,
                                               {id(el) for el in all_els if S.matches(sel, el, True)}))
        self.root_merge(flat)
        svgs = [el for el in all_els if el.tag == 'svg']

        def svg_compound(c):
            return any(S.comp_match(c, el, True) for el in svgs)
        out = []
        once = set()
        self.rule_display = []   # (sel list, display) for the markup pass
        self.child_rules = []    # selectors a <span> wrapped around bare text can change (span, structural, + ~)
        for file, it in flat:
            if isinstance(it, css_parse.AtRule):
                out.append(self.keyframes(it, file, once))
                continue
            if it.decls is None:
                self.report.add(self.where(file), it.line, 'css', f'{it.prelude!r} without a block', 'fix the sheet')
                continue
            for d in it.decls:
                if d.name.startswith('--') and d.important:
                    self.report.add(self.where(file), d.line, 'css', f'{d.name}: {d.value} !important',
                                    'RmlUi has no !important: ' + (
                                        'written without it, so a more specific rule setting it wins there; raise this '
                                        'selector\'s specificity instead' if self.vars == 'native' else
                                        'the converter lets it win in its own cascade (as CSS does) but RmlUi will '
                                        'not; raise the selector\'s specificity instead'))
            decls = [d for d in it.decls if not d.name.startswith('--')]
            clines = self.custom_lines([d for d in it.decls if d.name.startswith('--')], file) \
                if self.vars == 'native' else []
            parsed = []
            for t in S.split_list(it.prelude):
                try:
                    sel = S.parse_one(t)
                    S.check(sel)
                    self.check_markup_names(sel)
                except S.SelectorIssue as e:
                    self.report.add(self.where(file), it.line, 'selector', f'{t}: {e.what}', e.todo)
                    continue
                self.check_repeated(sel, t, file, it.line, all_els)
                c_last = sel[-1][1]
                if c_last.tag == 'span' or any(n in S.STRUCTURAL and n != 'not' for n, _ in c_last.pseudos) \
                        or any(cb in ('+', '~') for cb, _ in sel):
                    self.child_rules.append((t, sel))
                parsed.append(sel)
            if not parsed or not (decls or clines):
                continue
            groups, expansions, pending, covered = {}, {}, {}, set()
            used = sorted({n for d in decls for n in V.var_names(V.tokenize(d.value))
                           if self.vars != 'native' or not self.native_ok(n)})
            for sel in parsed:
                els = [el for el in all_els if S.matches(sel, el)] or [el for el in all_els if S.matches(sel, el, True)] \
                    or [el for el in all_els if S.matches(sel, el, 'relaxed')] or self.virtual(sel) \
                    or [el for el in all_els if S.matches(sel, el, 'loose')]
                pairs = [p_ for el in els for p_ in (align(sel, el) or [])]
                with self.casc.assume(pairs):
                    # a custom property set by a rule reaching only some of these elements (.box.wide { --w })
                    # is handled like a state: the rule keeps the value of the others, the variant is re-stated
                    base = els
                    for n in used:
                        reached = lambda e, o: any(S.matches(o[0], a) for a in self._chain(e))
                        part = [o for o in self.casc.by_name.get(n, ()) if 0 < sum(reached(e, o) for e in els) < len(els)]
                        base = [e for e in base if not any(reached(e, o) for o in part)] or base
                    lines = self.map_decls(decls, file, base, None, once, it.prelude, rule=it) if decls else []
                    used = sorted(set(used) | self.last_folded)   # the variables that ended up folded
                    ovs = {n: self.overrides_of(n, base) for n in used}
                lines = clines + lines
                rws = S.rewrite(sel, svg_compound)
                key = tuple(lines)
                if key not in groups:
                    groups[key] = []
                if S.ser_sel(rws) not in [S.ser_sel(x) for x in groups[key]]:
                    groups[key].append(rws)
                # a custom property a state rule overrides (#mark.kill { --len: 14px }): the declarations using it
                # are re-stated under that state (#mark.kill i { width: 14dp }), as a hand port would
                for n, ov in ovs.items():
                    unhandled = []
                    for o in ov:
                        done = False
                        if len(o[0]) == 1:
                            oc = o[0][0][1]
                            for el, c in pairs:
                                if not S.comp_match(oc, el, 'loose') or (set(oc.classes) <= set(c.classes)
                                                                         and not oc.attrs and not oc.pseudos):
                                    continue
                                if not ((oc.id and oc.id == c.id) or set(oc.classes) & set(c.classes)):
                                    continue   # only a state of the same element (#mark -> #mark.kill)
                                if set(c.classes) - set(el.classes(True)) - set(getattr(el, 'extra', ())) \
                                        or not S.comp_match(c, el, True):
                                    break   # restate from the page's own state only, not from another state rule
                                merged = S.Compound()
                                merged.tag, merged.id = c.tag or oc.tag, c.id or oc.id
                                merged.classes = c.classes + [x for x in oc.classes if x not in c.classes]
                                merged.attrs = c.attrs + [x for x in oc.attrs if x not in c.attrs]
                                merged.pseudos = c.pseudos + [x for x in oc.pseudos if x not in c.pseudos]
                                nsel = [(cb, merged if cc is c else cc) for cb, cc in sel]
                                npairs = [(e2, merged if c2 is c else c2) for e2, c2 in pairs]
                                setp = {k for k in o[3] if k.startswith('--') and k in used}
                                rank = self.rule_rank(sel, file, it)
                                sub = [d for d in decls if set(V.var_names(V.tokenize(d.value))) & setp
                                       and not self.later_sets(d.name, rank, els, S.specificity(nsel))]
                                if not sub:
                                    done = True   # a later rule sets those properties in every state anyway
                                    break
                                with self.casc.assume(npairs):
                                    nlines = self.map_decls(sub, file, els, None, once, it.prelude, rule=it)
                                    hit = any(S.matches(o[0], e2) for e2, c2 in npairs if c2 is merged)
                                if not hit:
                                    break   # the override's condition could not be assumed: reported below
                                base = [x for x in lines if x[0] in {k for k, _ in nlines}]
                                if nlines and nlines != base:
                                    k2 = S.ser_sel(S.rewrite(nsel, svg_compound))
                                    prev = expansions.setdefault(k2, [])
                                    for x in nlines:
                                        if x not in prev:
                                            prev.append(x)
                                done = True
                                break
                        if not done:
                            unhandled.append(o)
                    for o in unhandled:
                        pending.setdefault(n, {})[id(o)] = o
                    for o in self.casc.by_name.get(n, ()):
                        if o not in ov:
                            covered.add((n, id(o)))   # this selector's own state already gets that value
            for n, os_ in pending.items():
                left = [o for k, o in os_.items() if (n, k) not in covered]
                if left:
                    under = ', '.join(sorted({S.ser_sel(o[0]) for o in left}))
                    self.report.add(self.where(file), it.line, 'css', f'var({n}) is also set under {under}, '
                                    'which this converter cannot re-state for this rule',
                                    'RmlUi has no custom properties: the value for the page as written is used; '
                                    're-state the affected declarations under those selectors')
            for lines, sels in groups.items():
                if not lines:
                    continue
                if any(S.ROOT_CLASS in c.classes for x in sels for _, c in x):
                    self.root_class_used = True
                disp = [v for k, v in lines if k == 'display']
                if disp:
                    for sel in sels:
                        self.rule_display.append((sel, disp[-1]))
                out.append((', '.join(S.ser_sel(x) for x in sels), list(lines)))
            for k2, nlines in expansions.items():
                self.root_class_used = self.root_class_used or S.ROOT_CLASS in k2
                out.append((k2, nlines))
        return out

    # ---- --vars native: custom properties and var() kept for RmlUi 6.3 to resolve
    MATH_OR_COLOUR = set(V.MATH_FUNCS) | {'rgb', 'rgba', 'hsl', 'hsla', 'lab', 'lch', 'oklab', 'oklch', 'hwb', 'color',
                                          'color-mix'}

    def _var_inside(self, toks, inside=False):
        """a var() inside calc()/min()/... or a colour function: RmlUi has no calc() and reads rgba() alpha as 0-255,
        so such a value can't be left to it"""
        for t in toks:
            if t[0] == 'func' and t[1] == 'var' and inside:
                return True
            if t[0] in ('func', 'paren') and self._var_inside(t[-1], inside or (t[0] == 'func' and
                                                                                 t[1] in self.MATH_OR_COLOUR)):
                return True
        return False

    def custom_value(self, raw, file):
        """a custom property's value as RmlUi gets it: px -> dp, colours as hex, calc() folded, url() as the image path
        (from the declaring sheet); var() kept. Raises ValueIssue when RmlUi could not use it"""
        toks = V.tokenize(raw.strip())
        if not V.strip_ws(toks) or self._var_inside(toks):
            raise ValueIssue('value RmlUi cannot take', '')
        iss = []
        toks = [('ident', CP._quote_path(self.asset_path(t[1], os.path.dirname(file), iss) or '')) if t[0] == 'url'
                else t for t in toks]
        if any(t == ('ident', '') for t in toks):
            raise ValueIssue('an image RmlUi cannot load', '')
        notes = []
        toks = V.convert_units(toks, self.units, notes)
        if notes:
            raise ValueIssue('unit ' + notes[0], '')
        toks = V.strip_ws(V.convert_colors(V.fold_math(toks)))
        if any(t[0] == 'str' for t in toks) and len(toks) > 1:
            raise ValueIssue('a quoted string next to other values', '')   # RmlUi's parser refuses it (measured)
        return V.ser(toks)

    def setters(self, name):
        """every value the page gives custom property `name`: (raw value, file it is declared in), from every rule
        of the sheets and every inline style"""
        if self._setters is None:
            self._setters = {}
            for file, it in self.flat:
                for d in (it.decls or ()) if isinstance(it, css_parse.Rule) else ():
                    if d.name.startswith('--'):
                        self._setters.setdefault(d.name, []).append((d.value, file))
            for el in self.all_els:
                if '--' in (el.attrs.get('style') or ''):
                    for d in css_parse.parse_decls(el.attrs['style'], el.line):
                        if d.name.startswith('--'):
                            self._setters.setdefault(d.name, []).append((d.value, self.page))
        return self._setters.get(name, [])

    def native_ok(self, name, stack=()):
        """RmlUi can resolve var(name) itself: every value the page gives it converts, and so does every variable those
        values use (all or nothing: a setter left out would hand RmlUi another setter's value)"""
        if name in self.native_memo:
            return self.native_memo[name]
        if name in stack:
            return False
        ok = bool(self.setters(name))
        for raw, f in self.setters(name):
            try:
                self.custom_value(raw, f)
            except ValueIssue:
                ok = False
                break
            if not all(self.native_ok(n, stack + (name,)) for n in V.var_names(V.tokenize(raw))):
                ok = False
                break
        self.native_memo[name] = ok
        return ok

    def custom_lines(self, decls, file):
        """a rule's (or an inline style's) custom properties, written for RmlUi (--vars native)"""
        out = []
        for d in decls:
            if self.native_ok(d.name):
                try:
                    out = [x for x in out if x[0] != d.name] + [(d.name, self.custom_value(d.value, file))]
                except ValueIssue:   # native_ok saw every setter: only a path seen from another file can get here
                    pass
        return out

    def native_lines(self, decls, file, matched, sheet, once, prelude, inline, rule):
        """--vars native: the lines with var() kept wherever RmlUi computes the same value as the static folding does.
        Checked by mapping the declarations once per value each variable takes on the page: a line must carry each
        value exactly where the variable is, so writing var() there hands RmlUi the very value the folding would write.
        A variable that fails (calc() around it, a mapping that rewrites it: border-radius %, font lists, shadows
        reordered, a missing value) is folded instead. None when nothing is left to RmlUi."""
        names = {n for d in decls for n in V.var_names(V.tokenize(d.value))}
        if not names:
            return None
        clean = set()
        for n in names:
            users = [d for d in decls if n in V.var_names(V.tokenize(d.value))]
            if self.native_ok(n) and not any(self._var_inside(V.tokenize(d.value)) for d in users):
                clean.add(n)
        clean = {n for n in clean if all(set(V.var_names(V.tokenize(d.value))) <= clean
                                         for d in decls if n in V.var_names(V.tokenize(d.value)))}
        base = self.lookup_for(matched, file, decls[0].line, set(), quiet=names)
        texts = {}
        for d in decls:   # var(--x, fallback) as RmlUi gets it
            for t in self._var_funcs(V.tokenize(d.value)):
                try:
                    txt = V.ser(V.convert_colors(V.convert_units([t], self.units, [])))
                except ValueIssue:
                    txt = None
                texts.setdefault(V.ser(V.split(t[2])[0]).strip(), set()).add(txt)
        bad = {n for n in clean if len(texts.get(n, ())) != 1 or None in texts[n]}
        tmpl = None
        while clean - bad:
            good = clean - bad
            before = set(bad)

            def run(sg):
                look = lambda n: sg[n] if n in sg else base(n)
                out = self.quiet_map(decls, file, matched, sheet, prelude, inline, rule, look)
                return self._template(out, {n: self._resolved(n, look, decls) for n in good},
                                      {n: next(iter(texts[n])) for n in good}, bad)
            tmpl = run({})
            for n in sorted(good):
                if n in bad:
                    continue
                for raw in self.probes(n):
                    if run({n: raw}) != tmpl:
                        bad.add(n)
                        break
            if bad == before:
                break
        clean -= bad
        if not clean:
            return None
        look = self.lookup_for(matched, file, decls[0].line, once, quiet=clean)
        self._map_decls(decls, file, matched, sheet, once, prelude, inline, rule, look)   # its report items
        self.last_folded = names - clean
        return tmpl

    def probes(self, n):
        """values to map var(n) with: each one the page gives it, and a made-up one of the same kind (a number, a
        colour) that can't coincide with another value of the line"""
        raws = sorted({r for r, _ in self.setters(n)})
        t = V.strip_ws(V.tokenize(raws[0])) if raws else []
        if len(t) == 1 and t[0][0] == 'num':
            raws.append(V.ser([('num', 12.3457, t[0][2])]))
        elif len(t) == 1 and V.is_color(t[0]):
            raws.append('#123457')
        return raws

    @staticmethod
    def _var_funcs(toks):
        for t in toks:
            if t[0] == 'func' and t[1] == 'var':
                yield t
            elif t[0] in ('func', 'paren'):
                yield from Converter._var_funcs(t[-1])

    def _resolved(self, n, look, decls):
        """the text RmlUi substitutes for var(n) under this lookup (its fallback when no value reaches)"""
        raw = look(n)
        if raw is None:
            for t in self._var_funcs(V.tokenize(' '.join(d.value for d in decls))):
                parts = V.split(t[2])
                if V.ser(parts[0]).strip() == n and len(parts) > 1:
                    raw = V.ser(t[2][[i for i, a in enumerate(t[2]) if a[0] == 'comma'][0] + 1:])
                    break
        if raw is None:
            return None
        try:
            return self.custom_value(V.ser(V.resolve_vars(V.tokenize(raw), look)), self.page)
        except ValueIssue:
            return None

    @staticmethod
    def _template(lines, values, texts, bad):
        """lines with each variable's value put back as its var() text; a variable whose value is missing or is not
        found exactly once per use goes into `bad`"""
        out = []
        counts = {n: 0 for n in values}
        for k, v in lines:
            for n, val in values.items():
                if not val:
                    bad.add(n)
                    continue
                pat = r'(?<![\w#.%-])' + re.escape(val) + r'(?![\w%.-])'
                counts[n] += len(re.findall(pat, v))
                v = re.sub(pat, lambda m, t=texts[n]: t, v)
            out.append((k, v))
        for n, c in counts.items():
            if c == 0:
                bad.add(n)
        if len({v for v in values.values() if v}) < len([v for v in values.values() if v]):
            bad |= set(values)   # two variables with one value: whose is whose can't be told
        return out

    def quiet_map(self, decls, file, matched, sheet, prelude, inline, rule, look):
        saved, self.report, self.quiet = self.report, Report(), True
        try:
            return self._map_decls(decls, file, matched, sheet, set(), prelude, inline, rule, look)
        finally:
            self.report, self.quiet = saved, False

    def cascade_color(self, matched):
        """the text colour these elements get from the page's static cascade (body's default black when nothing sets
        it), or None when they differ or it can't be read"""
        vals = set()
        for el in matched:
            raw = self.casc.inherited(el, 'color')
            if raw is None:
                vals.add('#000000')
                continue
            try:
                c = V.ser(CP.prepare('color', raw, CP.Ctx(self.units, lambda n, e=el: self.casc.inherited(e, n), None),
                                     []))
            except ValueIssue:
                return None
            vals.add(c)
        if len(vals) == 1:
            c = vals.pop()
            return c if c.startswith('#') else None
        return None

    def cascade_color_note(self, file, d, color):
        self.report.add(self.where(file), d.line, 'css', f'{d.name}: {" ".join(d.value.split())} uses the text colour',
                        f'RmlUi has no currentColor: written as {color}, the colour these elements get on the page as '
                        'written (a state that changes their color does not change this)')

    def map_decls(self, decls, file, matched, sheet, once, prelude, inline=False, rule=None):
        """the declarations -> RCSS lines. With --vars native, a declaration whose var()s RmlUi can resolve itself
        keeps them (native_lines); the others are folded from the static cascade"""
        self.last_folded = set()
        if self.vars == 'native' and not self.quiet:
            got = self.native_lines(decls, file, matched, sheet, once, prelude, inline, rule)
            if got is not None:
                return got
        self.last_folded = {n for d in decls for n in V.var_names(V.tokenize(d.value))}
        return self._map_decls(decls, file, matched, sheet, once, prelude, inline, rule)

    def _map_decls(self, decls, file, matched, sheet, once, prelude, inline=False, rule=None, look=None):
        look = look or self.lookup_for(matched, file, decls[0].line, once)
        issues_at = []
        prepared = {}
        # the rule's own colour first: currentColor in its other declarations and colourless borders/shadows take it;
        # without one, the colour these elements get from the page's cascade (reported where it is used)
        color, color_from = None, None
        for d in sorted(decls, key=lambda d: d.name != 'color'):
            if d.name != 'color' and color_from is None:
                color_from = 'rule' if color else 'cascade'
                if not color and any('currentcolor' in x.value.lower() or x.name in COLOUR_FALLBACK for x in decls):
                    color = self.cascade_color(matched)   # only where something needs it (it walks the cascade)
            if not d.name:
                self.report.add(self.where(file), d.line, 'css', f'declaration {d.value!r} has no property name',
                                'fix the sheet')
                continue
            if d.important:
                self.report.add(self.where(file), d.line, 'css', f'{d.name}: {d.value} !important',
                                'RmlUi has no !important: kept without it; raise the selector\'s specificity if it '
                                'must win')
            ctx = CP.Ctx(self.units, look, None, where=prelude)
            ctx.color = color if d.name != 'color' else None
            try:
                d.toks = CP.prepare(d.name, d.value, ctx, issues_at)
            except ValueIssue as e:
                todo = e.todo
                sv = [n for n in V.var_names(V.tokenize(d.value)) if n in self.script_vars]
                if sv and 'no value' in e.what:
                    todo = (f'{", ".join(sv)} is set by a script at run time: the client sets the resulting {d.name} '
                            'itself (ui:style), or a class per state does')
                self.report.add(self.where(file), d.line, 'css', f'{d.name}: {" ".join(d.value.split())}: {e.what}', todo)
                continue
            if d.name == 'color':
                c = V.ser(d.toks)
                if c.startswith('#') or c == 'transparent':
                    color = c
            elif color_from == 'cascade' and color and 'currentcolor' in d.value.lower():
                self.cascade_color_note(file, d, color)
            prepared[id(d)] = d
        prepared = [d for d in decls if id(d) in prepared]
        names = {d.name: V.ser(d.toks) for d in prepared}
        grid_centre = False
        if names.get('display') in ('grid', 'inline-grid'):
            place = names.get('place-items') or ' '.join(x for x in (names.get('align-items'), names.get('justify-items'))
                                                         if x)
            single = all(sum(1 for c in el.children if isinstance(c, H.Element) or
                             (isinstance(c, H.Text) and c.text.strip())) <= 1 for el in matched)
            template = any(n.startswith('grid-template') or n.startswith('grid-auto') for n in names)
            grid_centre = bool(place.split()) and set(place.split()) == {'center'} and single and not template
            if grid_centre:
                prepared = [d for d in prepared if d.name not in ('place-items', 'justify-items', 'align-items')]
        out = []
        rule_decls = {}
        groups = {'background': [], 'mask': []}
        group_at = {}
        for d in prepared:
            ctx = CP.Ctx(self.units, look, None, rule_decls, self.keyframe_names, prelude)
            ctx.color = color
            ctx.asset = lambda u, iss, f=file: self.asset_path(u, os.path.dirname(f), iss)
            issues = []
            if d.name in CP.LAYER_PROPS:
                groups['background'].append(d)
                group_at.setdefault('background', (len(out), d.line))
                continue
            if d.name in CP.MASK_PROPS:
                groups['mask'].append(d)
                group_at.setdefault('mask', (len(out), d.line))
                continue
            got = CP.map_decl(d, ctx, issues)
            if ctx.used_color and color_from == 'cascade':
                self.cascade_color_note(file, d, color)
            for iss in issues:
                self.report.add(self.where(file), d.line, iss.kind, iss.what, iss.todo)
            for k, v in got:
                rule_decls[k] = v
            out += got
        for g in ('mask', 'background'):
            if not groups[g]:
                continue
            ctx = CP.Ctx(self.units, look, None, rule_decls, self.keyframe_names, prelude)
            ctx.color = color
            ctx.asset = lambda u, iss, f=file: self.asset_path(u, os.path.dirname(f), iss)
            issues = []
            dyn = {id(e) for e in matched}
            flags = {k: bool(v & dyn) if v is not True else True for k, v in self.sets.items()} if sheet is None else sheet
            got = CP.map_layers(g, groups[g], ctx, issues, flags, self.layer_defaults(g, matched, rule))
            at, line = group_at[g]
            for iss in issues:
                self.report.add(self.where(file), line, iss.kind, iss.what, iss.todo)
            out[at:at] = got
            if g == 'mask' and any(d.name.startswith('-webkit-') for d in groups[g]):
                pass   # -webkit-mask* is the mask: mapped, not dropped
        # display: grid -> a centring flex box when that is all it does (place-items: center, one child), else reported
        for i, (k, v) in enumerate(out):
            if v in ('__grid__', '__inline-grid__'):
                line = next((d.line for d in prepared if d.name == 'display'), decls[0].line)
                if grid_centre:
                    out[i:i + 1] = [('display', 'flex' if v == '__grid__' else 'inline-flex'), ('flex-direction', 'row'),
                                    ('justify-content', 'center'), ('align-items', 'center')]
                else:
                    out[i] = None
                    self.report.add(self.where(file), line, 'css', 'display: grid',
                                    'RmlUi has no grid: use flex rows/columns with widths (only a single centred child '
                                    '- place-items: center - is converted)')
                break
        out = [x for x in out if x is not None]
        # letter-spacing and line-height in em/%: CSS computes them once, on the element that declares them; RmlUi
        # resolves em again on every descendant with another font size (measured). Written in dp where the size is known.
        for i, (k, v) in enumerate(out):
            m = re.fullmatch(r'(-?[\d.]+)(em|%)', v) if k in ('letter-spacing', 'line-height') else None
            if not m:
                continue
            fs = [float(x[:-2]) for kk, x in out if kk == 'font-size' and x.endswith('dp')]
            sizes = fs[-1:] or sorted({round(self.casc.font_dp(el), 4) for el in matched})
            if len(sizes) == 1:
                n = float(m.group(1)) * (sizes[0] if m.group(2) == 'em' else sizes[0] / 100)
                out[i] = (k, V.fmt(n) + 'dp')
            elif len(sizes) > 1:
                self.report.add(self.where(file), decls[0].line, 'css', f'{k}: {v} on elements of different font sizes',
                                'RmlUi resolves em on every descendant: write it in dp per element')
        # duplicates: the last wins in CSS too
        seen = {}
        for k, v in out:
            seen[k] = v
        dedup = []
        for k, v in out:
            if seen.get(k) == v and (k, v) not in dedup:
                dedup.append((k, v))
        return dedup

    def layer_defaults(self, group, matched, rule):
        """size/position/repeat this rule's image gets from OTHER rules matching its elements: CSS combines them
        across rules, RmlUi's decorator takes them in one value. A field the rule sets itself is kept unless a
        higher-priority rule sets just that field; a field it does not set comes from the best rule that does."""
        own = [e for e in self.layer_src if e[5] is rule and e[3] == group]
        prio = max(((e[1], e[2]) for e in own), default=((-1, -1, -1), -1))
        own_fields = set(k for e in own for k in e[4] if k != 'image')
        best, has_image = {}, any(e[4].get('image') for e in own)
        ids = {id(el) for el in matched}
        for sel, spec, order, g, f, it, hits in self.layer_src:   # hits: the elements it matches (as data-class-* allow)
            if g != group or it is rule or not (hits & ids or any(getattr(el, 'virtual', False) and
                                                                     S.matches(sel, el, True) for el in matched)):
                continue
            has_image = has_image or bool(f.get('image'))
            for k in ('size', 'pos', 'repeat'):
                if k not in f:
                    continue
                if 'image' in f and k in own_fields:
                    continue
                if 'image' not in f and k in own_fields and (spec, order) <= prio:
                    continue
                if k not in best or (spec, order) >= best[k][0]:
                    best[k] = ((spec, order), f[k])
        out = {k: v for k, (_, v) in best.items()}
        out['_image'] = has_image
        return out

    def keyframes(self, it, file, once):
        frames = []
        for fr in it.block:
            if not isinstance(fr, css_parse.Rule) or fr.decls is None:
                continue
            for d in fr.decls:
                for n in V.var_names(V.tokenize(d.value)):
                    if n not in self.global_vars and n in self.casc.by_name:
                        under = ', '.join(sorted({S.ser_sel(e[0]) for e in self.casc.by_name[n]}))
                        self.report.add(self.where(file), d.line, 'css', f'var({n}) inside @keyframes is set per element '
                                        f'(under {under})', 'keyframes are shared in RmlUi: write one @keyframes per variant')
            sels = [s.strip() for s in fr.prelude.split(',')]
            for d in fr.decls:
                if d.name.startswith('--'):
                    self.report.add(self.where(file), d.line, 'css', f'{d.name} inside @keyframes',
                                    'RmlUi cannot animate custom properties: dropped; animate the property itself')
            decls = [d for d in fr.decls if not d.name.startswith('--')]
            vm, self.vars = self.vars, 'fold'   # a keyframe's values are folded: RmlUi animates the computed ones
            lines = self.map_decls(decls, file, [], {'decorator': False, 'mask-image': False, 'background-color': False}, once, fr.prelude) if decls else []
            self.vars = vm
            if lines:
                frames.append((', '.join(sels), lines))
        name = it.prelude.strip()
        if it.name != 'keyframes':
            self.report.add(self.where(file), it.line, 'css', f'@{it.name}', 'vendor prefix: written as @keyframes')
        return ('@keyframes ' + name, frames)

    # ---- markup
    def display_of(self, el):
        """'flex' when any rule of the converted sheet (any state) or the inline style makes this element a flex box:
        its bare text then goes into a <span> (RmlUi lays out a bare text node in a flex box unpredictably)"""
        st = el.attrs.get('style') or ''
        m = re.search(r'display\s*:\s*([\w-]+)', st)
        if m and m.group(1) in ('flex', 'inline-flex'):
            return 'flex'
        for sel, disp in self.rule_display:
            if disp in ('flex', 'inline-flex') and S.matches(sel, el, 'relaxed'):
                return 'flex'
        return None

    def emit_children(self, el, out, depth, flexy):
        if flexy and any(isinstance(c, H.Text) and c.text.strip() for c in el.children):
            probe = H.Element('span', [], el.line, el)
            probe.virtual = True
            hits = [t for t, sel in self.child_rules if S.matches(sel, probe, 'relaxed')
                    or any(S.matches(sel, k, 'relaxed') for k in el.elements())]
            if hits:
                self.report.add(self.where(None), el.line, 'markup', f'bare text in the flex box <{el.tag}> is wrapped '
                                f'in <span>s, and {", ".join(hits[:4])} select its children',
                                'the new spans count as children: :first-child, :nth-*, + and ~ and span rules can '
                                'match differently; wrap the text in the page yourself')
        for c in el.children:
            if isinstance(c, H.Text):
                txt = c.text
                if flexy and txt.strip():
                    lead = txt[:len(txt) - len(txt.lstrip())]
                    trail = txt[len(txt.rstrip()):]
                    out.append(_esc_text(lead) + '<span>' + _esc_text(txt.strip()) + '</span>' + _esc_text(trail))
                else:
                    out.append(_esc_text(txt))
            elif isinstance(c, H.Comment):
                out.append('<!--' + c.text.replace('--', '- -') + '-->')
            else:
                self.emit(c, out, depth + 1)

    def emit(self, el, out, depth):
        tag = el.tag
        where = self.where(None)
        if tag in ('script', 'style', 'link', 'meta', 'title', 'base', 'noscript', 'template'):
            if tag == 'script':
                self.script(el)
            elif tag == 'noscript':
                self.report.add(where, el.line, 'markup', '<noscript>', 'dropped')
            elif tag == 'template':
                self.report.add(where, el.line, 'markup', '<template>', 'RmlUi has no templates: use data-for')
            elif tag == 'base':
                self.report.add(where, el.line, 'markup', '<base>', 'dropped: paths are resolved from the page')
            return
        if tag == 'svg':
            return self.svg(el, out)
        attrs = {}
        size_style = []
        classes = el.classes()
        for k, v in el.attrs.items():
            if k == 'class':
                continue
            if k == 'hidden':
                classes.append(S.HIDDEN_CLASS)
                self.hidden_used = True
                continue
            if k == 'style':
                st = self.inline_style(el, v or '')
                if st:
                    attrs['style'] = st
                continue
            if k.startswith('data-'):
                attrs[k] = v if v is not None else ''
                if re.match(r'^data-(attr-src|attr-href|style-[\w-]+)$', k) and re.search(r'''['"][^'"]*(/|\.(png|jpe?g|svg|webp|gif|tga))[^'"]*['"]''', v or ''):
                    self.report.add(where, el.line, 'markup', f'<{tag} {k}="{v}">', 'a path inside a binding is '
                                    'written as is: RmlUi resolves it from the document (--out), not from the page')
                continue
            if k.startswith('on'):
                self.report.add(where, el.line, 'markup', f'<{tag} {k}="{(v or "")[:60]}">',
                                'inline handler dropped: use data-event-%s="..." and answer it in the client' % k[2:])
                continue
            if k == 'src' and tag == 'img' and '{{' in (v or ''):
                attrs['src'] = v
                self.report.add(where, el.line, 'markup', f'<img src="{v}">', 'a binding: kept as is; the path it gives '
                                'is resolved from the document (--out), not from the page')
                continue
            if k == 'src' and tag == 'img':
                iss = []
                p = self.asset_path(v or '', self.pdir, iss)
                for i in iss:
                    self.report.add(where, el.line, 'markup', i.what, i.todo)
                if p:
                    attrs['src'] = p
                continue
            if k == 'type' and tag == 'input' and (v or 'text') not in INPUT_TYPES:
                self.report.add(where, el.line, 'markup', f'<input type="{v}">',
                                'RmlUi inputs are text, password, checkbox, radio, range, submit, button: written as text')
                attrs[k] = 'text'
                continue
            if k in ('width', 'height') and tag in SIZE_ATTR_TAGS:
                m = re.match(r'^\s*([\d.]+)\s*(px)?\s*$', v or '')
                if m:
                    size_style.append(f'{k}: {V.fmt(float(m.group(1)) / self.units.ppd)}dp')
                    continue
            if k in ('width', 'height') and tag not in ('img', 'input') + tuple(SIZE_ATTR_TAGS):
                self.report.add(where, el.line, 'markup', f'attribute {k} on <{tag}>', 'a browser ignores it on this '
                                'element: dropped (set the size in the sheet)')
                continue
            if k in KEEP_ATTRS:
                attrs[k] = v if v is not None else ''
                continue
            if k in DOC_ONLY_ATTRS:
                continue
            if k == 'href' and tag == 'a':
                self.report.add(where, el.line, 'markup', f'<a href="{v}">', 'RmlUi has no links: answer a '
                                'data-event-click in the client')
                continue
            self.report.add(where, el.line, 'markup', f'attribute {k} on <{tag}>', {
                'title': 'RmlUi shows no tooltips: dropped', 'alt': 'dropped', 'tabindex': 'RmlUi uses the tab-index '
                'property: dropped', 'role': 'RmlUi has no accessibility tree: dropped'}.get(
                    k, 'RmlUi has no accessibility tree: dropped' if k.startswith('aria-') else 'dropped'))
        if size_style:   # width/height attributes of a canvas/video/iframe: its box keeps the size
            attrs['style'] = '; '.join(size_style) + ';' + ((' ' + attrs['style']) if attrs.get('style') else '')
        if tag == 'body' and self.root_class_used:
            classes = [S.ROOT_CLASS] + classes
        if classes:
            attrs = {'class': ' '.join(dict.fromkeys(classes)), **attrs}
        if 'id' in attrs:
            attrs = {'id': attrs.pop('id'), **attrs}
        if tag in REPLACE_WITH_DIV or (tag not in KNOWN_TAGS and tag not in ('body',)):
            self.report.add(where, el.line, 'markup', f'<{tag}>', 'RmlUi has no <%s>: written as a <div> with the '
                            'same id/class (draw it another way)' % tag if tag in REPLACE_WITH_DIV else
                            'unknown element: kept as <%s>, styled by the sheet only' % tag)
            if tag in REPLACE_WITH_DIV:
                tag = 'div'
                el.children = [c for c in el.children if not isinstance(c, H.Element) or c.tag not in ('source', 'track')]
        self.used_tags.add(tag)
        a = ''.join(f' {k}="{_esc_attr(v)}"' for k, v in attrs.items())
        if tag in H.VOID:
            out.append(f'<{tag}{a}/>')
            return
        out.append(f'<{tag}{a}>')
        d = self.display_of(el)
        self.emit_children(el, out, 0, d in ('flex', 'inline-flex'))
        out.append(f'</{tag}>')

    def inline_style(self, el, text):
        all_d = css_parse.parse_decls(text, el.line)
        decls = [d for d in all_d if not d.name.startswith('--')]
        clines = self.custom_lines([d for d in all_d if d.name.startswith('--')], self.page) \
            if self.vars == 'native' else []
        for d in all_d:
            if d.name.startswith('--') and d.important:
                self.report.add(self.where(None), d.line, 'css', f'{d.name}: {d.value} !important (inline)',
                                'RmlUi has no !important: kept without it')
        lines = clines + (self.map_decls(decls, self.page, [el], {'decorator': True, 'mask-image': True,
                                                                  'background-color': True}, set(),
                                         f'style of <{el.tag}>', inline=True) if decls else [])
        return '; '.join(f'{k}: {v}' for k, v in lines) + (';' if lines else '')

    def svg(self, el, out):
        where = self.where(None)
        shapes = [c for c in el.walk() if c is not el and c.tag.lower() in SVG_SHAPES]
        cls = el.classes()
        vb = el.attrs.get('viewbox') or el.attrs.get('viewBox')
        w, h = el.attrs.get('width'), el.attrs.get('height')

        def num(x):
            m = re.match(r'^\s*([\d.]+)\s*(px)?\s*$', x or '')
            return float(m.group(1)) if m else None
        if len(shapes) == 1 and shapes[0].tag == 'path' and vb and not shapes[0].attrs.get('transform') \
                and not [c for c in el.walk() if c.tag == 'g']:
            p = shapes[0]
            self.svg_n += 1
            gen = f'svg-{self.svg_n}'
            attrs = {}
            if el.attrs.get('id'):
                attrs['id'] = el.attrs['id']
            attrs['class'] = ' '.join(cls + p.classes() + [gen])
            attrs['view-box'] = vb
            attrs['d'] = p.attrs.get('d', '')
            for k, v in list(el.attrs.items()) + list(p.attrs.items()):
                if k.startswith('data-'):
                    attrs[k] = v or ''
            extra = sorted({c.tag for c in el.walk() if c is not el and c is not p})
            if extra:   # gradients, clips, masks, filters, titles: Open77's <path> has none of them
                self.report.add(where, el.line, 'markup', f'<svg> with {", ".join("<%s>" % t for t in extra)}',
                                'Open77\'s <path> draws one path in one colour: they are dropped (export a PNG for '
                                'what needs them)')
            for k in p.attrs:
                if k not in ('d', 'class', 'id', 'style') + SVG_PAINT and not k.startswith('data-'):
                    self.report.add(where, p.line, 'markup', f'<path {k}>', 'dropped')
            paint = {}
            for src in (el, p):
                for k in SVG_PAINT:
                    if src.attrs.get(k) is not None:
                        paint[k] = src.attrs[k]
                for d in css_parse.parse_decls(src.attrs.get('style') or '', src.line):
                    if d.name in SVG_PAINT:
                        paint[d.name] = d.value
            vbw = float(vb.split()[2]) if len(vb.split()) == 4 else None
            k_scale = (num(w) / vbw) if (num(w) and vbw) else 1.0
            decl = []
            if num(w):
                decl.append(f'width: {V.fmt(num(w) / self.units.ppd)}dp')
            if num(h):
                decl.append(f'height: {V.fmt(num(h) / self.units.ppd)}dp')
            for k, v in paint.items():
                v = v.strip()
                if k in ('fill', 'stroke'):
                    if v.lower().startswith('url('):
                        self.report.add(where, p.line, 'markup', f'<svg> {k}="{v}"', 'Open77\'s <path> paints one '
                                        f'colour: a gradient or pattern {k} is dropped; write the colour')
                        continue
                    if v == 'none':
                        v = 'transparent'
                    elif v.lower() == 'currentcolor':
                        self.report.add(where, p.line, 'markup', f'<svg> {k}="currentColor"',
                                        f'write the {k} colour in the sheet (path.{gen} or a class of yours)')
                        continue
                    else:
                        try:
                            v = V.ser(V.convert_colors(V.tokenize(v)))
                        except ValueIssue as e:
                            self.report.add(where, p.line, 'markup', f'<svg> {k}="{v}": {e.what}', e.todo)
                            continue
                elif k == 'stroke-width':
                    n = num(v)
                    v = (V.fmt(n * k_scale / self.units.ppd) + 'dp') if n is not None else v
                elif k in ('opacity', 'fill-opacity', 'stroke-opacity'):
                    if k != 'opacity':
                        self.report.add(where, p.line, 'markup', f'<svg> {k}', 'fold it into the colour\'s alpha')
                        continue
                decl.append(f'{k}: {v}')
            for k in el.attrs:
                if k not in ('viewbox', 'width', 'height', 'class', 'id', 'xmlns', 'fill', 'stroke', 'stroke-width',
                             'stroke-linecap', 'stroke-linejoin', 'aria-hidden', 'focusable', 'role', 'version',
                             'xmlns:xlink', 'style', 'opacity') and not k.startswith('data-'):
                    self.report.add(where, el.line, 'markup', f'<svg {k}>', 'dropped')
            if decl:
                self.svg_rules.append((f'path.{gen}', decl))
            self.used_tags.add('path')
            out.append('<path' + ''.join(f' {k}="{_esc_attr(v)}"' for k, v in attrs.items()) + '/>')
            return
        why = 'no viewBox' if not vb else (f'{len(shapes)} shapes' if len(shapes) != 1 else
                                           f'a <{shapes[0].tag}>' if shapes[0].tag != 'path' else 'a group or transform')
        self.report.add(where, el.line, 'markup', f'inline <svg> with {why}',
                        'Open77\'s <path> draws one path with a view-box: merge the shapes into one path d, or export '
                        'a PNG and use <img>/decorator: image(); a <div> of the same size stands in')
        attrs = {}
        if el.attrs.get('id'):
            attrs['id'] = el.attrs['id']
        if cls:
            attrs['class'] = ' '.join(cls)
        decl = []
        if num(w):
            decl.append(f'width: {V.fmt(num(w) / self.units.ppd)}dp')
        if num(h):
            decl.append(f'height: {V.fmt(num(h) / self.units.ppd)}dp')
        if decl:
            self.svg_n += 1
            gen = f'svg-{self.svg_n}'
            attrs['class'] = ((attrs.get('class') or '') + ' ' + gen).strip()
            self.svg_rules.append((f'div.{gen}', ['display: inline-block'] + decl))
        self.used_tags.add('div')
        out.append('<div' + ''.join(f' {k}="{_esc_attr(v)}"' for k, v in attrs.items()) + '></div>')

    def script(self, el):
        where = self.where(None)
        src = el.attrs.get('src')
        code, label = None, 'inline <script>'
        if src:
            label = f'<script src="{src}">'
            p = self.local_path(src, self.pdir)
            if os.path.exists(p):
                code = open(p, encoding='utf-8', errors='replace').read()
            if os.path.basename(src) == 'lrbind.js':
                self.report.add(where, el.line, 'script', label, 'nothing to do: RmlUi runs the data bindings natively; '
                                'the client creates the models (LrBind.create or Open77.ui.create)')
                return
        else:
            code = ''.join(c.text for c in el.children if isinstance(c, H.Text))
        touches = self.script_touches(code or '')
        todo = 'dropped: a script cannot run in NativeUI. Port its logic to the client Lua'
        if touches:
            todo += ' (it touches ' + '; '.join(touches) + ': turn those into bindings or ui:set/ui:style calls)'
        elif src and code is None:
            todo += ' (file not found, nothing to grep)'
        self.report.add(where, el.line, 'script', label, todo)

    def script_touches(self, code):
        ids = sorted(self.ids)
        lits = set(re.findall(r'''(?<![\w$])(?:"([^"\\\n]*)"|'([^'\\\n]*)'|`([^`$\\]*)`)''', code))
        strs = {a or b or c for a, b, c in lits}
        out = []
        hit_ids = [i for i in ids if i in strs or any(re.search(r'#' + re.escape(i) + r'\b', s) for s in strs)]
        if hit_ids:
            out.append('ids ' + ', '.join('#' + i for i in hit_ids))
        sels = sorted(s for s in strs if re.match(r'^[.#][A-Za-z_][\w-]*([ >.#:\[][\w\s.#>=\[\]"\':-]*)?$', s)
                      and len(s) < 60 and not re.fullmatch(r'#[0-9A-Fa-f]{3,8}', s))[:12]   # not colours
        q = re.findall(r'querySelector(?:All)?\(\s*["\']([^"\']+)', code)
        allq = sorted(set(q) | set(x for x in sels if x.lstrip('#') not in self.ids))
        if allq:
            out.append('selectors ' + ', '.join(allq[:12]))
        cl = sorted(set(re.findall(r'classList\.(?:add|remove|toggle|replace)\(\s*["\']([\w-]+)', code)))
        if cl:
            out.append('classes ' + ', '.join('.' + c for c in cl))
        ds = sorted(set(re.findall(r'dataset\.(\w+)', code)))
        if ds:
            out.append('attributes ' + ', '.join('data-' + re.sub(r'([A-Z])', lambda m: '-' + m.group(1).lower(), d)
                                                 for d in ds))
        cp = sorted(set(re.findall(r'setProperty\(\s*["\'](--[\w-]+)', code)))
        if cp:
            out.append('custom properties ' + ', '.join(cp))
        st = sorted(set(re.findall(r'\.style\.(\w+)\s*=', code)))
        if st:
            out.append('inline styles ' + ', '.join(st))
        if re.search(r'\.hidden\s*=', code):
            out.append('the hidden attribute')
        dom = [w for w in ('textContent', 'innerText', 'innerHTML', 'createElement', 'appendChild', 'insertAdjacentHTML',
                           'replaceChildren', 'cloneNode') if w in code]
        if dom:
            out.append('the DOM (' + ', '.join(dom) + ')')
        if 'LrBind.init' in code:
            out.append('LrBind.init (mockup models)')
        return out

    # ---- the whole run
    def run(self):
        text = open(self.page, encoding='utf-8').read()
        doc = H.parse(text)
        for line, what, todo in doc.issues:
            self.report.add(self.where(None), line, 'markup', what, todo)
        self.ids = {el.attrs['id'] for el in doc.root.walk() if el.attrs.get('id')}
        self.script_vars = set()
        for el in doc.root.walk():
            if el.tag == 'script':
                code = ''.join(c.text for c in el.children if isinstance(c, H.Text))
                if el.attrs.get('src'):
                    sp = self.local_path(el.attrs['src'], self.pdir)
                    code = open(sp, encoding='utf-8', errors='replace').read() if os.path.exists(sp) else ''
                self.script_vars |= set(re.findall(r'setProperty\(\s*["\'](--[\w-]+)', code))
        rules = []
        for file, line0, txt, media in self.load_sheets(doc):
            if media and not self.media_ok(media)[0]:
                self.report.add(self.where(file), line0, 'css', f'stylesheet for media {media}', 'not for the canvas: left out')
                continue
            rules += self.flatten(self.parse_sheet(txt, line0, file), file)
        self.custom_props([(f, r) for f, r in rules if isinstance(r, css_parse.Rule)], doc)
        # rem: the root element's font size as the page's cascade computes it (units, var(), calc(), the font
        # shorthand, selector lists); a rem inside it is the initial 16 px, as in CSS
        self.casc.unread = []
        self.units.root_px = self.casc.font_dp(self.top) * self.units.ppd
        for el, v in self.casc.unread:
            if el is self.top:
                self.report.add(self.where(None), el.line, 'css', f'the root font size {v} could not be read',
                                'rem is taken as 16px: write the root font-size in px or %')
        self.casc.memo = {}
        out_rules = self.convert_rules(rules, doc)
        # markup
        self.used_tags = set()
        html = H.find(doc.root, 'html')
        head = H.find(doc.root, 'head')
        body = H.find(doc.root, 'body')
        if html is not None:
            for k in html.attrs:
                if k not in DOC_ONLY_ATTRS:
                    self.report.add(self.where(None), html.line, 'markup', f'attribute {k} on <html>', 'dropped')
        title = H.find(head, 'title') if head is not None else None
        for el in (head.elements() if head is not None else []):
            if el.tag == 'meta':
                nm = (el.attrs.get('name') or el.attrs.get('http-equiv') or '').lower()
                if 'charset' not in el.attrs and nm not in ('viewport', 'content-type', 'color-scheme'):
                    self.report.add(self.where(None), el.line, 'markup', f'<meta {nm or "..."}>', 'dropped')
            elif el.tag == 'link' and 'stylesheet' not in (el.attrs.get('rel') or '').lower():
                self.report.add(self.where(None), el.line, 'markup', f'<link rel="{el.attrs.get("rel")}">', 'dropped')
            elif el.tag in ('script', 'noscript', 'base', 'template'):
                self.emit(el, [], 0)
        parts = []
        # comments outside the body (before it, and in <head>) stay before the body, in their order
        for c in html.children:
            for x in (head.children if c is head else [c]):
                if isinstance(x, H.Comment):
                    parts.append('<!--' + x.text.replace('--', '- -') + '-->\n')
        self.emit(body, parts, 0)
        body_txt = ''.join(parts)
        title_txt = ''.join(c.text for c in title.children if isinstance(c, H.Text)).strip() if title is not None else self.name
        rml = ('<rml>\n<head>\n    <title>%s</title>\n    <link type="text/rcss" href="%s.rcss"/>\n</head>\n'
               '<!-- converted by html2rml from %s; what it could not map: %s.report.md -->\n%s\n</rml>\n'
               % (_esc_text(title_txt), self.name, os.path.basename(self.page), self.name, body_txt))
        rcss = self.sheet(out_rules)
        return rml, rcss

    def sheet(self, out_rules):
        lines = ['/* converted by html2rml from %s (canvas %dx%d, 1 px = %s dp). RmlUi has no default stylesheet: the',
                 '   first block is the part of a browser\'s defaults this page relies on. */']
        lines[0] = lines[0] % (os.path.basename(self.page), self.canvas[0], self.canvas[1], V.fmt(1 / self.units.ppd))
        used = self.used_tags | {'body'}
        blk = [t for t in BLOCK if t in used]
        if blk:
            lines.append('%s { display: block; }' % ', '.join(blk))
        ib = [t for t in INLINE_BLOCK if t in used]
        if ib:
            lines.append('%s { display: inline-block; }' % ', '.join(ib))
        for t, d in TABLE.items():
            if t in used:
                lines.append('%s { display: %s; }' % (t, d))
        for t, d in UA.items():
            if t in used:
                conv = []
                for part in d.split(';'):
                    k, v = part.split(':', 1)
                    toks = V.convert_units(V.tokenize(v.strip()), self.units, [])
                    conv.append(f'{k.strip()}: {V.ser(toks)}')
                lines.append('%s { %s; }' % (t, '; '.join(conv)))
        if self.box_sizing:
            tags = sorted(used - {'br', 'wbr'})
            lines.append('%s { box-sizing: %s; }' % (', '.join(tags), self.box_sizing))
        if self.hidden_used:
            lines.append('.%s { display: none; }' % S.HIDDEN_CLASS)
        for sel, decl in self.svg_rules:
            lines.append('%s { %s; }' % (sel, '; '.join(decl)))
        lines.append('')
        for sel, body in out_rules:
            if sel.startswith('@keyframes'):
                if not body:
                    continue
                lines.append(sel + ' {')
                for fs, fl in body:
                    lines.append('    %s { %s; }' % (fs, '; '.join(f'{k}: {v}' for k, v in fl)))
                lines.append('}')
                continue
            lines.append(wrap(sel, body))
        return '\n'.join(lines) + '\n'


def wrap(sel, decls, width=118):
    head = sel + ' { '
    out, cur = [], head
    for k, v in decls:
        piece = f'{k}: {v}; '
        if len(cur) + len(piece) > width and cur.strip() != head.strip():
            out.append(cur.rstrip())
            cur = '    '
        cur += piece
    out.append(cur + '}')
    return '\n'.join(out)


def convert(page, out, name=None, css=(), canvas=(1920, 1080), px_per_dp=1.0, root=None, vars_mode='fold'):
    c = Converter(page, out, name, css, canvas, px_per_dp, root, vars_mode)
    c.box_sizing = None
    rml, rcss = _run_with_star(c)
    return c, rml, rcss


def _run_with_star(c):
    """the source's `* { box-sizing }` goes into the base block; other `*` declarations stay a `*` rule"""
    orig = c.convert_rules

    def convert_rules(flat, doc):
        keep = []
        for f, it in flat:
            if isinstance(it, css_parse.Rule) and it.decls and it.prelude.strip() == '*':
                bs = [d for d in it.decls if d.name == 'box-sizing']
                if bs:
                    c.box_sizing = bs[-1].value.strip()
                    rest = [d for d in it.decls if d.name != 'box-sizing']
                    if rest:
                        keep.append((f, css_parse.Rule('*', rest, it.line)))
                    continue
            keep.append((f, it))
        return orig(keep, doc)
    c.convert_rules = convert_rules
    return c.run()


def report_md(c):
    items = c.report.items
    out = [f'# html2rml report: {os.path.basename(c.page)} -> {c.name}.rml / {c.name}.rcss', '']
    out.append(f'Canvas {c.canvas[0]}x{c.canvas[1]}, 1 px = {V.fmt(1 / c.units.ppd)} dp. '
               f'{len(items)} item(s) the converter could not map one to one. '
               'Each says what it was and what to do instead.')
    out.append('')
    kinds = [('script', 'Scripts (dropped: port their logic to the client Lua)'), ('font', 'Fonts (the client loads them)'),
             ('markup', 'Markup'), ('selector', 'Selectors (rules dropped)'), ('css', 'Declarations and at-rules')]
    for k, title in kinds:
        its = [i for i in items if i['kind'] == k]
        if not its:
            continue
        out += [f'## {title}', '', '| where | what | do instead |', '|---|---|---|']
        merged = {}
        for i in its:
            key = (i['file'], i['what'], i['todo'])
            merged.setdefault(key, []).append(i['line'])
        for (f, what, todo), ls in merged.items():
            where = f'{f}:{",".join(str(x) for x in sorted(set(ls)))}'
            cell = lambda x: ' '.join(x.split()).replace('|', '/')   # one line per row, whatever the source held
            out.append(f'| {where} | {cell(what)} | {cell(todo)} |')
        out.append('')
    if c.fonts:
        out += ['## Font loading for the client', '', '```lua']
        out += [f['call'] for f in c.fonts]
        out += ['```', '']
    if not items:
        out.append('Nothing to report: everything was mapped.')
    return '\n'.join(out) + '\n'
