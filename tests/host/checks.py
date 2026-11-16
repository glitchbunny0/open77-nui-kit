#!/usr/bin/env python3
"""rmlhost checks: run the host binary given on the command line against the probe documents in this folder and
assert what it prints (check outline and clicks, layout numbers, parity dumps, errors on bad input).

  checks.py HOST [--only CHECK-PREFIX]

Prints "ok <check>" or "FAIL <check>: why" per check; exits 1 when any failed. Needs only the standard library.
"""
import json, os, struct, subprocess, sys, tempfile, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
HOST = os.path.abspath(sys.argv[1])
ONLY = sys.argv[3] if len(sys.argv) > 3 and sys.argv[2] == '--only' else None
CHECKS = []


def check(name):
    def deco(fn):
        CHECKS.append((name, fn))
        return fn
    return deco


class Run:
    def __init__(self, r):
        self.rc, self.err = r.returncode, r.stderr.decode('utf-8', 'replace')
        try:
            self.out = r.stdout.decode('utf-8')   # strict: invalid UTF-8 from the host is a failure
            self.utf8 = True
        except UnicodeDecodeError as e:
            self.out, self.utf8 = r.stdout.decode('utf-8', 'replace'), str(e)


def host(mode, *args, cases, timeout=10):
    """Run the host in this folder. cases: a Python value (sent as json.dumps does by default, ASCII with \\u escapes,
    as the wrappers send it) or str/bytes sent as is."""
    data = cases if isinstance(cases, (str, bytes)) else json.dumps(cases)
    if isinstance(data, str):
        data = data.encode('utf-8')
    return Run(subprocess.run([HOST, mode, *args], input=data, capture_output=True, timeout=timeout, cwd=HERE))


WORK = tempfile.mkdtemp(prefix='host-checks-', dir=os.environ.get('NUIKIT_TMP'))


def doc(name, body, rcss='', head=''):
    """Write a probe document (and its sheet) into the work dir; return its path."""
    path = os.path.join(WORK, name + '.rml')
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'<rml><head>{head}<style>body {{ font-family: probe; font-size: 10dp; }} {rcss}</style></head>'
                f'<body data-model="m">{body}</body></rml>')
    return path


PROBE_FONT = {'ascent': 800, 'descent': 200, 'def': 500, 'adv': {}}


def fonts(faces=None, name='fonts'):
    """Write a fonts.json (default: one face, family "probe" weight 400, every glyph 500/1000 em); return its path."""
    path = os.path.join(WORK, name + '.json')
    with open(path, 'w', encoding='utf-8') as f:
        json.dump({'probe|400': PROBE_FONT} if faces is None else faces, f)
    return path


def png(rel, w, h):
    """Write a w x h PNG under the work dir; return its path."""
    path = os.path.join(WORK, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    chunk = lambda t, d: struct.pack('>I', len(d)) + t + d + struct.pack('>I', zlib.crc32(t + d))
    raw = b''.join(b'\0' + b'\xff\0\0' * w for _ in range(h))
    with open(path, 'wb') as f:
        f.write(b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', w, h, 8, 2, 0, 0, 0))
                + chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b''))
    return path


def parity(rml, model, steps=(), events=()):
    """One parity case: the dumps (one per step) of the document <body data-model="m">rml</body>."""
    r = host('parity', cases=[{'name': 'p', 'rml': f'<body data-model="m">{rml}</body>', 'model': model,
                                'events': list(events), 'steps': list(steps)}])
    expect(r.rc == 0, f'parity rc {r.rc}: {r.err[:300]}')
    return json.loads(r.out)[0]


def expect(cond, msg):
    if not cond:
        raise AssertionError(msg)


# ---- the JSON reader
@check('json: an emoji (a surrogate pair) arrives as one 4-byte UTF-8 character')
def _():
    r = host('check', doc('emoji', '<p>{{s}}</p>'), 'm', cases=[{'name': 'e', 'model': {'s': 'Loot \U0001F600 ready'}}])
    expect(r.utf8 is True, f'the host printed invalid UTF-8: {r.utf8}')
    expect('"Loot \U0001F600 ready"' in r.out, 'outline: ' + r.out[:300])


