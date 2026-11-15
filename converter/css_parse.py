"""CSS structure: rules, at-rules and declarations, with the source line of each. Comments are dropped, strings and
parentheses are respected (a ';' or '}' inside url(...) or a string does not end anything)."""


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


def strip_comments(text):
    """comments out, newlines kept (lines stay right), strings untouched"""
    out, i, n = [], 0, len(text)
    while i < n:
        c = text[i]
        if c in '"\'':
            j = i + 1
            while j < n and text[j] != c:
                j += 2 if text[j] == '\\' else 1
            out.append(text[i:j + 1])
            i = j + 1
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
    def __init__(self, text, line0=1):
        self.t, self.i, self.n = text, 0, len(text)
        self.line0 = line0

    def line_at(self, i):
        return self.line0 + self.t.count('\n', 0, i)

    def skip_ws(self):
        while self.i < self.n and self.t[self.i] in ' \t\r\n\f':
            self.i += 1

    def until(self, stops):
        """text up to (not including) the first char of `stops` at depth 0, outside strings"""
        start, depth = self.i, 0
        while self.i < self.n:
            c = self.t[self.i]
            if c in '"\'':
                j = self.i + 1
                while j < self.n and self.t[j] != c:
                    j += 2 if self.t[j] == '\\' else 1
                self.i = j + 1
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
        start, depth = self.i, 1
        while self.i < self.n:
            c = self.t[self.i]
            if c in '"\'':
                j = self.i + 1
                while j < self.n and self.t[j] != c:
                    j += 2 if self.t[j] == '\\' else 1
                self.i = j + 1
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    inner = self.t[start:self.i]
                    self.i += 1
                    return inner, start
            self.i += 1
        return self.t[start:], start


def parse_decls(text, line0):
    out = []
    r = _Reader(text, line0)
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


def parse(text, line0=1):
    """a stylesheet (comments already stripped or not) -> list of Rule / AtRule"""
    text = strip_comments(text)
    return _parse_items(text, line0)


def _parse_items(text, line0):
    items = []
    r = _Reader(text, line0)
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
                items.append(AtRule(name, prelude.strip(), parse_decls(inner, iline), line, 'decls'))
            elif name.endswith('keyframes'):
                items.append(AtRule(name, prelude.strip(), _parse_items(inner, iline), line, 'keyframes'))
            else:
                items.append(AtRule(name, prelude.strip(), _parse_items(inner, iline), line, 'rules'))
            continue
        prelude = r.until('{;')
        line = r.line_at(start)
        if r.i >= r.n or text[r.i] == ';':
            r.i += 1
            if prelude.strip():
                items.append(Rule(prelude.strip(), None, line))   # junk without a block
            continue
        inner, istart = r.block()
        items.append(Rule(prelude.strip(), parse_decls(inner, r.line_at(istart)), line))
    return items
