"""The page's tree: stdlib html.parser into a small DOM with source lines (void tags, raw text elements, implied end
tags handled the way a browser would for well-formed-ish pages)."""
from html.parser import HTMLParser

VOID = {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}
# a start tag of these closes an open <p> (the HTML parser's implied end tag)
CLOSES_P = {'address', 'article', 'aside', 'blockquote', 'div', 'dl', 'fieldset', 'footer', 'form', 'h1', 'h2', 'h3',
            'h4', 'h5', 'h6', 'header', 'hr', 'main', 'nav', 'ol', 'p', 'pre', 'section', 'table', 'ul', 'figure'}


class Text:
    def __init__(self, text, line):
        self.text, self.line, self.parent = text, line, None


class Comment:
    def __init__(self, text, line):
        self.text, self.line, self.parent = text, line, None


class Element:
    def __init__(self, tag, attrs, line, parent=None):
        self.tag, self.line, self.parent = tag, line, parent
        self.attrs = {}
        for k, v in attrs:
            if k not in self.attrs:
                self.attrs[k] = v
        self.children = []
        self.self_closed = False
        self.reparented = []   # notes from the tree builder (implied end tags)

    def classes(self, dynamic=False):
        out = (self.attrs.get('class') or '').split() + sorted(getattr(self, 'extra', ()))
        if dynamic:
            out += [k[len('data-class-'):] for k in self.attrs if k.startswith('data-class-')]
        return out

    def elements(self):
        return [c for c in self.children if isinstance(c, Element)]

    def walk(self):
        yield self
        for c in self.children:
            if isinstance(c, Element):
                yield from c.walk()

    def __repr__(self):
        return '<%s%s%s @%d>' % (self.tag, '#' + self.attrs['id'] if self.attrs.get('id') else '',
                                 ''.join('.' + c for c in self.classes()), self.line)


class Doc:
    def __init__(self):
        self.root = Element('#document', [], 0)
        self.doctype = None
        self.issues = []   # (line, what, todo) from parsing


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.doc = Doc()
        self.stack = [self.doc.root]

    def _line(self):
        return self.getpos()[0]

    def handle_decl(self, decl):
        self.doc.doctype = decl

    def handle_starttag(self, tag, attrs):
        if tag == 'p' or tag in CLOSES_P:
            if any(e.tag == 'p' for e in self.stack):
                while self.stack[-1].tag != 'p':
                    self.stack.pop()
                self.stack.pop()
                if tag != 'p':
                    self.doc.issues.append((self._line(), f'<{tag}> inside an open <p>: the browser closes the <p> '
                                            'first (and so does this tree)', 'close the <p> yourself; use <div>'))
        if tag == 'li' and self.stack[-1].tag == 'li':
            self.stack.pop()
        el = Element(tag, attrs, self._line(), self.stack[-1])
        self.stack[-1].children.append(el)
        if tag not in VOID:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        el = Element(tag, attrs, self._line(), self.stack[-1])
        el.self_closed = True
        self.stack[-1].children.append(el)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        for k in range(len(self.stack) - 1, 0, -1):
            if self.stack[k].tag == tag:
                del self.stack[k:]
                return
        self.doc.issues.append((self._line(), f'stray </{tag}>', 'remove it'))

    def handle_data(self, data):
        t = Text(data, self._line())
        t.parent = self.stack[-1]
        self.stack[-1].children.append(t)

    def handle_comment(self, data):
        c = Comment(data, self._line())
        c.parent = self.stack[-1]
        self.stack[-1].children.append(c)


def parse(text):
    b = _Builder()
    b.feed(text)
    b.close()
    if len(b.stack) > 1:
        for el in b.stack[1:]:
            if el.tag not in ('html', 'body', 'head'):
                b.doc.issues.append((el.line, f'<{el.tag}> is never closed', f'close it with </{el.tag}>'))
    return b.doc


def find(node, tag):
    for c in node.children:
        if isinstance(c, Element):
            if c.tag == tag:
                return c
            r = find(c, tag)
            if r is not None:
                return r
    return None
