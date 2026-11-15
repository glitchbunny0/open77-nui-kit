#!/usr/bin/env python3
"""lrbind suite (run by tests/lrbind.sh from the kit root, NUIKIT_TMP set).

Checks, one line each:
  golden    rmlhost parity regenerates golden.json from cases.mjs on every run; it must equal the committed file
  order     the cases 8 times over in shuffled order through rmlhost parity: no case may come out differently
  parity    lrbind.js in jsdom against that fresh golden, snapshot by snapshot
  protocol  the page protocol, form controls, mockup mode (protocol.test.mjs)
  lua       lrbind.lua against a fake page (lrbind_lua.lua)
  header    lrbind.js / lrbind.lua carry the MIT notice (the kit's, and RmlUi's for the ported parts of lrbind.js)
  example   examples/side-menu/web/lrbind.js is the kit's file
  sync      bin/lrbind-sync on a scratch resource tree (what a copy is, own comment lines, refresh, check, --help)
  browser   data-rml in a real Chromium: nothing planted in the string runs (skipped without Chromium)
Then every mutant in MUTANTS: a copy of one file with ONE planted bug, run through the one check it names. That check
must go red, and its output must contain the expected text (the failing case or check). A mutant whose pattern no
longer matches exactly once fails too, so the table cannot rot silently.
"""
import concurrent.futures as cf, json, os, random, re, shutil, subprocess, sys

KIT = os.environ.get('NUIKIT') or os.getcwd()
TMP = os.environ['NUIKIT_TMP']
JS = os.path.join(KIT, 'lrbind', 'lrbind.js')
LUA = os.path.join(KIT, 'lrbind', 'lrbind.lua')
GOLDEN = os.path.join(KIT, 'lrbind', 'tests', 'parity', 'golden.json')
FRESH = os.path.join(TMP, 'golden.json')
SOURCES = {'lrbind.js': (JS, 'js'), 'lrbind.lua': (LUA, 'lua'), 'golden.json': (GOLDEN, 'golden')}
HOST = None    # rmlhost, built by main()
CHECKS = {}
MUTANTS = []   # (what, file, old, new, check, expected text in the red output)


def sh(cmd, cwd=KIT, env=None, stdin=None, timeout=300):
    e = dict(os.environ, **(env or {}))
    r = subprocess.run(cmd, cwd=cwd, env=e, input=stdin, capture_output=True, timeout=timeout)
    return r.returncode, r.stdout.decode('utf-8', 'replace') + r.stderr.decode('utf-8', 'replace')


def result(rc, out):
    out = out.strip()
    return rc == 0, out if rc else out.splitlines()[-1]


# ==== golden: regenerated through real RmlUi on every run (main() writes FRESH), compared with the committed file

def check_golden(golden=GOLDEN):
    with open(FRESH, 'rb') as f:
        fresh = f.read()
    with open(golden, 'rb') as f:
        committed = f.read()
    if fresh == committed:
        return True, f'{len(json.loads(fresh))} cases regenerated through rmlhost parity, identical to golden.json'
    a = {c['name']: c for c in json.loads(fresh)}
    b = {c['name']: c for c in json.loads(committed)}
    diff = sorted(n for n in set(a) | set(b) if a.get(n) != b.get(n))
    return False, 'FAIL golden.json is not what RmlUi gives now (run bin/lrbind-parity --regen): ' + '; '.join(diff[:8])


CHECKS['golden'] = check_golden
MUTANTS += [
    ('golden.json edited by hand', 'golden.json', '"calls":[]', '"calls":["x()"]', 'golden', 'FAIL golden'),
]

# ==== order: RmlUi updates the views of one depth in address order, so a case whose outcome hangs on that order gets a
# golden that flips when cases are added before it. One rmlhost run with the cases 8 times over, each round shuffled
# (fixed seeds, so the probe is the same every run): every case must come out the same every time.
CASES = os.path.join(KIT, 'lrbind', 'tests', 'parity', 'cases.mjs')
SOURCES['cases.mjs'] = (CASES, 'cases')


def host_parity(cases_json):
    r = subprocess.run([HOST, 'parity'], input=cases_json.encode(), capture_output=True)
    if r.returncode:
        raise RuntimeError('rmlhost parity failed: ' + r.stderr.decode()[-400:])
    return r.stdout


def check_order(cases=CASES):
    rc, out = sh(['node', 'lrbind/tests/parity/parity.test.mjs', '--cases', cases, '--emit-cases'])
    if rc:
        return False, 'FAIL order: cannot read the cases: ' + out[-400:]
    listed, rounds = json.loads(out), []
    for seed in range(8):
        order = listed[:]
        random.Random(seed).shuffle(order)
        rounds += order
    seen = {}
    for c in json.loads(host_parity(json.dumps(rounds))):
        seen.setdefault(c['name'], set()).add(re.sub(r'#root#c\d+', '', json.dumps(c, sort_keys=True)))
    flips = [n for n, outs in seen.items() if len(outs) > 1]
    return not flips, (f'{len(seen)} cases give the same snapshots at 8 shuffled positions each' if not flips else
                       'FAIL order: RmlUi gives these cases other snapshots in another case order (views of one depth '
                       'run in address order; rewrite them): ' + '; '.join(flips))


