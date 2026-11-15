"""CSS component values: a small tokenizer, var() folding, unit conversion to dp, calc()/min()/max()/clamp() folding
and colours written the way RmlUi 6.3 reads them (hex). Errors are raised as ValueIssue(reason, todo) for the
caller's report."""
import colorsys, math, re
from .named_colors import NAMED


class ValueIssue(Exception):
    def __init__(self, what, todo=''):
        super().__init__(what)
        self.what, self.todo = what, todo


# ---- tokens: (kind, ...). kinds: ws, comma, slash, op (+ - *), str, num (value, unit), hash, ident,
# func (name, args), paren (args), url (path), delim
NUM_RE = re.compile(r'[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?')
IDENT_START = re.compile(r'-?-?[A-Za-z_\u00a0-\uffff\\]|--')


def tokenize(s):
    toks, i, n = [], 0, len(s)
    stack = [toks]

    def prev_sig():
        cur = stack[-1]
        for t in reversed(cur):
            if t[0] != 'ws':
                return t
        return None

    while i < n:
        c = s[i]
        cur = stack[-1]
        if c in ' \t\r\n\f':
            j = i
            while j < n and s[j] in ' \t\r\n\f':
                j += 1
            cur.append(('ws',))
            i = j
        elif c == ',':
            cur.append(('comma',))
            i += 1
        elif c == '/':
            cur.append(('slash',))
            i += 1
        elif c in '"\'':
            j = i + 1
            while j < n and s[j] != c:
                j += 2 if s[j] == '\\' else 1
            cur.append(('str', s[i + 1:j]))
            i = j + 1
        elif c == ')':
            if len(stack) > 1:
                stack.pop()
            i += 1
        elif c == '(':
            grp = []
            cur.append(('paren', grp))
            stack.append(grp)
            i += 1
        elif c == '#':
            m = re.match(r'#[\w-]+', s[i:])
            cur.append(('hash', m.group(0) if m else '#'))
            i += len(m.group(0)) if m else 1
        elif (c.isdigit() or (c == '.' and i + 1 < n and s[i + 1].isdigit()) or
              (c in '+-' and NUM_RE.match(s, i) and (prev_sig() is None or prev_sig()[0] in ('comma', 'op', 'slash')
                                                      or (cur and cur[-1][0] == 'ws')))):
            m = NUM_RE.match(s, i)
            j = m.end()
            u = re.match(r'%|[A-Za-z]+', s[j:])
            unit = u.group(0).lower() if u else ''
            cur.append(('num', float(m.group(0)), unit))
            i = j + len(unit)
        elif c in '+-*' and not (c == '-' and IDENT_START.match(s, i)):
            cur.append(('op', c))
            i += 1
        elif IDENT_START.match(s, i):
            m = re.match(r'(?:--|-?)[\w\u00a0-\uffff-]*', s[i:])
            name = m.group(0)
            j = i + len(name)
            if j < n and s[j] == '(':
                if name.lower() == 'url':
                    k = j + 1
                    while k < n and s[k] in ' \t':
                        k += 1
                    if k < n and s[k] in '"\'':
                        q = s[k]
                        e = s.find(q, k + 1)
                        path = s[k + 1:e]
                        e = s.find(')', e)
                    else:
                        e = s.find(')', k)
                        e = n if e < 0 else e
                        path = s[k:e].strip()
                    cur.append(('url', path))
                    i = e + 1
                    continue
                args = []
                cur.append(('func', name.lower() if not name.startswith('--') else name, args))
                stack.append(args)
                i = j + 1
            else:
                cur.append(('ident', name))
                i = j
        else:
            cur.append(('delim', c))
            i += 1
    return toks


# function names are matched lower-case; RmlUi's transform parser wants these spelled as CSS writes them
CAMEL = {n.lower(): n for n in ('translateX', 'translateY', 'translateZ', 'rotateX', 'rotateY', 'rotateZ', 'scaleX',
                                'scaleY', 'scaleZ', 'skewX', 'skewY')}


def fmt(v):
    if abs(v - round(v)) < 1e-6:
        return str(int(round(v)))
    s = ('%.4f' % v).rstrip('0').rstrip('.')
    return '0' if s in ('-0', '') else s