@check('json: the escapes r, b, f and slash decode')
def _():
    r = host('parity', cases='[{"name":"p","rml":"<body data-model=\\"m\\"><p data-attr-title=\\"s\\">x</p></body>",'
                             '"model":{"s":"a\\rb\\bc\\fd\\/e"}}]')
    expect(r.rc == 0, f'rc {r.rc}: {r.err[:200]}')
    title = json.loads(r.out)[0]['snapshots'][0]['dom']['children'][0]['attrs'].get('title')
    expect(title == 'a\rb\bc\fd/e', f'title {title!r}')


def bad_json(text, msg):
    r = host('check', doc('plain', '<p>x</p>'), 'm', cases=text, timeout=5)
    expect(r.rc == 2, f'{text[:40]!r}: rc {r.rc}, stderr {r.err[:200]!r}')
    expect(msg in r.err and 'offset' in r.err, f'{text[:40]!r}: stderr {r.err[:200]!r}, want {msg!r} with an offset')


@check('json: an unterminated string is an error')
def _():
    bad_json('[{"name":"abc', 'unterminated string')


@check('json: a truncated or bad u-escape is an error')
def _():
    bad_json('[{"name":"\\u1', 'truncated \\u escape')
    bad_json('[{"name":"\\uZZZZ"}]', 'bad \\u escape')


@check('json: a missing comma or colon is an error')
def _():
    bad_json('[{"name":"a" "model":{}}]', "expected ',' or '}'")
    bad_json('[{"name" "a"}]', "expected ':'")


@check('json: deep nesting is an error, not a stack overflow')
def _():
    bad_json('[' * 50000, 'nested deeper')


@check('json: a bare word is an error')
def _():
    bad_json('[{"name":"a","model":undefined}]', 'unexpected character')


@check('json: an integer past int64 is kept as a double')
def _():
    r = host('check', doc('big', '<p>{{n}}</p>'), 'm', cases='[{"name":"b","model":{"n":123456789012345678901234567890}}]')
    expect(r.rc == 0, f'rc {r.rc}: {r.err[:200]}')
    expect('9223372036854775807' not in r.out and '"123456789012345' in r.out, 'outline: ' + r.out[:300])


# ---- case shapes: an error naming the field, never a crash
def bad_case(mode, args, cases, msg):
    r = host(mode, *args, cases=cases, timeout=4)
    expect(r.rc == 2 and msg in r.err, f'rc {r.rc}, stderr {r.err[:300]!r}, want {msg!r}')


@check('input: a click without sel or event is an error')
def _():
    d = doc('plain', '<p>x</p>')
    bad_case('check', [d, 'm'], [{'name': 'a', 'clicks': [{'event': 'x'}]}], 'clicks[0].sel must be a string')
    bad_case('check', [d, 'm'], [{'name': 'a', 'clicks': [{'sel': 'p'}]}], 'clicks[0].event must be a string')


@check('input: click args that are not scalars are an error')
def _():
    bad_case('check', [doc('plain', '<p>x</p>'), 'm'], [{'name': 'a', 'clicks': [{'sel': 'p', 'event': 'x', 'args': [[1]]}]}],
             'clicks[0].args must hold strings, numbers or booleans')


@check('input: a parity step without its fields is an error')
def _():
    case = {'name': 'a', 'rml': '<body data-model="m"></body>', 'model': {}}
    bad_case('parity', [], [dict(case, steps=[{'set': 'x'}])], '"set" needs a path string and a "value"')
    bad_case('parity', [], [dict(case, steps=[{'event': 'x'}])], '"event" needs an element id and a "type"')


@check('input: a parity case without a model is an error')
def _():
    bad_case('parity', [], [{'name': 'a', 'rml': '<body data-model="m"></body>'}], '"model" is missing')


@check('input: a place that is not [left, top] is an error')
def _():
    bad_case('layout', [doc('plain', '<p id="t">x</p>'), 'm', fonts()], [{'name': 'a', 'place': {'#t': [5]}}],
             'place["#t"] must be [left, top]')


@check('input: a bad set path is an error, not a hang or a crash')
def _():
    for path in ['items[1', 'items[-1]', 'items[x]']:
        bad_case('parity', [], [{'name': 'a', 'rml': '<body data-model="m"></body>', 'model': {'items': [1, 2]},
                                 'steps': [{'set': path, 'value': 3}]}], 'set path "' + path + '"')


