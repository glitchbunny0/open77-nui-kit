"""Selectors: parse, check what RmlUi 6.3 matches, rewrite for RML, and match against the page's own tree (for the
static cascade the converter needs: custom properties, display, inline styles)."""
import re

STATE_PSEUDO = {'hover', 'active', 'focus', 'focus-visible', 'checked', 'disabled', 'selected', 'placeholder-shown',
                'drag'}
STRUCTURAL = {'nth-child', 'nth-last-child', 'nth-of-type', 'nth-last-of-type', 'first-child', 'last-child',
              'first-of-type', 'last-of-type', 'only-child', 'only-of-type', 'empty', 'not'}


class SelectorIssue(Exception):
    def __init__(self, what, todo):
        super().__init__(what)
        self.what, self.todo = what, todo


class Compound:
    def __init__(self):
        self.tag, self.id, self.classes, self.attrs, self.pseudos, self.pelems = None, None, [], [], [], []

    def ser(self):
        s = self.tag or ''
        if self.id:
            s += '#' + self.id
        s += ''.join('.' + c for c in self.classes)
        for n, op, v in self.attrs:
            s += '[%s]' % n if op is None else '[%s%s"%s"]' % (n, op, v)
        for n, a in self.pseudos:
            s += ':%s' % n + ('(%s)' % a if a is not None else '')
        s += ''.join('::' + p for p in self.pelems)
        return s or '*'

    def spec(self):
        a = 1 if self.id else 0
        b = len(self.classes) + len(self.attrs) + sum(1 for n, _ in self.pseudos if n != 'not')
        c = 1 if self.tag and self.tag != '*' else 0
        for n, arg in self.pseudos:
            if n == 'not' and arg:
                try:
                    inner = parse_one(arg)
                    sa, sb, sc = specificity(inner)
                    a, b, c = a + sa, b + sb, c + sc
                except SelectorIssue:
                    pass
        return a, b, c


def _read_parens(s, i):
    depth, j = 0, i
    while j < len(s):
        if s[j] == '(':
            depth += 1
        elif s[j] == ')':
            depth -= 1
            if depth == 0:
                return s[i + 1:j], j + 1
        j += 1
    raise SelectorIssue(f'unclosed ( in {s!r}', 'fix the selector')


NAME = re.compile(r'-?[A-Za-z_][\w-]*|\*')


def split_list(text):
    parts, depth, cur, q = [], 0, '', None
    for ch in text:
        if q:
            cur += ch
            if ch == q:
                q = None
            continue
        if ch in '"\'':
            q = ch
        elif ch in '([':
            depth += 1
        elif ch in ')]':
            depth -= 1
        elif ch == ',' and depth == 0:
            parts.append(cur.strip())
            cur = ''
            continue
        cur += ch
    if cur.strip():
        parts.append(cur.strip())
    return parts