def ser(toks):
    out = []
    for t in toks:
        k = t[0]
        if k == 'ws':
            out.append(' ')
        elif k == 'comma':
            out.append(', ')
        elif k == 'slash':
            out.append(' / ')
        elif k == 'op':
            out.append(' %s ' % t[1] if t[1] in '+-' else t[1])
        elif k == 'str':
            out.append('"%s"' % t[1])
        elif k == 'num':
            out.append(fmt(t[1]) + t[2])
        elif k in ('hash', 'ident', 'delim'):
            out.append(t[1])
        elif k == 'func':
            out.append('%s(%s)' % (CAMEL.get(t[1], t[1]), ser(t[2])))
        elif k == 'paren':
            out.append('(%s)' % ser(t[1]))
        elif k == 'url':
            out.append('url(%s)' % t[1])
    s = ''.join(out)
    s = re.sub(r'\s+', ' ', s)
    s = re.sub(r'\s*,\s*', ', ', s)
    s = re.sub(r'\(\s+', '(', s)
    s = re.sub(r'\s+\)', ')', s)
    s = re.sub(r' \* ', '*', s)
    return s.strip()


def split(toks, kind='comma'):
    """split a token list on top-level commas (or 'ws' for space-separated components)"""
    parts, cur = [], []
    for t in toks:
        if t[0] == kind:
            parts.append(cur)
            cur = []
        else:
            cur.append(t)
    parts.append(cur)
    if kind == 'ws':
        parts = [p for p in parts if p]
    return parts


def strip_ws(toks):
    a, b = 0, len(toks)
    while a < b and toks[a][0] == 'ws':
        a += 1
    while b > a and toks[b - 1][0] == 'ws':
        b -= 1
    return toks[a:b]


def words(toks):
    """space-separated components at the top level, commas/slashes kept as their own words"""
    out, cur = [], []
    for t in toks:
        if t[0] == 'ws':
            if cur:
                out.append(cur)
                cur = []
        elif t[0] in ('comma', 'slash'):
            if cur:
                out.append(cur)
                cur = []
            out.append([t])
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


# ---- var()
def resolve_vars(toks, lookup, stack=()):
    """replace every var(--x[, fallback]) with its value's tokens. lookup(name) -> raw text or None.
    Raises ValueIssue on an unknown name without fallback or a cycle."""
    out = []
    for t in toks:
        if t[0] == 'func' and t[1] == 'var':
            args = t[2]
            parts = split(args)
            name = ser(parts[0]).strip()
            if name in stack:
                raise ValueIssue(f'var({name}) refers to itself', 'write the value')
            raw = lookup(name)
            if raw is not None:
                out.extend(resolve_vars(tokenize(raw), lookup, stack + (name,)))
            elif len(parts) > 1:
                fb = args[[i for i, a in enumerate(args) if a[0] == 'comma'][0] + 1:]
                out.extend(resolve_vars(strip_ws(fb), lookup, stack))
            else:
                raise ValueIssue(f'var({name}) has no value here and no fallback',
                                 'define it in :root (static value) or write the value; if a script sets it, the '
                                 'client must set the resulting property instead')
        elif t[0] in ('func', 'paren'):
            out.append(t[:-1] + (resolve_vars(t[-1], lookup, stack),))
        else:
            out.append(t)
    return out


def has_var(toks):
    for t in toks:
        if t[0] == 'func' and t[1] == 'var':
            return True
        if t[0] in ('func', 'paren') and has_var(t[-1]):
            return True
    return False


def var_names(toks, out=None):
    out = [] if out is None else out
    for t in toks:
        if t[0] == 'func' and t[1] == 'var':
            out.append(ser(split(t[2])[0]).strip())
            var_names(t[2], out)
        elif t[0] in ('func', 'paren'):
            var_names(t[-1], out)
    return out


# ---- units
class Units:
    def __init__(self, px_per_dp=1.0, canvas=(1920, 1080), root_px=16.0):
        self.ppd, self.canvas, self.root_px = px_per_dp, canvas, root_px

    def px(self, v, unit):
        """length in CSS px for absolute and canvas-relative units, else None"""
        w, h = self.canvas
        return {'px': v, 'vw': v * w / 100, 'vh': v * h / 100, 'vmin': v * min(w, h) / 100,
                'vmax': v * max(w, h) / 100, 'rem': v * self.root_px, 'pt': v * 4 / 3, 'pc': v * 16, 'in': v * 96,
                'cm': v * 96 / 2.54, 'mm': v * 96 / 25.4, 'q': v * 96 / 101.6}.get(unit)


