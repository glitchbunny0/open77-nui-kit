"""CSS structure: rules, at-rules and declarations, with the source line of each. Comments are dropped, strings and
parentheses are respected (a ';' or '}' inside url(...) or a string does not end anything). A string ends at an
unescaped newline, as in a browser (a "bad string": parse(..., bad) gets its line). Nested rules (CSS nesting) are
flattened after their parent rule, `&` standing for the parent selector."""

import re


class Decl:
    def __init__(self, name, value, important, line):
        self.name, self.value, self.important, self.line = name, value, important, line

    def __repr__(self):
        return f'Decl({self.name}: {self.value}{" !important" if self.important else ""} @{self.line})'


class Rule:
    """a qualified rule: `prelude { decls }`"""
    def __init__(self, prelude, decls, line):
        self.prelude, self.decls, self.line = prelude, decls, line


class AtRule:
    """`@name prelude ;` (block None) or `@name prelude { ... }` (block: list of Rule/AtRule, or decls for
    @font-face/@page, or the raw text for @keyframes frames as Rules whose prelude is the frame selector)"""
    def __init__(self, name, prelude, block, line, kind):
        self.name, self.prelude, self.block, self.line, self.kind = name, prelude, block, line, kind


def _string_end(text, i, n):
    """at a quote: the index after the string (an unescaped newline ends it: a browser's bad string)"""
    c, j = text[i], i + 1
    while j < n and text[j] != c and text[j] != '\n':
        j += 2 if text[j] == '\\' else 1
    return min(j + 1, n) if j < n and text[j] == c else min(j, n)


def strip_comments(text):
    """comments out, newlines kept (lines stay right), strings untouched"""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in '"\'':
            j = _string_end(text, i, n)
            out.append(text[i:j])
            i = j
        elif text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            out.append('\n' * text.count('\n', i, j) or ' ')
            i = j
        else:
            out.append(c)
            i += 1
    return ''.join(out)


class _Reader:
    def __init__(self, text, line0=1, bad=None):
        self.t, self.i, self.n = text, 0, len(text)
        self.line0 = line0
        self.bad = bad if bad is not None else set()   # lines of strings a newline ended

    def line_at(self, i):
        return self.line0 + self.t.count('\n', 0, i)

    def string(self):
        j = _string_end(self.t, self.i, self.n)
        if self.t[j - 1:j] != self.t[self.i] or j == self.i + 1:
            self.bad.add(self.line_at(self.i))
        self.i = j

    def skip_ws(self):
        while self.i < self.n and self.t[self.i] in ' \t\r\n\f':
            self.i += 1

    def until(self, stops):
        """text up to (not including) the first char of `stops` at depth 0, outside strings"""
        start, depth = self.i, 0
        while self.i < self.n:
            c = self.t[self.i]
            if c in '"\'':
                self.string()
                continue
            if c in '([':
                depth += 1
            elif c in ')]':
                depth = max(0, depth - 1)
            elif depth == 0 and c in stops:
                break
            self.i += 1
        return self.t[start:self.i]

    def block(self):
        """at '{': the text inside the matching braces; leaves the reader after '}'"""
        assert self.t[self.i] == '{'
        self.i += 1
        start, depth, parens = self.i, 1, 0
        while self.i < self.n:
            c = self.t[self.i]
            if c in '"\'':
                self.string()
                continue
            if c == '(':
                parens += 1
            elif c == ')':
                parens = max(0, parens - 1)
            elif parens:
                pass   # `}` inside url(x;}.png) or another function ends nothing
            elif c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    inner = self.t[start:self.i]
                    self.i += 1
                    return inner, start
            self.i += 1
        return self.t[start:], start


def parse_decls(text, line0, bad=None):
    out = []
    r = _Reader(text, line0, bad)
    while True:
        r.skip_ws()
        if r.i >= r.n:
            break
        start = r.i
        chunk = r.until(';')
        if r.i < r.n:
            r.i += 1
        if not chunk.strip():
            continue
        line = r.line_at(start)
        if ':' not in chunk:
            out.append(Decl('', chunk.strip(), False, line))   # junk: reported by the caller
            continue
        name, value = chunk.split(':', 1)
        value = value.strip()
        important = False
        low = value.lower()
        k = low.rfind('!')
        if k >= 0 and low[k + 1:].strip() == 'important':
            important, value = True, value[:k].strip()
        out.append(Decl(name.strip().lower() if not name.strip().startswith('--') else name.strip(), value, important, line))
    return out