@check('input: a model bound twice is an error')
def _():
    bad_case('check', [doc('plain', '<p>x</p>'), 'm'], [{'name': 'a', 'model': {}, 'models': {'m': {}}}], 'bound twice')


@check('input: a fonts.json without faces is an error')
def _():
    bad_case('layout', [doc('plain', '<p>x</p>'), 'm', fonts({}, 'empty')], [{'name': 'a', 'model': {}}], 'no font faces')


# ---- the dynamic data model says what RmlUi's own data variables say
@check('model: assigning to an array warns as RmlUi does')
def _():
    r = parity('<div id="b" data-event-click="rows = 3">x</div>', {'rows': [1]}, steps=[{'event': 'b', 'type': 'click'}])
    w = r['snapshots'][1]['warnings']
    expect('Values can only be assigned to scalar data types.' in w, f'warnings {w}')


@check('model: a member of an empty table reads as a missing struct member')
def _():
    r = parity('<p>{{cfg.title}}</p>', {'cfg': {}})
    w = r['snapshots'][0]['warnings']
    expect(any('Member title not found in data struct.' in x for x in w), f'warnings {w}')


# ---- clicks
def clicks(body, model, events, clicks, rcss='', name='clicks'):
    rcss = 'div { display: block; width: 100dp; height: 20dp; } ' + rcss
    r = host('check', doc(name, body, rcss), 'm', cases=[{'name': 'c', 'model': model, 'events': events, 'clicks': clicks}])
    expect(r.rc == 0, f'rc {r.rc}: {r.err[:300]}')
    return [l for l in r.out.splitlines() if l.startswith('CLICK')]


@check('click: number and boolean args compare as RmlUi prints them')
def _():
    body = ('<div id="a" data-event-click="pick(2)">a</div><div id="b" data-event-click="pick(r.id)">b</div>'
            '<div id="c" data-event-click="tog(true)">c</div><div id="d" data-event-click="pick()">d</div>'
            '<div id="e" data-event-click="qty(1.5)">e</div>')
    got = clicks(body, {'r': {'id': 2}}, ['pick', 'tog', 'qty'],
                 [{'sel': '#a', 'event': 'pick', 'args': [2]}, {'sel': '#b', 'event': 'pick', 'args': [2]},
                  {'sel': '#c', 'event': 'tog', 'args': [True]}, {'sel': '#d', 'event': 'pick', 'args': [2]},
                  {'sel': '#e', 'event': 'qty', 'args': [1.5]}])
    want = ['ok', 'ok', 'ok', 'FAIL', 'ok']
    expect([l.split()[1] for l in got] == want, f'{got}')
    expect('#d -> pick() (want pick(2))' in got[3], got[3])


@check('click: an event an ancestor also fires makes the click fail')
def _():
    body = '<div id="row" data-event-click="pick(1)"><div id="buy" data-event-click="buy(2)">buy</div></div>'
    got = clicks(body, {}, ['pick', 'buy'], [{'sel': '#buy', 'event': 'buy', 'args': [2]},
                                             {'sel': '#buy', 'event': 'pick', 'args': [1]}])
    expect(len(got) == 2 and all(l.startswith('CLICK FAIL #buy -> buy(2), then pick(1)') for l in got), f'{got}')


HIT_RCSS = ('body { width: 100%; height: 100%; } div { display: block; width: 100dp; height: 20dp; }'
            '#cover { position: absolute; left: 0; top: 180dp; width: 400dp; height: 100dp; z-index: 10; }')


def hit(body, sel, rcss=''):
    got = clicks(body + '<div id="cover"></div>', {}, ['go'], [{'sel': sel, 'event': 'go', 'args': [1]}],
                 HIT_RCSS + rcss, name='hit')
    expect(len(got) == 1, f'{got}')
    return got[0]


@check('click: a press on a child of the target reaches the target')
def _():
    got = hit('<div id="t" data-event-click="go(1)"><div id="c">x</div></div>', '#t')
    expect(got == 'CLICK ok   #t -> go(1) (want go(1))', got)


@check('click: an element with pointer-events none is not hit')
def _():
    got = hit('<div id="t" data-event-click="go(1)">x</div>', '#t', '#t { pointer-events: none; }')
    expect(got == 'CLICK FAIL #t -> covered by body at 50,10 (want go(1))', got)