CHECKS['order'] = check_order
MUTANTS += [
    ('a case whose outcome hangs on view order', 'cases.mjs', 'value="x" data-checked="c"/>', 'value="x" data-checked="b"/>',
     'order', 'checked: radio bound to a bool'),
]

# ==== parity, protocol, lua: the three test files, run on the file under test


def check_parity(js=JS):
    return result(*sh(['node', 'lrbind/tests/parity/parity.test.mjs', '--golden', FRESH], env={'LRBIND_SHIM': js}))


def check_protocol(js=JS):
    return result(*sh(['node', 'lrbind/tests/protocol.test.mjs'], env={'LRBIND_SHIM': js}))


def check_lua(lua=LUA):
    return result(*sh(['lua5.4', 'tests/lrbind_lua.lua'], cwd=os.path.join(KIT, 'lrbind'), env={'LRBIND_LUA': lua}))


CHECKS.update(parity=check_parity, protocol=check_protocol, lua=check_lua)

# ==== header: the MIT notice travels with every copy (lrbind-sync writes these files into resources that ship)
HEADER = {
    'js': ['// SPDX-License-Identifier: MIT', 'Copyright (c) 2026 glitchbunny0 and contributors',
           'ported from RmlUi', 'Copyright (c) 2008-2014 CodePoint Ltd, Shift Technology Ltd, and contributors',
           'Copyright (c) 2019-2026 The RmlUi Team, and contributors',
           'The above copyright notice and this permission notice shall be included in all copies',
           'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND'],
    'lua': ['-- SPDX-License-Identifier: MIT', 'Copyright (c) 2026 glitchbunny0 and contributors',
            'The above copyright notice and this permission notice shall be included in all copies',
            'THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND'],
}


def check_header(js=JS, lua=LUA):
    missing = []
    for kind, path in (('js', js), ('lua', lua)):
        with open(path, encoding='utf-8') as f:
            text = f.read()
        notice = text[:text.find('\n\n')]   # the first comment block
        if not text.startswith(HEADER[kind][0] + '\n'):
            missing.append(f'{os.path.basename(path)}: first line is not {HEADER[kind][0]!r}')
        missing += [f'{os.path.basename(path)}: no {s!r}' for s in HEADER[kind][1:] if s not in notice]
    return not missing, ('MIT notice on lrbind.js (the kit, and RmlUi for the ported parts) and lrbind.lua (the kit)'
                         if not missing else 'FAIL header: ' + '; '.join(missing))


def check_example(js=JS):
    copy = os.path.join(KIT, 'examples', 'side-menu', 'web', 'lrbind.js')
    with open(copy, 'rb') as a, open(js, 'rb') as b:
        same = a.read() == b.read()
    return same, ('examples/side-menu/web/lrbind.js is lrbind/lrbind.js' if same else
                  'FAIL example: examples/side-menu/web/lrbind.js differs from lrbind/lrbind.js (bin/lrbind-sync refresh examples)')


CHECKS.update(header=check_header, example=check_example)
MUTANTS += [
    ('lrbind.js without the RmlUi copyright', 'lrbind.js', '// Copyright (c) 2019-2026 The RmlUi Team, and contributors\n',
     '', 'header', 'The RmlUi Team'),
    ('lrbind.lua without its SPDX line', 'lrbind.lua', '-- SPDX-License-Identifier: MIT\n', '', 'header', 'first line'),
    ('the kit file changes, the example copy does not', 'lrbind.js', '"use strict";', '"use strict"; ', 'example',
     'FAIL example'),
]

# ==== sync: bin/lrbind-sync on a scratch tree (a copy is every lrbind.js / lrbind.lua; own comment lines may sit above
# the kit's first line; refresh keeps them; the kit's own tree and node_modules are not copies)
SYNC = os.path.join(KIT, 'bin', 'lrbind-sync')
SOURCES['lrbind-sync'] = (SYNC, 'sync')