DECL_BLOCK_AT = {'font-face', 'page', 'counter-style', 'property', 'font-feature-values', 'viewport'}


def parse(text, line0=1, bad=None):
    """a stylesheet (comments already stripped or not) -> list of Rule / AtRule; `bad` (a set) gets the lines of
    strings a newline ended"""
    text = strip_comments(text)
    return _parse_items(text, line0, bad)


def _parse_items(text, line0, bad=None):
    items = []
    r = _Reader(text, line0, bad)
    while True:
        r.skip_ws()
        if r.i >= r.n:
            break
        start = r.i
        if text[r.i] == '@':
            r.i += 1
            j = r.i
            while r.i < r.n and (text[r.i].isalnum() or text[r.i] in '-_'):
                r.i += 1
            name = text[j:r.i].lower()
            prelude = r.until('{;')
            line = r.line_at(start)
            if r.i >= r.n or text[r.i] == ';':
                r.i += 1
                items.append(AtRule(name, prelude.strip(), None, line, 'statement'))
                continue
            inner, istart = r.block()
            iline = r.line_at(istart)
            if name in DECL_BLOCK_AT:
                items.append(AtRule(name, prelude.strip(), parse_decls(inner, iline, bad), line, 'decls'))
            elif name.endswith('keyframes'):
                items.append(AtRule(name, prelude.strip(), _parse_items(inner, iline, bad), line, 'keyframes'))
            else:
                items.append(AtRule(name, prelude.strip(), _parse_items(inner, iline, bad), line, 'rules'))
            continue
        prelude = r.until('{;')
        line = r.line_at(start)
        if r.i >= r.n or text[r.i] == ';':
            r.i += 1
            if prelude.strip():
                items.append(Rule(prelude.strip(), None, line))   # junk without a block
            continue
        inner, istart = r.block()
        items += _nested_rule(prelude.strip(), inner, r.line_at(istart), line, bad)
    return items


def _nested_rule(prelude, inner, iline, line, bad):
    """a rule whose block holds nested rules (CSS nesting: `.a { color: red; &:hover { } .b { } }`) -> the rule and
    the nested ones flattened after it, `&` standing for the parent (a nested selector without & is a descendant)"""
    r = _Reader(inner, iline, bad)
    decl_text, nested = list(inner), []
    while True:
        r.skip_ws()
        if r.i >= r.n:
            break
        start = r.i
        r.until(';{}')
        if r.i < r.n and inner[r.i] == '{' and re.match(r'^\s*(--|[-\w]+\s*:[^:]*["\'])', inner[start:r.i]):
            r.block()   # a declaration holding a {} block (a custom property, or a string a newline ended)
        elif r.i < r.n and inner[r.i] == '{':
            sub_pre = inner[start:r.i].strip()
            sub_line = r.line_at(start)
            body, bstart = r.block()
            for k in range(start, r.i):   # blank the nested rule out of the declarations, lines kept
                decl_text[k] = '\n' if inner[k] == '\n' else ' '
            nested.append((sub_pre, body, r.line_at(bstart), sub_line))
        elif r.i < r.n:
            r.i += 1
    out = [Rule(prelude, parse_decls(''.join(decl_text), iline, bad), line)]
    parents = [p.strip() for p in _split_sel(prelude)]
    for sub_pre, body, bline, sline in nested:
        if sub_pre.startswith('@'):   # @media/@supports nested in a rule: the at-rule around the parent's selector
            name, _, rest = sub_pre[1:].partition(' ')
            out.append(AtRule(name.lower(), rest.strip(), _nested_rule(prelude, body, bline, sline, bad), sline, 'rules'))
            continue
        sels = []
        for part in _split_sel(sub_pre):
            part = part.strip()
            for par in parents:
                sels.append(part.replace('&', par) if '&' in part else f'{par} {part}')
        out += _nested_rule(', '.join(sels), body, bline, sline, bad)
    return out


def _split_sel(text):
    parts, depth, cur = [], 0, ''
    for ch in text:
        depth += {'(': 1, '[': 1, ')': -1, ']': -1}.get(ch, 0)
        if ch == ',' and depth == 0:
            parts.append(cur)
            cur = ''
        else:
            cur += ch
    return parts + [cur] if cur.strip() else parts