@check('click: an element under an overlay is not hit')
def _():
    got = hit('<div id="t" data-event-click="go(1)" style="position: absolute; top: 200dp;">x</div>', '#t')
    expect(got == 'CLICK FAIL #t -> covered by div#cover at 50,210 (want go(1))', got)


@check('click: a zero-size element is not hit')
def _():
    got = hit('<div id="t" data-event-click="go(1)"></div>', '#t', '#t { width: 0; }')
    expect(got.startswith('CLICK FAIL #t -> zero-size box (0x20)'), got)


@check('click: an element outside the context is not hit')
def _():
    got = hit('<div id="t" data-event-click="go(1)" style="position: absolute; left: 3000dp;">x</div>', '#t')
    expect(got.startswith('CLICK FAIL #t -> off screen at 3050,'), got)


@check('click: events the pointer calls on its way there are not the click')
def _():
    got = hit('<div id="t" data-event-mouseover="go(0)" data-event-click="go(1)">x</div>', '#t')
    expect(got == 'CLICK ok   #t -> go(1) (want go(1))', got)


@check('click: a box sized by its text alone can be clicked')
def _():
    got = hit('<p id="t" data-event-click="go(1)" style="display: inline-block;">BUY</p>', '#t', 'p { width: auto; }')
    expect(got == 'CLICK ok   #t -> go(1) (want go(1))', got)


# ---- parity
@check('parity: boolean and string event params reach the expression as such')
def _():
    r = parity('<div id="b" data-event-mousedown="pick(ev.flag, ev.name, ev.x)">x</div>', {},
               steps=[{'event': 'b', 'type': 'mousedown', 'params': {'flag': True, 'name': 'n', 'x': 1.5}}], events=['pick'])
    calls = r['snapshots'][1]['calls']
    expect(calls == ['pick(1,n,1.5)'], f'calls {calls}')


# ---- Open77's additions, registered: parsed and checked like RmlUi's own properties
def decl_warnings(decl):
    r = host('check', doc('decl', '<div id="e"></div>', 'div { display: block; width: 10dp; height: 10dp; } #e { %s }' % decl),
             'm', cases=[{'name': 'c', 'model': {}}])
    expect(r.rc == 0, f'rc {r.rc}: {r.err[:200]}')
    return [l for l in r.out.splitlines() if l.startswith('WARN')]


def all_parse(decls):
    bad = {d: w for d in decls if (w := decl_warnings(d))}
    expect(not bad, f'warnings for valid declarations: {bad}')


def none_parse(decls):
    good = [d for d in decls if not decl_warnings(d)]
    expect(not good, f'no warning for: {good}')


@check('open77: the paint properties parse their documented values')
def _():
    all_parse(['fill: #22d8e233', 'fill: none', 'fill: currentColor', 'stroke: #22d8e2', 'stroke-width: 1.5dp',
               'stroke-width: 2', 'stroke-linejoin: round', 'stroke-linecap: square', 'stroke-dasharray: 8 4',
               'stroke-dasharray: 8, 4dp', 'stroke-dashoffset: 3', 'trim-start: 0', 'trim-end: 0.65', 'trim-offset: 0.5'])


@check('open77: a bad paint value is an error')
def _():
    none_parse(['fill: #GGGGGG', 'stroke: nope', 'stroke-width: 2pxx', 'stroke-linejoin: rund', 'stroke-dasharray: 8 x',
                'trim-end: high'])


@check('open77: the filters take their documented arguments')
def _():
    all_parse(['filter: glow(6dp #22d8e2 1.2)', 'filter: glow(2dp)', 'filter: chromatic(2) scanlines(0.25 3)',
               'filter: scanlines(0.35 3 1 0.2)', 'filter: distort(3 4 2) brightness(1.2)', 'filter: pixelate(4)',
               'backdrop-filter: blur(14dp) glow(5dp #5EF6FF 0.9)'])


@check('open77: a filter with bad arguments is an error')
def _():
    none_parse(['filter: scanlines(0.35 3dp)', 'filter: glow(1.2 #fff 6dp)', 'filter: glow(6dp #fff 1 2)',
                'filter: blur(4pz) glow(2dp #fff 1)', 'filter: glo(2dp)'])


@check('open77: fx() takes an effect name, numbers and a colour')
def _():
    all_parse(['decorator: fx(holo 0.6 1 0 0 #22d8e2)', 'decorator: fx(chamfer-solid 6 0 0 0 #22d8e2)',
               'decorator: fx(border-flow 1.5 2 0 0 #22d8e2) padding-box', 'decorator: fx(pulse 1)'])