def parse_one(text):
    """one complex selector -> [(combinator, Compound)], combinator of the first is ''"""
    s = text.strip()
    out, i, comb, cur = [], 0, '', None
    while i < len(s):
        ch = s[i]
        if ch in ' \t\n>+~':
            j = i
            c = ' '
            while j < len(s) and s[j] in ' \t\n>+~':
                if s[j] != ' ' and s[j] not in '\t\n':
                    c = s[j]
                j += 1
            if cur is not None:
                out.append((comb, cur))
                cur = None
            comb = c
            i = j
            continue
        if cur is None:
            cur = Compound()
        if ch == '#':
            m = re.match(r'#(-?[\w-]+)', s[i:])
            if not m:
                raise SelectorIssue(f'bad id in {text!r}', 'fix the selector')
            cur.id = m.group(1)
            i += len(m.group(0))
        elif ch == '.':
            m = re.match(r'\.(-?[\w-]+)', s[i:])
            if not m:
                raise SelectorIssue(f'bad class in {text!r}', 'fix the selector')
            cur.classes.append(m.group(1))
            i += len(m.group(0))
        elif ch == '[':
            j = s.index(']', i)
            body = s[i + 1:j].strip()
            m = re.match(r'^([\w-]+(?:\|[\w-]+)?)\s*(?:([~|^$*]?=)\s*(.+?))?\s*$', body)
            if not m:
                raise SelectorIssue(f'attribute selector [{body}]', 'write it as a class the markup or client sets')
            name, op, val = m.group(1), m.group(2), m.group(3)
            if '|' in name:
                raise SelectorIssue(f'namespaced attribute [{body}]', 'drop the namespace')
            if val is not None:
                fl = re.match(r'^("[^"]*"|\'[^\']*\'|\S+)\s+([iIsS])$', val)
                if fl:
                    raise SelectorIssue(f'attribute selector flag [{body}]',
                                        'RmlUi compares attribute values case-sensitively; drop the flag')
                if val[:1] in '"\'':
                    val = val[1:-1]
            cur.attrs.append((name, op, val))
            i = j + 1
        elif s.startswith('::', i):
            m = re.match(r'::([\w-]+)', s[i:])
            cur.pelems.append(m.group(1) if m else '?')
            i += len(m.group(0)) if m else 2
            if i < len(s) and s[i] == '(':
                _, i = _read_parens(s, i)
        elif ch == ':':
            m = re.match(r':([\w-]+)', s[i:])
            if not m:
                raise SelectorIssue(f'bad pseudo-class in {text!r}', 'fix the selector')
            name = m.group(1).lower()
            i += len(m.group(0))
            arg = None
            if i < len(s) and s[i] == '(':
                arg, i = _read_parens(s, i)
                arg = arg.strip()
            if name in ('before', 'after', 'first-line', 'first-letter'):
                cur.pelems.append(name)
            else:
                cur.pseudos.append((name, arg))
        else:
            m = NAME.match(s, i)
            if not m:
                raise SelectorIssue(f'cannot read {s[i:]!r} in {text!r}', 'fix the selector')
            if i + len(m.group(0)) < len(s) and s[i + len(m.group(0))] == '|':
                raise SelectorIssue(f'namespace in {text!r}', 'drop the namespace')
            cur.tag = m.group(0).lower() if m.group(0) != '*' else '*'
            i += len(m.group(0))
    if cur is not None:
        out.append((comb, cur))
    if not out:
        raise SelectorIssue('empty selector', 'fix the selector')
    return out


def ser_sel(sel):
    s = ''
    for comb, c in sel:
        if comb == ' ':
            s += ' '
        elif comb:
            s += ' %s ' % comb
        s += c.ser()
    return s


def specificity(sel):
    a = b = c = 0
    for _, comp in sel:
        x, y, z = comp.spec()
        a, b, c = a + x, b + y, c + z
    return a, b, c


# ---- what RmlUi supports
def check(sel):
    """raise SelectorIssue when RmlUi 6.3 would not match this selector the way a browser does"""
    for _, c in sel:
        for p in c.pelems:
            raise SelectorIssue(f'pseudo-element ::{p}', 'RmlUi has no generated content: put a real element in the '
                                'markup (an empty <div class="..."/>) and style that' if p in ('before', 'after')
                                else 'RmlUi has no pseudo-elements: style a real element')
        for n, arg in c.pseudos:
            if n in STATE_PSEUDO or (n == 'root' and arg is None):
                continue
            if n == 'not':
                if arg is None or ',' in arg or re.search(r'[\s>+~]', arg.strip()) or '::' in arg:
                    raise SelectorIssue(f':not({arg}) with a list or a combinator',
                                        'RmlUi\'s :not() takes one compound selector: chain :not(.a):not(.b)')
                inner = parse_one(arg)
                check(inner)
                continue
            if n in STRUCTURAL:
                if n.startswith('nth') and (arg is None or ' of ' in arg):
                    raise SelectorIssue(f':{n}({arg})', 'write a plain an+b argument')
                continue
            if n in ('is', 'where', 'has', 'matches', '-webkit-any', '-moz-any'):
                raise SelectorIssue(f':{n}()', 'RmlUi has no :%s(): write each alternative as its own selector' % n)
            raise SelectorIssue(f':{n}', 'RmlUi 6.3 never sets this pseudo-class (it knows %s and the structural '
                                'ones): toggle a class from the client instead' % ', '.join(sorted(STATE_PSEUDO)))
    return True