def check_sync(sync=SYNC):
    root = os.path.join(TMP, 'sync-' + re.sub(r'\W', '_', os.path.basename(sync)))
    shutil.rmtree(root, ignore_errors=True)
    res = os.path.join(root, 'res')
    kit = os.path.join(res, 'lib', 'kit')   # a vendored kit: the tool under test + the kit's two files
    os.makedirs(os.path.join(kit, 'bin'))
    os.makedirs(os.path.join(kit, 'lrbind'))
    shutil.copy(sync, os.path.join(kit, 'bin', 'lrbind-sync'))
    for n in ('lrbind.js', 'lrbind.lua'):
        shutil.copy(os.path.join(KIT, 'lrbind', n), os.path.join(kit, 'lrbind', n))
    with open(JS, 'rb') as f:
        js = f.read()
    with open(LUA, 'rb') as f:
        lua = f.read()
    p = lambda *a: os.path.join(res, *a)
    run = lambda *a: sh([sys.executable, os.path.join(kit, 'bin', 'lrbind-sync')] + list(a), cwd=root)
    last = lambda out: (out.strip().splitlines() or [''])[-1]
    bad = []

    def put(path, data):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'wb') as f:
            f.write(data)

    def get(path):
        with open(path, 'rb') as f:
            return f.read()

    os.makedirs(p('hud'))
    rc, out = run('add', p('hud'))
    if rc or get(p('hud', 'web', 'lrbind.js')) != js or get(p('hud', 'client', 'lrbind.lua')) != lua:
        bad.append('add does not write the kit files, header included')
    rc, out = run('check', res)
    if rc != 0 or '2 copies, 0 stale' not in out:
        bad.append(f'check after add: rc {rc}, {last(out)!r} (want 2 copies, 0 stale: the kit tree under lib/ skipped)')
    own = b'// my resource: hud page\n// (c) someone else\n\n'
    put(p('hud', 'web', 'lrbind.js'), own + js)
    put(p('hud', 'client', 'lrbind.lua'), b'-- vendored by hand\n' + lua)
    rc, out = run('check', res)
    if rc != 0:
        bad.append(f'own comment lines above the header count as stale: {last(out)!r}')
    put(p('hud', 'web', 'lrbind.js'), own + js + b'// drift\n')
    put(p('old', 'web', 'lrbind.js'), js.split(b'\n\n', 1)[1])                 # an old copy without the header
    put(p('misc', 'web', 'js', 'lrbind.js'), js + b' ')                         # a copy in another folder
    put(p('misc', 'web', 'data', 'lrbind.js'), js + b' ')                       # ships under web/** too
    put(p('code', 'web', 'lrbind.js'), b'window.x = 1;\n' + js)                 # code above the header
    put(p('mods', 'node_modules', 'web', 'lrbind.js'), b'not a copy')           # skipped
    put(os.path.join(kit, 'examples', 'web', 'lrbind.js'), b"the kit's own")    # skipped: inside the kit
    rc, out = run('check', res)
    want = sorted(['hud/web/lrbind.js', 'old/web/lrbind.js', 'misc/web/js/lrbind.js', 'misc/web/data/lrbind.js',
                   'code/web/lrbind.js'])
    got = sorted(os.path.relpath(l.split(' ', 1)[1], res) for l in out.splitlines() if l.startswith('stale '))
    if rc != 1 or got != want or '6 copies, 5 stale' not in out:
        bad.append(f'check on drifted copies: rc {rc}, stale {got} (want {want}), {last(out)!r}')
    rc, out = run('refresh', res)
    if rc or '5 refreshed' not in out:
        bad.append(f'refresh: rc {rc}, {last(out)!r}')
    if get(p('hud', 'web', 'lrbind.js')) != own + js:
        bad.append("refresh does not keep the copy's own comment lines above the header")
    if get(p('code', 'web', 'lrbind.js')) != js or get(p('old', 'web', 'lrbind.js')) != js:
        bad.append('refresh does not write the whole kit file over a copy with code above it or without the header')
    if get(p('misc', 'web', 'js', 'lrbind.js')) != js or get(p('misc', 'web', 'data', 'lrbind.js')) != js:
        bad.append('refresh misses a copy outside <res>/web/')
    if get(p('mods', 'node_modules', 'web', 'lrbind.js')) != b'not a copy' or \
            get(os.path.join(kit, 'examples', 'web', 'lrbind.js')) != b"the kit's own":
        bad.append("refresh touched node_modules or the kit's own tree")
    rc, out = run('check', res)
    if rc != 0:
        bad.append(f'check after refresh: {last(out)!r}')
    rc, out = run('--help')
    if rc != 0 or 'A copy is every file named' not in out:
        bad.append(f'--help: rc {rc}')
    return not bad, ('lrbind-sync add/check/refresh: every copy found, own comment lines kept, the header kept'
                     if not bad else 'FAIL sync: ' + '; '.join(bad))