@check('open77: fx() without an effect name or with units is an error')
def _():
    none_parse(['decorator: fx(1 2 3)', 'decorator: fx(holo 1px)', 'decorator: fx(holo 1 2 3 4 #fff 5)',
                'decorator: linear-gradient(90dge, #f00, #00f), fx(border-flow 1 2)'])


# ---- layout mode
def layout(body, rcss='', cases=None, faces=None, name='lay'):
    """The layout of a probe document: a list (one per case) of {name, els, ...}."""
    r = host('layout', doc(name, body, rcss), 'm', fonts(faces), cases=cases or [{'name': 'c', 'model': {}}])
    expect(r.rc == 0, f'layout rc {r.rc}: {r.err[:300]}')
    return json.loads(r.out)


def els(body, rcss='', **kw):
    return layout(body, rcss, **kw)[0]['els']


def texts(es):
    return [e['text'] for e in es if 'text' in e]


def ids(es):
    return [e['id'] for e in es if 'tag' in e and e['id']]


@check('layout: a hidden element drops its text and its whole subtree')
def _():
    es = els('<div id="h">HIDDEN<div id="hc">child</div><div id="vis">shown?</div></div><div id="ok">OK</div>',
             '#h { visibility: hidden; } #vis { visibility: visible; } div { display: block; }')
    expect(texts(es) == ['OK'] and ids(es) == ['ok'], f'texts {texts(es)}, boxes {ids(es)}')


CLIP_RCSS = ('div { display: block; } #c { position: absolute; left: 20dp; top: 30dp; width: 100dp; height: 50dp; '
             'border: 10dp #fff; overflow: hidden; } #in { width: 300dp; height: 300dp; } '
             '#s { width: 100dp; height: 50dp; overflow: hidden; margin-top: 200dp; } #sin { width: 300dp; height: 300dp; } '
             '#ab { position: absolute; left: 500dp; top: 500dp; width: 10dp; height: 10dp; } '
             '#none { clip: none; width: 5dp; height: 5dp; } '
             '#far { position: absolute; left: 2200dp; top: 1200dp; width: 10dp; height: 10dp; }')
CLIP_BODY = ('<div id="c"><div id="in">text in</div><div id="none"></div></div>'
             '<div id="s"><div id="sin"></div><div id="ab"></div></div><div id="far"></div>')


def clips():
    es = els(CLIP_BODY, CLIP_RCSS, cases=[{'name': 'c', 'model': {}, 'size': [2560, 1440]}], name='clip')
    out = {e.get('id') or e.get('text'): e['clip'] for e in es}
    return out


@check('layout: overflow clips to the padding box of the clipping ancestor')
def _():
    c = clips()
    expect(c['in'] == [30, 40, 130, 90] and c['text in'] == [30, 40, 130, 90] and c['sin'] == [0, 200, 100, 250], f'{c}')


@check('layout: the clip follows the offset-parent chain (an absolute child escapes; clip: none)')
def _():
    c = clips()
    expect(c['ab'] is None and c['none'] is None, f'{c}')


@check('layout: nothing clips an unclipped box, whatever the context size')
def _():
    c = clips()
    expect(c['far'] is None and c['c'] is None, f'{c}')


@check('layout: text comes as RmlUi draws it, text-transform applied, with no flag to apply it again')
def _():
    es = els('<p id="u">stra\u00dfe caf\u00e9</p>', '#u { text-transform: uppercase; }')
    run = next(e for e in es if 'text' in e)
    expect(run['text'] == 'STRA\u00dfE CAF\u00e9' and 'upper' not in run, f'{run}')


@check('layout: each case lists its own warnings')
def _():
    out = layout('<p>{{x}}</p>', cases=[{'name': 'a', 'model': {}}, {'name': 'b', 'model': {'x': 1}}], name='warn')
    wa, wb = out[0].get('warnings'), out[1].get('warnings')
    expect(any("'x'" in w for w in wa or []) and wb == [], f'a: {wa}, b: {wb}')