ROOT_CLASS = 'html2rml-root'       # :root -> this class on the RML body: class-level specificity, as in CSS
HIDDEN_CLASS = 'html2rml-hidden'   # the hidden attribute (a page's own .hidden class stays its own)


def rewrite(sel, svg_compound=None):
    """RML names: html is the document body, :root its ROOT_CLASS (html2rml-root, so `:root .x` keeps the
    specificity of a class); [hidden] is the HIDDEN_CLASS; an inline <svg> is a <path> (svg_compound(c) says whether a
    compound matches an <svg> of the page: `.icon path` is then `path.icon`)"""
    out = []
    for i, (comb, c) in enumerate(sel):
        c2 = Compound()
        c2.tag, c2.id, c2.classes, c2.pseudos, c2.pelems = c.tag, c.id, list(c.classes), [], list(c.pelems)
        c2.attrs = []
        for a in c.attrs:
            if a[0] == 'hidden' and a[1] is None:
                c2.classes.append(HIDDEN_CLASS)
            else:
                c2.attrs.append(a)
        for n, arg in c.pseudos:
            if n == 'root' and len(sel) == 1 and not (c.tag or c.id or c.classes or c.attrs or len(c.pseudos) > 1):
                c2.tag = 'body'   # a lone :root is body itself (RmlUi sets body's class after styling it once)
            elif n == 'root':
                c2.classes.append(ROOT_CLASS)
                c2.tag = 'body' if c2.tag in ('html', 'body') else c2.tag
            elif n == 'not' and arg:
                try:
                    c2.pseudos.append((n, ser_sel(rewrite(parse_one(arg)))))
                except SelectorIssue:
                    c2.pseudos.append((n, arg))
            else:
                c2.pseudos.append((n, arg))
        if c2.tag == 'html':
            c2.tag = 'body'
        if c2.tag == 'svg':
            c2.tag = 'path'
        if out and c2.tag == 'path' and comb in (' ', '>') and out[-1][1].tag != 'path' and svg_compound \
                and svg_compound(sel[i - 1][1]) and not out[-1][1].pelems:
            out[-1][1].tag = 'path'
        if out and c2.tag == 'path' and out[-1][1].tag == 'path' and comb in (' ', '>'):
            prev = out[-1][1]   # `svg path` is one <path> now
            prev.classes += c2.classes
            prev.id = prev.id or c2.id
            prev.pseudos += c2.pseudos
            continue
        if out and c2.tag == 'body' and comb in (' ', '>') and (out[-1][1].tag == 'body'
                                                                or ROOT_CLASS in out[-1][1].classes):
            prev = out.pop()[1]   # `html body`, `:root body`: the one root element
            c2.classes = [x for x in prev.classes if x not in c2.classes] + c2.classes
        out.append((comb, c2))
    return out


# ---- matching against the page's tree (static state: no hover, classes from the class attribute only)
def _nth(arg, pos):
    a = arg.replace(' ', '').lower()
    if a == 'odd':
        A, B = 2, 1
    elif a == 'even':
        A, B = 2, 0
    else:
        m = re.match(r'^([+-]?\d*)n([+-]\d+)?$', a)
        if m:
            A = int(m.group(1)) if m.group(1) not in ('', '+', '-') else (-1 if m.group(1) == '-' else 1)
            B = int(m.group(2) or 0)
        else:
            try:
                A, B = 0, int(a)
            except ValueError:
                return False
    if A == 0:
        return pos == B
    return (pos - B) % A == 0 and (pos - B) // A >= 0


