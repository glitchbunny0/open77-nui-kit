#!/usr/bin/env python3
"""rmlhost checks: run the host binary given on the command line against the probe documents in this folder and
assert what it prints (check outline and clicks, layout numbers, parity dumps, errors on bad input).

  checks.py HOST [--only CHECK-PREFIX]

Prints "ok <check>" or "FAIL <check>: why" per check; exits 1 when any failed. Needs only the standard library.
"""
import json, os, subprocess, sys, tempfile

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