@check('check: a stylesheet warning shows in every case')
def _():
    with open(os.path.join(WORK, 'sheetwarn.rcss'), 'w') as f:
        f.write('p { colr: red; }')
    r = host('check', doc('sheetwarn', '<p>x</p>', head='<link type="text/rcss" href="sheetwarn.rcss"/>'), 'm',
             cases=[{'name': 'one', 'model': {}}, {'name': 'two', 'model': {}}])
    per = [l for l in r.out.split('=== case ') if l]
    expect(len(per) == 2 and all('colr' in p for p in per), r.out[-400:])


# ---- fonts: a face is chosen as RmlUi's font engine chooses one
TWO_WEIGHTS = {'probe|400': PROBE_FONT, 'probe|600': dict(PROBE_FONT, **{'def': 600})}


def word_box(rcss, faces):
    out = layout('<span id="w">aaaa</span>', 'span { display: inline-block; } ' + rcss, faces=faces, name='font')[0]
    return next(e for e in out['els'] if e.get('id') == 'w'), out['warnings']


@check('font: an unknown family gets no face and no text, as in RmlUi')
def _():
    out = layout('<p id="t">hello</p>', '#t { font-family: nope; }', name='nofam')[0]
    expect(not texts(out['els']), f'text runs {texts(out["els"])}')
    expect(any('No font face defined' in w for w in out['warnings']), f'warnings {out["warnings"]}')


@check('font: a missing weight takes the nearest loaded face, with a warning')
def _():
    box, warn = word_box('#w { font-weight: 700; }', TWO_WEIGHTS)
    expect(box['w'] == 24.0, f'width {box["w"]} (4 glyphs of 0.6 em at 10 = 24 from weight 600)')
    expect(any('Font face substituted' in w and 'weight 700' in w for w in warn), f'warnings {warn}')


@check('font: italic text needs an italic face')
def _():
    box, warn = word_box('#w { font-style: italic; }', TWO_WEIGHTS)
    expect(box['w'] == 0.0 and any('No font face defined' in w for w in warn), f'box {box["w"]}, warnings {warn}')
    box, warn = word_box('#w { font-style: italic; }', dict(TWO_WEIGHTS, **{'probe|400|i': dict(PROBE_FONT, **{'def': 700})}))
    expect(box['w'] == 28.0 and not warn, f'with an italic face: width {box["w"]}, warnings {warn}')


# ---- text widths as RmlUi's font engine sums them
def span_width(text, rcss='', face=None, model=None):
    faces = {'probe|400': dict(PROBE_FONT, **(face or {}))}
    out = layout(f'<span id="w">{text}</span>', 'span { display: inline-block; } ' + rcss, faces=faces, name='width',
                 cases=[{'name': 'c', 'model': model or {}}])[0]
    return next(e for e in out['els'] if e.get('id') == 'w')['w']


@check('width: each glyph adds its whole-pixel advance')
def _():
    w = span_width('aaa', face={'adv': {'97': 370}})
    expect(w == 12.0, f'width {w}, want 3 x round(3.7) = 12')


@check('width: letter-spacing adds its whole pixels per glyph')
def _():
    w = span_width('aaaa', '#w { letter-spacing: 1.5dp; }')
    expect(w == 24.0, f'width {w}, want 4 x (5 + 1) = 24')


@check('width: a glyph the font lacks adds nothing')
def _():
    w = span_width('a\u2190a', face={'adv': {'8592': None}})
    expect(w == 10.0, f'width {w}, want 10 (the arrow is not in the font)')


@check('width: a control character adds nothing')
def _():
    w = span_width('{{s}}', model={'s': 'a\u0001b'})
    expect(w == 10.0, f'width {w}, want 10')


@check('width: kerning pairs from fonts.json apply unless font-kerning is none')
def _():
    face = {'kern': {'97,98': -100}}
    w, w0 = span_width('ab', face=face), span_width('ab', '#w { font-kerning: none; }', face=face)
    expect((w, w0) == (9.0, 10.0), f'widths {w}, {w0}, want 9 kerned, 10 with font-kerning: none')


@check('width: an emoji counts as one glyph')
def _():
    w = span_width('a\U0001F600b')
    expect(w == 15.0, f'width {w}, want 15')


@check('layout: a text run carries its measured width')
def _():
    es = els('<p>abc</p>')
    run = next(e for e in es if 'text' in e)
    expect(run['w'] == 15, f'{run}')


def warns(r):
    return [l for l in r.out.splitlines() if l.startswith('WARN')]