CHECKS['sync'] = check_sync
MUTANTS += [
    ('sync: own comment lines count as stale', 'lrbind-sync', 'if line.strip() and not line.lstrip().startswith(comment):',
     'if line.strip():', 'sync', 'own comment lines above the header count as stale'),
    ('sync: refresh drops own lines', 'lrbind-sync', 'f.write(own + kit_file(name))', 'f.write(kit_file(name))', 'sync',
     "does not keep the copy's own comment lines"),
    ('sync: code above the header passes', 'lrbind-sync',
     '        if line.strip() and not line.lstrip().startswith(comment):\n            return None\n', '', 'sync',
     'check on drifted copies'),
    ('sync: only web/ and client/ copies', 'lrbind-sync', 'if name in FILES:',
     'if name in FILES and os.path.basename(dirpath) == FILES[name][0]:', 'sync', 'check on drifted copies'),
    ('sync: the kit tree is not skipped', 'lrbind-sync',
     '        if inside(dirpath, KIT):\n            dirnames[:] = []\n            continue\n', '', 'sync', 'check after add'),
    ('sync: node_modules is not skipped', 'lrbind-sync', 'sorted(d for d in dirnames if d not in SKIP)', 'sorted(dirnames)',
     'sync', 'check on drifted copies'),
    ('sync: a drifted tail passes', 'lrbind-sync', 'return own is not None and data[len(own):] == kit_file(name)',
     'return own is not None', 'sync', 'check on drifted copies'),
    ('sync: --help exits 2', 'lrbind-sync', '        return 0\n    if len(argv) != 3', '        return 2\n    if len(argv) != 3',
     'sync', '--help'),
]

# ==== mutants of lrbind.js and lrbind.lua that the suites have always caught
MUTANTS += [
    ('printf ties round up', 'lrbind.js', 'if (k % 2n === 1n) k += 1n;', '', 'parity', 'printf ties to even'),
    ("'yes' is truthy", 'lrbind.js', 'return l === "1" || l === "true";', 'return l === "1" || l === "true" || l === "yes";',
     'parity', 'string truthiness'),
    ('shrinking data-for keeps stale clones', 'lrbind.js', 'gone.element.remove();', '', 'parity', 'for basics'),
    ('text view ignores a failed run', 'lrbind.js', 'if (r.ok && entry.value !== v)', 'if (entry.value !== v)', 'parity',
     'runtime errors keep the old text'),
    ('negative literal index accepted', 'lrbind.js', 'if (index === null || index < 0) return null;',
     'if (index === null) return null;', 'parity', 'negative dynamic index'),
    ('it_index default renamed', 'lrbind.js', 'indexName: indexName || "it_index"', 'indexName: indexName || "index"',
     'parity', 'for default names'),
    ('undeclared event callback allowed', 'lrbind.js', 'if (!model.events.has(name)) {', 'if (false) {', 'parity',
     'undeclared event stops the chain'),
    ('ev.* ignores the parameter name', 'lrbind.js', 'if (event) return hasOwn(event, address[1]) ? event[address[1]] : NONE;',
     'if (event) return event.mouse_x;', 'parity', 'event params'),
    ('data-value writes on change, not per edit', 'lrbind.js',
     'if (tag === "textarea" || (tag === "input" && type !== "checkbox" && type !== "radio")) return "input";', '',
     'protocol', 'typing writes the model on every edit'),
    ('removeAt removes two entries', 'lrbind.js', 'a.splice(index, 1)', 'a.splice(index, 2)', 'protocol', 'removeAt 0'),
    ('lua: change does not update the Lua copy', 'lrbind.lua', 'if parent then parent[key] = payload.value end', '',
     'lua', 'change updates the Lua copy'),
    ('lua: toLua does not shift', 'lrbind.lua', '"[" .. (tonumber(n) + 1) .. "]"', '"[" .. n .. "]"', 'lua',
     'change path back to 1-based'),
]

# ==== the review's planted bugs that the kit's suites missed, caught by the cases merged from it (form controls compared
# with RmlUi's own control styling ignored, event params handed to the DOM event as RmlUi numbers them)
MUTANTS += [
    ('<= evaluates as <', 'lrbind.js', 'case I.LessEq: R = toNum(L) <= toNum(R);', 'case I.LessEq: R = toNum(L) < toNum(R);',
     'parity', 'relational eq-forms'),
    ('>= evaluates as >', 'lrbind.js', 'case I.GreaterEq: R = toNum(L) >= toNum(R);',
     'case I.GreaterEq: R = toNum(L) > toNum(R);', 'parity', 'relational eq-forms'),
    ('string != compares as ==', 'lrbind.js', 'case I.NotEqual: R = anyString(L, R) ? toStr(L) !== toStr(R)',
     'case I.NotEqual: R = anyString(L, R) ? toStr(L) === toStr(R)', 'parity', 'relational eq-forms'),
    ('CastToInt rounds instead of truncating', 'lrbind.js', 'return Number.isFinite(v) ? Math.trunc(v) | 0 : null;',
     'return Number.isFinite(v) ? Math.round(v) | 0 : null;', 'parity', 'dynamic index edges'),
    ('data-rml content is not bound', 'lrbind.js', 'view.children = bindChildren(view.model, el);', 'view.children = [];',
     'parity', 'rml view binds what it inserts'),
    ('modifier keys dropped from ev.*', 'lrbind.js', 'if ("ctrlKey" in e) {', 'if (false) {', 'parity',
     'event modifier keys and mouse button'),
    ('mouse button not renumbered (RmlUi: 1 = right)', 'lrbind.js',
     'p.button = e.button === 1 ? 2 : e.button === 2 ? 1 : e.button;', 'p.button = e.button;', 'parity',
     'event modifier keys and mouse button'),
    ('a view sets the checked attribute, not the control state', 'lrbind.js',
     '    if ("checked" in el && el.checked !== on) el.checked = on;\n', '', 'protocol', 'a later set unchecks a checkbox the user clicked'),
]