KEEP_UNITS = {'', '%', 'dp', 'em', 'deg', 'rad', 's', 'x'}


def convert_units(toks, units, notes):
    """px and friends -> dp, ms -> s, turn/grad -> deg; notes collects unit names that have no RmlUi form"""
    out = []
    for t in toks:
        if t[0] == 'num':
            v, u = t[1], t[2]
            p = units.px(v, u)
            if p is not None:
                out.append(('num', p / units.ppd, 'dp' if p else ''))
            elif u == 'ms':
                out.append(('num', v / 1000, 's'))
            elif u == 'turn':
                out.append(('num', v * 360, 'deg'))
            elif u == 'grad':
                out.append(('num', v * 0.9, 'deg'))
            elif u in KEEP_UNITS:
                out.append(t)
            else:
                notes.append(u)
                out.append(t)
        elif t[0] in ('func', 'paren'):
            out.append(t[:-1] + (convert_units(t[-1], units, notes),))
        else:
            out.append(t)
    return out


# ---- calc()
MATH_FUNCS = ('calc', 'min', 'max', 'clamp', '-webkit-calc')


def fold_math(toks):
    out = []
    for t in toks:
        if t[0] == 'func' and t[1] in MATH_FUNCS:
            v, u = _eval_func(t)
            out.append(('num', v, u))
        elif t[0] in ('func', 'paren'):
            out.append(t[:-1] + (fold_math(t[-1]),))
        else:
            out.append(t)
    return out


def _eval_func(t):
    name, args = t[1], t[2]
    if name in ('calc', '-webkit-calc'):
        return _Calc(args).run()
    vals = [_Calc(a).run() for a in split(args)]
    units = {u for v, u in vals if not (v == 0 and u == '')}
    if len(units) > 1:
        raise ValueIssue(f'{name}() mixes units ({", ".join(sorted(units))})',
                         'pick the value for the design canvas and write it in dp')
    unit = units.pop() if units else ''
    nums = [v for v, _ in vals]
    if name == 'min':
        return min(nums), unit
    if name == 'max':
        return max(nums), unit
    if len(nums) != 3:
        raise ValueIssue('clamp() needs three values', 'write the value')
    return max(nums[0], min(nums[1], nums[2])), unit


class _Calc:
    def __init__(self, toks):
        self.t = [x for x in toks if x[0] != 'ws']
        self.i = 0

    def run(self):
        v = self.expr()
        if self.i != len(self.t):
            raise ValueIssue('calc() could not be read: ' + ser(self.t), 'write the value')
        return v

    def peek(self):
        return self.t[self.i] if self.i < len(self.t) else None

    def expr(self):
        a = self.term()
        while self.peek() and self.peek()[0] == 'op' and self.peek()[1] in '+-':
            op = self.t[self.i][1]
            self.i += 1
            b = self.term()
            a = self.add(a, b, op)
        return a

    def term(self):
        a = self.factor()
        while self.peek() and (self.peek()[0] == 'slash' or (self.peek()[0] == 'op' and self.peek()[1] == '*')):
            op = '/' if self.t[self.i][0] == 'slash' else '*'
            self.i += 1
            b = self.factor()
            if op == '*':
                if a[1] and b[1]:
                    raise ValueIssue('calc() multiplies two lengths', 'write the value')
                a = (a[0] * b[0], a[1] or b[1])
            else:
                if b[1]:
                    raise ValueIssue('calc() divides by a length', 'write the value')
                if b[0] == 0:
                    raise ValueIssue('calc() divides by zero', 'write the value')
                a = (a[0] / b[0], a[1])
        return a

    def factor(self):
        t = self.peek()
        if t is None:
            raise ValueIssue('calc() ends early', 'write the value')
        self.i += 1
        if t[0] == 'num':
            return (t[1], t[2])
        if t[0] == 'paren':
            return _Calc(t[1]).run()
        if t[0] == 'func' and t[1] in MATH_FUNCS:
            return _eval_func(t)
        if t[0] == 'op' and t[1] == '-':
            v = self.factor()
            return (-v[0], v[1])
        if t[0] == 'ident' and t[1].lower() in ('pi', 'e'):
            return (math.pi if t[1].lower() == 'pi' else math.e, '')
        raise ValueIssue(f'calc() term {ser([t])!r} is not a number', 'write the value')

    @staticmethod
    def add(a, b, op):
        if a[1] != b[1] and not (a[0] == 0 and not a[1]) and not (b[0] == 0 and not b[1]):
            raise ValueIssue(f'calc() mixes {a[1] or "numbers"} and {b[1] or "numbers"}',
                             'RmlUi has no calc(): pick the value for the design canvas (or set it from the client '
                             'with ui:style)')
        return (a[0] + b[0] if op == '+' else a[0] - b[0], a[1] or b[1])