def check_doc(path, model=None):
    r = host('check', path, 'm', cases=[{'name': 'c', 'model': model or {}}])
    expect(r.rc == 0, f'rc {r.rc}: {r.err[:300]}')
    return r


# ---- classes in a stable order
CLS_BODY = '<div id="x" class="zz" data-class-aa="on">x</div>'


@check('classes: the check outline sorts them')
def _():
    r = check_doc(doc('cls', CLS_BODY), {'on': True})
    expect('div#x.aa.zz ' in r.out, r.out[:300])


@check('classes: layout sorts them')
def _():
    es = els(CLS_BODY, cases=[{'name': 'c', 'model': {'on': True}}], name='cls')
    expect(next(e for e in es if e.get('id') == 'x')['cls'] == 'aa zz', f'{es}')


# ---- the numbers of a probe document (fonts.json face: ascent 0.8 em, descent 0.2 em, every glyph 0.5 em)
@check('layout: a probe document lays out to known numbers')
def _():
    es = els('<div id="a"></div><div id="t">abc</div><div id="row"><div id="r1"></div><div id="r2"></div></div>',
             'div { display: block; } #a { position: absolute; left: 20dp; top: 30dp; width: 200dp; height: 100dp; '
             'padding: 10dp; border: 5dp #ffffff; } #t { position: absolute; left: 0; top: 200dp; font-size: 20dp; '
             'line-height: 30dp; } #row { position: absolute; left: 300dp; top: 0; display: flex; width: 100dp; } '
             '#r1 { flex: 1; height: 10dp; } #r2 { width: 30dp; height: 20dp; }', name='probe')
    by = {e.get('id'): e for e in es if 'tag' in e}
    run = next(e for e in es if e.get('text') == 'abc')
    got = {'a': [by['a'][k] for k in ('x', 'y', 'w', 'h', 'bt')], 'text': [run[k] for k in ('x', 'y', 'w', 'size')],
           't': by['t']['h'], 'r1': [by['r1'][k] for k in ('x', 'w')], 'r2': [by['r2'][k] for k in ('x', 'h')]}
    want = {'a': [20, 30, 230, 130, 5], 'text': [0, 221, 30, 20], 't': 30, 'r1': [300, 70], 'r2': [370, 20]}
    expect(got == want, f'got {got}, want {want}')


# ---- images
@check('image: a missing img src is reported')
def _():
    w = warns(check_doc(doc('img1', '<img src="nope.png"/>')))
    expect(any('Could not load texture' in x and 'nope.png' in x for x in w), f'{w}')


@check('image: a missing decorator image is reported')
def _():
    w = warns(check_doc(doc('img2', '<div id="d">x</div>', '#d { width: 10dp; height: 10dp; decorator: image(gone.png); }')))
    expect(any('Could not load texture' in x and 'gone.png' in x for x in w), f'{w}')


@check('image: an image next to the document or under the resource root is found')
def _():
    png('res/img/a.png', 4, 4)
    os.makedirs(os.path.join(WORK, 'res', 'ui'), exist_ok=True)
    path = os.path.join(WORK, 'res', 'ui', 'found.rml')
    with open(path, 'w') as f:
        f.write('<rml><head><style>#d { width: 10dp; height: 10dp; decorator: image(/img/a.png); }</style></head>'
                '<body data-model="m"><img src="../img/a.png"/><div id="d"/></body></rml>')
    w = warns(check_doc(path))
    expect(not any('texture' in x for x in w), f'{w}')


@check('image: layout lists a missing image in the case warnings')
def _():
    out = layout('<div id="d">x</div>', '#d { width: 10dp; height: 10dp; decorator: image(gone.png); }', name='imglay')[0]
    expect(any('Could not load texture' in w and 'gone.png' in w for w in out['warnings']), f'{out["warnings"]}')


@check('image: drawing raises no noise of its own')
def _():
    w = warns(check_doc(doc('draw', '<div id="d">x</div><div id="z"></div>', '#z { box-shadow: #000 0dp 0dp 2dp; } '
                              '#d { width: 50dp; height: 20dp; '
                              'decorator: linear-gradient(90deg, #fff, #000), radial-gradient(circle, #f00, #00f); '
                              'box-shadow: #000 0dp 0dp 2dp, #fff 1dp 1dp inset; filter: blur(2dp) glow(2dp #fff 1); '
                              'backdrop-filter: blur(4dp); mask-image: linear-gradient(#000, #0000); }')))
    expect(not [x for x in w if 'font face' not in x], f'{w}')