# ==== data-checked follows DataViewChecked; a change of the checked attribute fires change, as RmlUi's controls do
MUTANTS += [
    ('data-checked: checkboxes through toBool', 'lrbind.js',
     'setChecked(el, typeof value === "boolean" ? value : s !== "" && s === (el.getAttribute("value") || ""));',
     'setChecked(el, el.type === "radio" ? s === (el.getAttribute("value") || "") : toBool(value));', 'parity',
     'checked: checkbox bound to a string'),
    ('data-checked: an empty value matches', 'lrbind.js', 'value : s !== "" && s === (el.getAttribute', 'value : s === (el.getAttribute',
     'parity', 'checked: radio with empty value'),
    ('a checked change fires no change event', 'lrbind.js', 'el.dispatchEvent(new win.Event("change", { bubbles: true }));', '',
     'parity', 'checked: a view change fires change'),
    ('a checked radio leaves the others with its name', 'lrbind.js',
     '    if (on && el.type === "radio") popRadioSet(el);\n', '', 'parity', 'radios with one name uncheck each other'),
    ('a clicked radio leaves the others with its name', 'lrbind.js',
     '    if (el.checked && el.type === "radio") popRadioSet(el);\n', '', 'parity', 'radios with one name uncheck each other'),
    ('radio names reach into forms', 'lrbind.js', ' || (!form && r.closest("form"))', '', 'parity', 'forms apart'),
    ('a click does not set the checked attribute first', 'lrbind.js', '      root.addEventListener("change", syncToggle, true);\n',
     '', 'parity', 'one change event per click'),
    ('data-value on a checkbox writes its value', 'lrbind.js', '    if (el.type === "checkbox") return el.checked;\n', '',
     'parity', 'data-value on a checkbox writes its checked state'),
]

# ==== ev.* and controller values typed as RmlUi hands them over
MUTANTS += [
    ('modifier keys as booleans', 'lrbind.js', 'p.ctrl_key = e.ctrlKey ? 1 : 0;', 'p.ctrl_key = e.ctrlKey;', 'protocol',
     'modifier keys are ints 0/1'),
    ('a button on every mouse event', 'lrbind.js', 'if (BUTTON_EVENTS.has(e.type)) p.button =', 'p.button =', 'protocol',
     'mousemove carries no button'),
    ('no lock keys', 'lrbind.js', '      for (const [name, key] of LOCK_KEYS) p[name] =', '      if (false) p[name] =', 'protocol',
     'ctrl and caps lock as 1'),
    ('wheel deltas as their sign', 'lrbind.js', 'p.wheel_delta_x = e.deltaX / notch; p.wheel_delta_y = e.deltaY / notch;',
     'p.wheel_delta_x = Math.sign(e.deltaX); p.wheel_delta_y = Math.sign(e.deltaY);', 'parity', 'wheel delta in notches'),
    ('wheel deltaMode ignored', 'lrbind.js', 'const notch = WHEEL_NOTCH[e.deltaMode] || 1;', 'const notch = 100;', 'protocol',
     'wheel in lines'),
    ('ev.value of a range as text', 'lrbind.js', 'else p.value = t.type === "range" ? parseFloat(t.value) : t.value;',
     'else p.value = t.value;', 'protocol', 'range: ev.value and the model value are numbers'),
    ('a range writes text into the model', 'lrbind.js', 'return el.type === "range" ? parseFloat(el.value) : el.value;',
     'return el.value;', 'protocol', 'range: ev.value and the model value are numbers'),
    ('no ev.checked', 'lrbind.js', ' p.checked = t.checked;', '', 'protocol', 'checkbox change'),
    ("ev.value from the listener's element", 'lrbind.js', 'const t = e.target;', 'const t = e.currentTarget;', 'protocol',
     "carries the target's value"),
    ('ev.* reads inherited properties', 'lrbind.js', 'if (event) return hasOwn(event, address[1]) ? event[address[1]] : NONE;',
     'if (event) return event[address[1]];', 'parity', 'ev prototype name'),
]