# ---- colours
def _hex(r, g, b, a=1.0):
    r, g, b = [max(0, min(255, int(round(x)))) for x in (r, g, b)]
    al = max(0, min(255, int(a * 255 + 0.5)))
    return '#%02X%02X%02X' % (r, g, b) + ('' if al == 255 else '%02X' % al)


def _chan(t, scale=255):
    if t[0] != 'num':
        raise ValueIssue('colour channel ' + ser([t]), 'write the colour as #RRGGBBAA')
    return t[1] * scale / 100 if t[2] == '%' else t[1]


def _alpha(t):
    if t[0] != 'num':
        raise ValueIssue('colour alpha ' + ser([t]), 'write the colour as #RRGGBBAA')
    return t[1] / 100 if t[2] == '%' else t[1]


def _func_args(args):
    """rgb(1, 2, 3[, a]) or rgb(1 2 3[ / a]) -> ([three], alpha token or None)"""
    flat = [x for x in args if x[0] not in ('ws', 'comma')]
    alpha = None
    if any(x[0] == 'slash' for x in flat):
        k = [i for i, x in enumerate(flat) if x[0] == 'slash'][0]
        alpha = flat[k + 1] if k + 1 < len(flat) else None
        flat = flat[:k]
    elif len(flat) == 4:
        alpha = flat[3]
        flat = flat[:3]
    if len(flat) != 3:
        raise ValueIssue('colour function with %d channels' % len(flat), 'write the colour as #RRGGBBAA')
    return flat, alpha


def color_of(t):
    """a colour token -> hex string, None if the token is not a colour"""
    if t[0] == 'hash':
        h = t[1][1:]
        if len(h) in (3, 4, 6, 8) and all(c in '0123456789abcdefABCDEF' for c in h):
            return t[1]
        raise ValueIssue(f'colour {t[1]}', 'write #RGB, #RGBA, #RRGGBB or #RRGGBBAA')
    if t[0] == 'ident':
        n = t[1].lower()
        if n == 'transparent':
            return 'transparent'
        if n in NAMED:
            return NAMED[n]
        return None
    if t[0] == 'func' and t[1] in ('rgb', 'rgba'):
        ch, al = _func_args(t[2])
        return _hex(*[_chan(c) for c in ch], a=_alpha(al) if al else 1.0)
    if t[0] == 'func' and t[1] in ('hsl', 'hsla'):
        ch, al = _func_args(t[2])
        hh = ch[0][1] if ch[0][0] == 'num' else 0
        if ch[0][0] == 'num' and ch[0][2] == 'rad':
            hh = math.degrees(hh)
        s, l = _chan(ch[1], 100) / 100, _chan(ch[2], 100) / 100
        r, g, b = colorsys.hls_to_rgb((hh % 360) / 360, l, s)
        return _hex(r * 255, g * 255, b * 255, a=_alpha(al) if al else 1.0)
    if t[0] == 'func' and t[1] in ('hwb', 'lab', 'lch', 'oklab', 'oklch', 'color', 'color-mix'):
        raise ValueIssue(f'colour function {t[1]}()', 'write the colour as #RRGGBBAA')
    return None


def convert_colors(toks, current=None):
    out = []
    for t in toks:
        if t[0] == 'ident' and t[1].lower() == 'currentcolor':
            if current is None:
                raise ValueIssue('currentColor', 'RmlUi has no currentColor: write the colour')
            out.append(('hash', current) if current.startswith('#') else ('ident', current))
            continue
        c = color_of(t)
        if c is not None:
            out.append(('hash', c) if c.startswith('#') else ('ident', c))
        elif t[0] in ('func', 'paren'):
            out.append(t[:-1] + (convert_colors(t[-1], current),))
        else:
            out.append(t)
    return out


def is_color(t):
    try:
        return color_of(t) is not None
    except ValueIssue:
        return False
