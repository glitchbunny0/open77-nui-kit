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


# a start tag of the key closes open elements of these tags first (the HTML parser's other implied end tags)
IMPLIED_END = {'option': {'option'}, 'optgroup': {'option', 'optgroup'}, 'tr': {'td', 'th', 'tr'},
               'td': {'td', 'th'}, 'th': {'td', 'th'}, 'dt': {'dt', 'dd'}, 'dd': {'dt', 'dd'},
               'rt': {'rt', 'rp'}, 'rp': {'rt', 'rp'}}
for _t in ('thead', 'tbody', 'tfoot'):
    IMPLIED_END[_t] = {'thead', 'tbody', 'tfoot', 'tr', 'td', 'th'}
FOREIGN = {'svg', 'math'}   # inside these, `<x/>` closes the element (XML rules)


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
        while len(self.stack) > 1 and self.stack[-1].tag in IMPLIED_END.get(tag, ()):
            self.stack.pop()
        el = Element(tag, attrs, self._line(), self.stack[-1])
        self.stack[-1].children.append(el)
        if tag not in VOID:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        if tag not in VOID and not any(e.tag in FOREIGN for e in self.stack) and tag not in FOREIGN:
            # HTML ignores the slash on a non-void element: <div/> opens a <div> that the following content goes into
            self.doc.issues.append((self._line(), f'<{tag}/>', f'HTML ignores the slash: the <{tag}> stays open (as in '
                                    f'a browser) and what follows goes inside; write <{tag}></{tag}>'))
            self.handle_starttag(tag, attrs)
            return
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
    _implied(b.doc)
    return b.doc


# what a browser keeps in <head>; any other content there, or after </body>, it moves into the body
HEAD_TAGS = {'title', 'meta', 'link', 'style', 'script', 'noscript', 'base', 'template'}


def _adopt(parent, nodes, at=None):
    for c in nodes:
        c.parent = parent
    if at is None:
        parent.children.extend(nodes)
    else:
        parent.children[at:at] = nodes


def _implied(doc):
    """the tree a browser builds: one <html> holding <head> and <body> (implied when the page leaves them out); content
    outside them (after </body>, after </html>, flow content in <head>) goes into the body, comments keep their place"""
    root = doc.root
    html = next((c for c in root.children if isinstance(c, Element) and c.tag == 'html'), None)
    if html is None:
        first = next((c for c in root.children if isinstance(c, Element)), None)
        html = Element('html', [], first.line if first else 1, root)
        _adopt(html, list(root.children))
        root.children = [html]
    else:
        k = root.children.index(html)
        after = root.children[k + 1:]   # after </html>
        root.children = root.children[:k + 1]
        _adopt(html, after)
    head = next((c for c in html.children if isinstance(c, Element) and c.tag == 'head'), None)
    body = next((c for c in html.children if isinstance(c, Element) and c.tag == 'body'), None)
    if body is None:
        flow = next((c for c in html.children if (isinstance(c, Element) and c not in (head,) and c.tag not in HEAD_TAGS)
                     or (isinstance(c, Text) and c.text.strip())), None)
        body = Element('body', [], flow.line if flow else html.line, html)
        html.children.append(body)
    before, after, seen_body, flowing = [], [], False, False
    keep = []   # stays a child of <html>: head, body, leading head content and comments, whitespace
    for c in html.children:
        if c is body:
            seen_body = True
            keep.append(c)
        elif c is head:
            keep.append(c)
        elif isinstance(c, Text) and not c.text.strip():
            (after if seen_body else before if flowing else keep).append(c)
        elif seen_body:
            after.append(c)
        elif isinstance(c, Comment) and not flowing:
            keep.append(c)
        elif isinstance(c, Element) and c.tag in HEAD_TAGS and not flowing:
            if head is None:
                head = Element('head', [], c.line, html)
                keep.insert(0, head)
            _adopt(head, [c])
        else:
            flowing = True
            before.append(c)
    html.children = keep
    for c in keep:
        c.parent = html
    if head is not None:
        moved = [c for c in head.children if (isinstance(c, Element) and c.tag not in HEAD_TAGS)
                 or (isinstance(c, Text) and c.text.strip())]
        head.children = [c for c in head.children if c not in moved]
        before = moved + before
    while after and isinstance(after[-1], Text) and not after[-1].text.strip():
        after.pop()   # the newline after </body> or </html>
    _adopt(body, before, 0)
    _adopt(body, after)


def find(node, tag):
    for c in node.children:
        if isinstance(c, Element):
            if c.tag == tag:
                return c
            r = find(c, tag)
            if r is not None:
                return r
    return None
