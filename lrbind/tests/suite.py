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
    ('ev.* ignores the parameter name', 'lrbind.js', 'return event && hasOwn(event, address[1]) ? event[address[1]] : NONE;',
     'return event ? event.mouse_x : NONE;', 'parity', 'event params'),
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
    ('ev.* reads inherited properties', 'lrbind.js', 'event && hasOwn(event, address[1]) ? event[address[1]] : NONE',
     'event ? event[address[1]] : NONE', 'parity', 'ev prototype name'),
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