# ==== assignments RmlUi refuses are refused; paths walk own members only; set appends but leaves no holes; merge takes
# top-level fields; a bad push/removeAt warns instead of throwing
MUTANTS += [
    ('an assignment creates a missing member', 'lrbind.js', '} else if (typeof entry === "number" || !hasOwn(cur, entry)) {',
     '} else if (typeof entry === "number") {', 'parity', 'assign to a missing member'),
    ('an assignment past the end of a list', 'lrbind.js', ' || entry < 0 || entry >= cur.length) {', ') {', 'parity',
     'assign out of bounds through an alias'),
    ('an assignment over a container', 'lrbind.js',
     '      if (cur !== null && typeof cur === "object") { warn("Values can only be assigned to scalar data types."); return false; }\n',
     '', 'parity', 'assign a container'),
    ('an assignment walks inherited members', 'lrbind.js', '!hasOwn(cur, entry)) {', 'cur[entry] === NONE) {', 'parity',
     'assign to an inherited name'),
    ('set walks inherited members', 'lrbind.js', '} else if (last ? Array.isArray(next) : !hasOwn(next, entry)) {',
     '} else if (last ? Array.isArray(next) : false) {', 'protocol', 'set through __proto__ / constructor is refused'),
    ('a member named __proto__ set as obj[key]', 'lrbind.js', 'if (key === "__proto__") Object.defineProperty',
     'if (false) Object.defineProperty', 'protocol', 'a member named __proto__ is an own member'),
    ('set leaves holes in a list', 'lrbind.js', 'if (entry > next.length || (entry === next.length && !last)) {',
     'if (false) {', 'protocol', 'set past the end of a list is refused'),
    ('merge takes any key', 'lrbind.js', 'if (!m.variables.has(k)) { warn("merge:', 'if (false) { warn("merge:', 'protocol',
     'merge takes top-level fields only'),
    ('removeAt takes a fractional index', 'lrbind.js', 'if (a && Number.isInteger(index) && index >= 0', 'if (a && index >= 0',
     'protocol', 'a fractional index'),
    ('push/removeAt without a path throws', 'lrbind.js',
     '  function arrayAt(model, path) {\n    const address = typeof path === "string" ? parseAddress(path) : null;',
     '  function arrayAt(model, path) {\n    const address = parseAddress(path);', 'protocol', 'without a path'),
]

# ==== model names RmlUi refuses (reserved, case-insensitively; not a letter first; other characters) are not bound
MUTANTS += [
    ('reserved names are bound', 'lrbind.js', '    if (RESERVED.has(l)) return "Name is reserved.";\n', '', 'parity',
     'reserved and illegal model names'),
    ('reserved names compared with their case', 'lrbind.js', 'if (RESERVED.has(l))', 'if (RESERVED.has(name))', 'parity',
     'model names RmlUi refuses'),
    ('any first character', 'lrbind.js', "if (!/^[a-z]/.test(l)) return", "if (false) return", 'protocol',
     'illegal and reserved model names are refused'),
    ('any character after it', 'lrbind.js', "if (!/^[a-z0-9_]*$/.test(l)) return", "if (false) return", 'protocol',
     'illegal and reserved model names are refused'),
]

# ==== data-for: structural (aliases on its element are cancelled), names split as ExpandString does, a failed view
# leaves its element empty and says why
MUTANTS += [
    ('aliases on a data-for element apply', 'lrbind.js', '      if (view) out.push(addView(model, view));\n      else while',
     '      for (const a of attrs) if (a.name.startsWith("data-alias-")) { const t = model.resolve(a.value, el); '
     'if (t) insertAlias(model, el, a.name.slice(11), t); }\n      const view2 = makeFor(model, el, forAttr);\n'
     '      if (view2) out.push(addView(model, view2));\n      else while', 'parity', 'for container through an alias'),
    ('three names: the first one used', 'lrbind.js', '      if (pair.length === 1 || pair.length === 2) iterator = pair[0];',
     '      iterator = pair[0];', 'parity', 'for three names'),
    ('a trailing empty item counts', 'lrbind.js', '    if (start >= 0) out.push(str.slice(start, end + 1));',
     '    out.push(start >= 0 ? str.slice(start, end + 1) : "");', 'parity', 'for syntax edges'),
    ('a failed data-for keeps its content', 'lrbind.js', '      else while (el.firstChild) el.removeChild(el.firstChild);\n',
     '', 'parity', 'for syntax edges'),
    ('a data-for that names nothing is silent', 'lrbind.js',
     "{ warn(\"Could not find variable name '\" + halves[halves.length - 1] + \"' in data model. Could not add data-for view.\"); return null; }",
     '{ return null; }', 'parity', 'for container through an alias'),
]

# ==== browser: data-rml in a real Chromium (skipped without one): planted handlers, an iframe, a javascript: link
# that the page clicks; none may run, and the markup must be there
def find_chrome():
    rc, out = sh(['bin/html-shot', '--find'])
    path = out.strip().splitlines()[-1] if rc == 0 and out.strip() else ''
    return path if path and os.path.exists(path) else None


