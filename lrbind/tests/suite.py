#!/usr/bin/env python3
"""lrbind suite (run by tests/lrbind.sh from the kit root, NUIKIT_TMP set).

Checks, one line each:
  golden    rmlhost parity regenerates golden.json from cases.mjs on every run; it must equal the committed file
  parity    lrbind.js in jsdom against that fresh golden, snapshot by snapshot
  protocol  the page protocol, form controls, mockup mode (protocol.test.mjs)
  lua       lrbind.lua against a fake page (lrbind_lua.lua)
Then every mutant in MUTANTS: a copy of one file with ONE planted bug, run through the one check it names. That check
must go red, and its output must contain the expected text (the failing case or check). A mutant whose pattern no
longer matches exactly once fails too, so the table cannot rot silently.
"""
import concurrent.futures as cf, json, os, re, shutil, subprocess, sys

KIT = os.environ.get('NUIKIT') or os.getcwd()
TMP = os.environ['NUIKIT_TMP']
JS = os.path.join(KIT, 'lrbind', 'lrbind.js')
LUA = os.path.join(KIT, 'lrbind', 'lrbind.lua')
GOLDEN = os.path.join(KIT, 'lrbind', 'tests', 'parity', 'golden.json')
FRESH = os.path.join(TMP, 'golden.json')
SOURCES = {'lrbind.js': (JS, 'js'), 'lrbind.lua': (LUA, 'lua'), 'golden.json': (GOLDEN, 'golden')}
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

# ==== parity, protocol, lua: the three test files, run on the file under test


def check_parity(js=JS):
    return result(*sh(['node', 'lrbind/tests/parity/parity.test.mjs', '--golden', FRESH], env={'LRBIND_SHIM': js}))


def check_protocol(js=JS):
    return result(*sh(['node', 'lrbind/tests/protocol.test.mjs'], env={'LRBIND_SHIM': js}))


def check_lua(lua=LUA):
    return result(*sh(['lua5.4', 'tests/lrbind_lua.lua'], cwd=os.path.join(KIT, 'lrbind'), env={'LRBIND_LUA': lua}))


CHECKS.update(parity=check_parity, protocol=check_protocol, lua=check_lua)

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
    ('ev.* ignores the parameter name', 'lrbind.js', 'return event ? event[address[1]] : NONE;',
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
    failed = 0
    rc, out = sh(['bash', 'scripts/build.sh'])
    host = out.strip().splitlines()[-1] if rc == 0 else ''
    if rc != 0 or not os.path.exists(host):
        print('FAIL rmlhost: scripts/build.sh failed\n' + out)
        return 1
    rc, cases = sh(['node', 'lrbind/tests/parity/parity.test.mjs', '--emit-cases'])
    r = subprocess.run([host, 'parity'], input=cases.encode(), capture_output=True)
    with open(FRESH, 'wb') as f:
        f.write(r.stdout)
    if rc != 0 or r.returncode != 0:
        print('FAIL rmlhost parity did not run: ' + (cases if rc else r.stderr.decode())[-400:])
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
