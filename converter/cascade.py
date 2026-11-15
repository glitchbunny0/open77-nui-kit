"""The page's static cascade: which declared value wins on an element of the page as written, with inheritance for
custom properties and font-size. A selector can be evaluated "as if" its own state classes were on the elements it
names (#mark.head i: #mark is assumed to carry .head), which is how a state rule gets the custom properties that
state sets. RmlUi has no custom properties and resolves em per element, so both are folded here."""
from contextlib import contextmanager
from . import css_parse, css_values as V, selector as S, html_parse as H

FONT_KW = {'xx-small': 9, 'x-small': 10, 'small': 13, 'medium': 16, 'large': 18, 'x-large': 24, 'xx-large': 32,
           'xxx-large': 48}


class Cascade:
    def __init__(self, rules, doc, units):
        """rules: [(file, Rule)] in cascade order"""
        self.units = units
        self.entries = []   # (sel, spec, order, {name: value}, file, line)
        order = 0
        for file, r in rules:
            if not isinstance(r, css_parse.Rule) or not r.decls:
                continue
            order += 1
            dm, imp = {}, set()
            for d in r.decls:
                if d.important or d.name not in imp:   # a later normal declaration does not beat an !important one
                    dm[d.name] = d.value
                if d.important:
                    imp.add(d.name)
            for t in S.split_list(r.prelude):
                try:
                    sel = S.parse_one(t)
                except S.SelectorIssue:
                    continue
                self.entries.append((sel, S.specificity(sel), order, dm, file, r.line, imp))
        self.by_name = {}
        for e in self.entries:
            for n in e[3]:
                self.by_name.setdefault(n, []).append(e)
        self.version = 0
        self.memo = {}
        self.extra = {}
        self.unread = []
        self.resolving = set()

    @contextmanager
    def assume(self, pairs):
        """pairs: [(element, compound)]: the compound's classes, attributes and pseudo-classes (:hover,
        :nth-child(odd), [data-state="open"]) count as set on that element"""
        saved = {}
        for el, c in pairs:
            saved.setdefault(id(el), (el, getattr(el, 'extra', set()), getattr(el, 'assumed', set())))
            el.extra = set(getattr(el, 'extra', set())) | set(c.classes)
            el.assumed = set(getattr(el, 'assumed', set())) | {('attr',) + tuple(a) for a in c.attrs} \
                | {('pseudo', n, a) for n, a in c.pseudos if n != 'not'}
        self.version += 1
        try:
            yield
        finally:
            for el, old, olda in saved.values():
                el.extra, el.assumed = old, olda
            self.version += 1

    def declared(self, el, name):
        """the winning declared value of `name` on el itself (inline style last), or None"""
        if not isinstance(el, H.Element):
            return None
        inline = None
        st = el.attrs.get('style')
        if st:
            for d in css_parse.parse_decls(st, el.line):
                if d.name == name and (d.important or not (inline and inline[1])):
                    inline = (d.value, d.important)
        if inline and inline[1]:
            return inline[0]
        best = None
        for sel, spec, order, dm, f, l, imp in self.by_name.get(name, ()):
            rank = (name in imp, spec, order)   # !important first, then specificity, then source order
            if (best is None or rank >= best[0]) and S.matches(sel, el):
                best = (rank, dm[name])
        if inline and not (best and best[0][0]):
            return inline[0]
        return best[1] if best else None

    def inherited(self, el, name):
        """the value with inheritance (custom properties, font-size)"""
        if not isinstance(el, H.Element) or el.tag == '#document':
            return None
        key = (id(el), name, self.version)
        if key in self.memo:
            return self.memo[key]
        v = self.declared(el, name)
        if v is None:
            v = self.inherited(el.parent, name)
        elif name.startswith('--') and 'var(' in v:
            v = self._resolve_at(el, name, v)
        self.memo[key] = v
        return v

    def _resolve_at(self, el, name, v):
        """a custom property whose value uses var(): resolved on the element that declares it, as CSS (and RmlUi) do;
        None when it can't be (a cycle, a missing variable without fallback: CSS's guaranteed-invalid value)"""
        key = (id(el), name)
        if key in self.resolving:
            return None
        self.resolving.add(key)
        try:
            return V.ser(V.resolve_vars(V.tokenize(v), lambda n: self.inherited(el, n)))
        except V.ValueIssue:
            return None
        finally:
            self.resolving.discard(key)

    def font_dp(self, el):
        """the element's font size in dp (CSS: 16 px at the root, em/% of the parent's)"""
        if not isinstance(el, H.Element) or el.tag == '#document':
            return 16.0 / self.units.ppd
        key = (id(el), '#font', self.version)
        if key in self.memo:
            return self.memo[key]
        parent = self.font_dp(el.parent)
        v = self.declared(el, 'font-size')
        if v is None:
            f = self.declared(el, 'font')
            if f:
                try:
                    toks = V.resolve_vars(V.tokenize(f), lambda n: self.inherited(el, n))
                    toks = V.fold_math(V.convert_units(toks, self.units, []))
                except V.ValueIssue:
                    toks = []
                for w in V.words(toks):
                    t = w[0]
                    if (t[0] == 'num' and t[2]) or (t[0] == 'ident' and t[1] in FONT_KW):
                        v = V.ser([t])   # the first length is the size (a bare number is the weight)
                        break
        size = parent
        if v is not None:
            size = self.resolve_size(v.strip(), parent, el)
        self.memo[key] = size
        return size

    def resolve_size(self, v, parent, el):
        if v in FONT_KW:
            return FONT_KW[v] / self.units.ppd
        if v == 'smaller':
            return parent / 1.2
        if v == 'larger':
            return parent * 1.2
        try:
            toks = V.resolve_vars(V.tokenize(v), lambda n: self.inherited(el, n))
            toks = V.fold_math(V.convert_units(toks, self.units, []))
        except V.ValueIssue:
            toks = []
        toks = V.strip_ws(toks)
        if len(toks) == 1 and toks[0][0] == 'num':
            n, u = toks[0][1], toks[0][2]
            if u == 'dp' or (u == '' and n == 0):
                return n
            if u == 'em':
                return parent * n
            if u == '%':
                return parent * n / 100
        self.unread.append((el, v))   # a font size the cascade can't read: the parent's is used
        return parent


def align(sel, el, mode='loose'):
    """[(element, compound)] pairing each compound of `sel` with the page element it lands on (right to left),
    or None. 'loose' ignores classes and states, so `#mark.head i` lands on the page's #mark and i."""
    def at(k, node):
        comb, c = sel[k]
        if not S.comp_match(c, node, mode):
            return None
        if k == 0:
            return [(node, c)]
        if comb == ' ':
            p = node.parent
            while p is not None and isinstance(p, H.Element):
                r = at(k - 1, p)
                if r is not None:
                    return r + [(node, c)]
                p = p.parent
            return None
        if comb == '>':
            r = at(k - 1, node.parent) if isinstance(node.parent, H.Element) else None
            return r + [(node, c)] if r is not None else None
        sibs = [x for x in node.parent.elements()] if isinstance(node.parent, H.Element) else []
        i = sibs.index(node) if node in sibs else -1
        if comb == '+':
            r = at(k - 1, sibs[i - 1]) if i > 0 else None
            return r + [(node, c)] if r is not None else None
        for s in reversed(sibs[:max(0, i)]):
            r = at(k - 1, s)
            if r is not None:
                return r + [(node, c)]
        return None
    return at(len(sel) - 1, el)