def comp_match(c, el, dynamic=False):
    if el is None or not hasattr(el, 'tag'):
        return False
    if c.tag and c.tag != '*' and c.tag != el.tag:
        return False
    if c.id and el.attrs.get('id') != c.id:
        return False
    if dynamic == 'loose':
        return True   # tags and ids only: where a state rule (.on toggled by a script) would apply
    cls = el.classes(bool(dynamic))
    if any(x not in cls for x in c.classes):
        return False
    assumed = getattr(el, 'assumed', ())   # pseudo-classes and attributes a state assumption puts on el
    for n, op, v in c.attrs:
        if ('attr', n, op, v) in assumed:
            continue
        if n not in el.attrs:
            return False
        av = el.attrs[n] or ''
        if op == '=' and av != v:
            return False
        if op == '~=' and v not in av.split():
            return False
        if op == '|=' and not (av == v or av.startswith(v + '-')):
            return False
        if op == '^=' and not av.startswith(v):
            return False
        if op == '$=' and not av.endswith(v):
            return False
        if op == '*=' and v not in av:
            return False
    for n, arg in c.pseudos:
        if n == 'root':
            if el.tag != 'html':
                return False
            continue
        if ('pseudo', n, arg) in assumed:
            continue
        if n in STATE_PSEUDO:
            if dynamic == 'relaxed':
                continue   # :hover and friends: any element may get them
            return False
        if n != 'not' and (getattr(el, 'virtual', False) or 'data-for' in el.attrs):
            # a structural pseudo-class on an element a data-for repeats (or one only a script builds): any copy may
            # match it, the one in the page's tree tells nothing
            if dynamic == 'relaxed' or getattr(el, 'virtual', False):
                continue
            return False
        sib = [x for x in el.parent.children if hasattr(x, 'tag')] if el.parent else [el]
        same = [x for x in sib if x.tag == el.tag]
        if n == 'first-child' and sib[0] is not el:
            return False
        if n == 'last-child' and sib[-1] is not el:
            return False
        if n == 'only-child' and len(sib) != 1:
            return False
        if n == 'first-of-type' and same[0] is not el:
            return False
        if n == 'last-of-type' and same[-1] is not el:
            return False
        if n == 'only-of-type' and len(same) != 1:
            return False
        if n == 'empty' and any(hasattr(x, 'tag') or (hasattr(x, 'text') and type(x).__name__ == 'Text' and x.text.strip())
                                for x in el.children):
            return False
        if n == 'nth-child' and not _nth(arg or '', sib.index(el) + 1):
            return False
        if n == 'nth-last-child' and not _nth(arg or '', len(sib) - sib.index(el)):
            return False
        if n == 'nth-of-type' and not _nth(arg or '', same.index(el) + 1):
            return False
        if n == 'nth-last-of-type' and not _nth(arg or '', len(same) - same.index(el)):
            return False
        if n == 'not':
            try:
                inner = parse_one(arg)
            except SelectorIssue:
                return False
            if len(inner) == 1 and comp_match(inner[0][1], el, dynamic if dynamic != 'loose' else False):
                return False
        if n not in STATE_PSEUDO and n not in STRUCTURAL and n != 'root':
            return False
    return True


def matches(sel, el, dynamic=False):
    """right to left. dynamic: False = the page as written (classes from the class attribute, no :hover),
    True = + data-class-* names, 'relaxed' = + state pseudo-classes, 'loose' = tags and ids only"""
    def at(k, node):
        comb, c = sel[k]
        if not comp_match(c, node, dynamic):
            return False
        if k == 0:
            return True
        if comb == ' ':
            p = node.parent
            while p is not None:
                if at(k - 1, p):
                    return True
                p = p.parent
            return False
        if comb == '>':
            return at(k - 1, node.parent) if node.parent is not None else False
        sibs = [x for x in node.parent.children if hasattr(x, 'tag')] if node.parent else []
        i = sibs.index(node) if node in sibs else -1
        if comb == '+':
            return i > 0 and at(k - 1, sibs[i - 1])
        if comb == '~':
            return any(at(k - 1, s) for s in sibs[:max(0, i)])
        return False
    return at(len(sel) - 1, el)