@check('image: an img takes the PNG natural size')
def _():
    png('nat/n.png', 40, 30)
    r = check_doc(doc('natural', '<img id="i" src="nat/n.png"/>'))
    line = next((l for l in r.out.splitlines() if l.strip().startswith('img#i')), '')
    expect(' 40x30' in line, f'outline line {line!r}')


# ---- files under a folder named outside ASCII: Windows opens such a path only through its wide API (no Western ANSI
# code page holds the д); elsewhere a narrow path is UTF-8 already
@check('files: a document, its sheet, an image and fonts.json under a non-ASCII folder are read')
def _():
    d = os.path.join(WORK, 'Jürgen', 'ресурс')
    png(os.path.join('Jürgen', 'ресурс', 'img', 'n.png'), 40, 30)
    with open(os.path.join(d, 'ui.rcss'), 'w', encoding='utf-8') as f:
        f.write('#box { display: block; width: 33dp; height: 7dp; }')
    path = os.path.join(d, 'ui.rml')
    with open(path, 'w', encoding='utf-8') as f:
        f.write('<rml><head><link type="text/rcss" href="ui.rcss"/></head>'
                '<body data-model="m"><div id="box"/><img id="i" src="img/n.png"/></body></rml>')
    r = check_doc(path)
    box = next((l for l in r.out.splitlines() if l.strip().startswith('div#box')), '')
    img = next((l for l in r.out.splitlines() if l.strip().startswith('img#i')), '')
    expect(' 33x7' in box and ' 40x30' in img and not warns(r), f'{box!r} {img!r} {warns(r)}')
    fj = os.path.join(d, 'fonts.json')
    with open(fj, 'w', encoding='utf-8') as f:
        json.dump({'probe|400': PROBE_FONT}, f)
    r = host('layout', path, 'm', fj, cases=[{'name': 'c', 'model': {}}])
    expect(r.rc == 0 and json.loads(r.out)[0]['els'], f'layout rc {r.rc}: {r.err[:200]}')


@check('files: ../ in an image path climbs from the folder of a document given with native separators')
def _():
    png(os.path.join('sep', 'img', 'u.png'), 12, 9)
    path = os.path.join(WORK, 'sep', 'ui', 'deep', 'doc.rml')   # \ between the folders on Windows
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w', encoding='utf-8') as f:
        f.write('<rml><body data-model="m"><img id="i" src="../../img/u.png"/></body></rml>')
    r = check_doc(path)
    img = next((l for l in r.out.splitlines() if l.strip().startswith('img#i')), '')
    expect(' 12x9' in img and not warns(r), f'{img!r} {warns(r)}')


# ---- check output: one line per item, whatever the input holds
@check('check: a newline in a case name cannot start a line of its own')
def _():
    r = host('check', doc('plain', '<p>x</p>'), 'm', cases=[{'name': 'a\nWARN x1: injected', 'model': {}},
                                                           {'name': 'b\n=== case ghost', 'model': {}}])
    lines = r.out.splitlines()
    expect(not any(l.startswith('WARN x1: injected') or l == '=== case ghost' for l in lines)
           and sum(l.startswith('=== case ') for l in lines) == 2, r.out[:400])


@check('check: warnings keep the order RmlUi logged them in')
def _():
    r = check_doc(doc('expr', '<p>{{ t + }}</p>'), {'t': 1})
    w = [l.split(': ', 1)[1] for l in warns(r) if 'font face' not in l]
    first = next((i for i, x in enumerate(w) if x.startswith('Error in data expression')), None)
    expect(first is not None and w[first + 1].strip() == '" t + "' and w[first + 2].strip() == '^', f'{w}')


def main():
    failed = 0
    for name, fn in CHECKS:
        if ONLY and not name.startswith(ONLY):
            continue
        try:
            fn()
            print('ok ' + name)
        except Exception as e:   # an assertion, a timeout, a crash in the check itself: all red
            failed += 1
            msg = str(e).replace('\n', ' | ')
            print(f'FAIL {name}: {type(e).__name__ + ": " if not isinstance(e, AssertionError) else ""}{msg[:600]}')
    sys.exit(1 if failed else 0)


if __name__ == '__main__':
    main()