CHROME = find_chrome()
XSS = ('<b>ok</b><img src="x" onerror="document.title=\'PWNED\'">'
       '<iframe srcdoc="<script>parent.document.title=\'PWNED\'</script>"></iframe>'
       '<svg><animate onbegin="document.title=\'PWNED\'" attributeName="x" dur="1s"/></svg>'
       '<details open ontoggle="document.title=\'PWNED\'"><summary>x</summary></details>'
       '<a id="j" href=" javascript:document.title=\'PWNED\'">j</a>')
XSS_JSON = json.dumps(XSS).replace('</', '<\\/')   # it sits inside a <script>
XSS_PAGE = """<!doctype html><html><head><title>clean</title><script src="lrbind.js"></script></head><body>
<div data-model="m"><div id="a" data-rml="html"></div><b id="n">{{n}}</b></div>
<script>LrBind.init({ models: { m: { n: 1, html: %s } } });</script>
<script>setTimeout(() => document.getElementById('j') && document.getElementById('j').click(), 50);</script>
</body></html>"""


def check_browser(js=JS):
    if not CHROME:
        return True, 'skipped (no Chromium: bin/html-shot --find)'
    d = os.path.join(TMP, 'browser-' + re.sub(r'\W', '_', os.path.basename(js)))
    os.makedirs(d, exist_ok=True)
    shutil.copy(js, os.path.join(d, 'lrbind.js'))
    with open(os.path.join(d, 'index.html'), 'w') as f:
        f.write(XSS_PAGE % XSS_JSON)
    rc, out = sh([CHROME, '--headless', '--no-sandbox', '--disable-gpu', '--virtual-time-budget=3000',
                  '--user-data-dir=' + os.path.join(d, 'profile'), '--dump-dom', 'file://' + os.path.join(d, 'index.html')],
                 timeout=60)
    m = re.search(r'<title>(.*?)</title>', out)
    title = m.group(1) if m else None
    bound = re.search(r'<div id="a"[^>]*><b>ok</b>', out) is not None
    ran = 'PWNED' in out.replace(XSS_JSON, '')
    ok = rc == 0 and title == 'clean' and bound and not ran
    return ok, ('data-rml in Chromium: the markup is there, none of the planted scripts ran' if ok else
                'FAIL browser: data-rml in Chromium: ' + ('a planted script ran' if ran else 'nothing ran') +
                f', markup there {bound}, title {title!r}, rc {rc}')


CHECKS['browser'] = check_browser

# ==== data-rml: inert in a browser (what would act there and means nothing to RmlUi is dropped), an empty value keeps
# the markup's content, the views of replaced content die with it
MUTANTS += [
    ('data-rml as innerHTML', 'lrbind.js', '      insertInert(el, v);', '      el.innerHTML = v;', 'browser',
     'a planted script ran'),
    ('data-rml as innerHTML (jsdom)', 'lrbind.js', '      insertInert(el, v);', '      el.innerHTML = v;', 'protocol',
     'data-rml: no script'),
    ('data-rml keeps active elements', 'lrbind.js', 'if (ACTIVE_TAGS.has(tag)) {', 'if (false) {', 'protocol',
     'data-rml: no script, iframe'),
    ('data-rml keeps on* handlers', 'lrbind.js', 'if (name.startsWith("on") || ', 'if (', 'protocol',
     'data-rml: no on* handler'),
    ('data-rml keeps links and form targets', 'lrbind.js', ' || ACTIVE_ATTRS.has(name) || ', ' || ', 'protocol',
     'data-rml: no link or form target'),
    ('data-rml keeps javascript: values', 'lrbind.js', ' || /^(javascript|vbscript|data):/.test(value)) {', ') {', 'protocol',
     'data-rml: no javascript:/data: value'),
    ('data-rml compares values as written', 'lrbind.js', '.replace(/[\\u0000-\\u0020\\u007f-\\u009f]+/g, "").toLowerCase();',
     ';', 'protocol', 'in any case or spacing'),
    ('data-rml drops silently', 'lrbind.js', '    if (dropped.size) warn(', '    if (false) warn(', 'protocol',
     'what it dropped is reported'),
    ('data-rml: an empty value wipes the content', 'lrbind.js', 'last: kind === "rml" ? "" : NONE', 'last: NONE', 'parity',
     'rml view keeps markup content when the value is empty'),
    ('data-rml: replaced content keeps its views', 'lrbind.js',
     '      for (const sub of view.model.views) if (sub !== view && !sub.dead && el.contains(sub.element)) dropView(sub);\n',
     '', 'parity', 'what it replaces stops updating'),
]

# ==== RmlUi's warnings that had no twin: ev.* read outside an event, an inline style value that does not parse (the
# old value stays)
MUTANTS += [
    ('ev.* outside an event is silent', 'lrbind.js',
     '          warn("Could not get value from data variable \'ev." + address[1] + "\'.");', '', 'parity', 'ev in a view'),
    ('a style value that does not parse is silent', 'lrbind.js',
     '      warn("Syntax error parsing inline property declaration \'" + mod + ": " + v + ";\'.");', '', 'parity',
     'style with a number'),
    ('a style value that does not parse clears the old one', 'lrbind.js', '      if (old !== "") el.style.setProperty(mod, old);\n',
     '', 'parity', 'style with a number'),
]

# ==== attribute names keep their case where the DOM keeps it (a page as XHTML, as RmlUi reads XML); in an HTML page a
# camelCase alias the parser lowercased still resolves, with a warning; nothing else is matched ignoring case
MUTANTS += [
    ('alias names lowercased', 'lrbind.js', 'insertAlias(model, el, a.name.slice(11), target, true);',
     'insertAlias(model, el, asciiLower(a.name.slice(11)), target, true);', 'parity', 'camelCase alias and class names'),
    ('class names lowercased', 'lrbind.js', 'class(el, value, mod) { el.classList.toggle(mod, toBool(value)); },',
     'class(el, value, mod) { el.classList.toggle(asciiLower(mod), toBool(value)); },', 'parity', 'camelCase alias and class names'),
    ('aliases matched ignoring case in XML too', 'lrbind.js', ' && lowercasesAttributes(el.ownerDocument)) {', ') {', 'parity',
     'camelCase alias and class names'),
    ('no case fallback in HTML', 'lrbind.js', 'if (lower !== address[0] && fromAttr && fromAttr.has(lower)',
     'if (false && fromAttr && fromAttr.has(lower)', 'protocol', 'a camelCase data-alias resolves in an HTML page'),
    ('the case fallback is silent', 'lrbind.js', 'warn("\'" + address[0] + "\' matches data-alias-', 'void ("\'" + address[0] + "\' matches data-alias-',
     'protocol', 'a camelCase data-alias resolves in an HTML page'),
    ('iterator names matched ignoring case', 'lrbind.js', 'fromAttr && fromAttr.has(lower) &&', 'names.has(lower) &&',
     'protocol', 'an iterator name is matched as written'),
]

# ==== the run

def plant(i, src, old, new):
    path, _ = SOURCES[src]
    with open(path, encoding='utf-8') as f:
        text = f.read()
    n = text.count(old)
    if n != 1 and src != 'golden.json':
        return None, f'pattern found {n} times (the mutant no longer applies; update lrbind/tests/suite.py)'
    out = os.path.join(TMP, 'mutants', f'm{i:02d}-{src}')
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, 'w', encoding='utf-8') as f:
        f.write(text.replace(old, new, 1))
    if src == 'cases.mjs':   # its shared blocks are read relative to the file
        shutil.copytree(os.path.join(os.path.dirname(CASES), 'fixtures'), os.path.join(os.path.dirname(out), 'fixtures'),
                        dirs_exist_ok=True)
    return out, None


def run_mutant(i, m):
    what, src, old, new, check, expect = m
    path, err = plant(i, src, old, new)
    if err:
        return False, f'FAIL mutant {what}: {err}'
    ok, detail = CHECKS[check](**{SOURCES[src][1]: path})
    if detail.startswith('skipped'):
        return True, f'ok    mutant {what} -> {check} {detail}'
    if ok:
        return False, f'FAIL mutant {what}: {check} stayed green'
    if expect not in detail:
        return False, f'FAIL mutant {what}: {check} went red, but not on {expect!r}:\n{detail}'
    return True, f'ok    mutant {what} -> {check} red on {expect!r}'


def main():
    global HOST
    failed = 0
    rc, out = sh(['bash', 'scripts/build.sh'])
    HOST = out.strip().splitlines()[-1] if rc == 0 else ''
    if rc != 0 or not os.path.exists(HOST):
        print('FAIL rmlhost: scripts/build.sh failed\n' + out)
        return 1
    rc, cases = sh(['node', 'lrbind/tests/parity/parity.test.mjs', '--emit-cases'])
    try:
        if rc:
            raise RuntimeError(cases[-400:])
        with open(FRESH, 'wb') as f:
            f.write(host_parity(cases))
    except RuntimeError as e:
        print(f'FAIL rmlhost parity did not run: {e}')
        return 1
    for name, fn in CHECKS.items():
        ok, detail = fn()
        print(f'ok    {name}: {detail}' if ok else detail if detail.startswith('FAIL') else f'FAIL {name}: {detail}')
        failed += not ok
    with cf.ThreadPoolExecutor(max_workers=min(8, os.cpu_count() or 2)) as pool:
        for ok, line in pool.map(lambda a: run_mutant(*a), enumerate(MUTANTS)):
            print(line)
            failed += not ok
    print(f'lrbind suite: {len(CHECKS)} checks, {len(MUTANTS)} mutants, {failed} failed')
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
