#!/usr/bin/env bash
# The docs and the CI file describe the code as it is: the commands in README.md, examples/side-menu/README.md and the
# agent skill are RUN (in a copy of the kit) and must leave the hand-written example alone; the skill's metadata
# follows the Agent Skills spec, every link names a file, references/output.md explains every line the tools print,
# the agent docs name no home path, tailnet address or account (NUIKIT_PRIVATE_RE adds a project's own names); the
# Lua snippet of docs/cases.md must write cases rml-check accepts, the numbers the docs quote (Node floor, instruction
# budget) must be the code's, and CI must make Chromium and Pillow required, bound its run time and use a Node jsdom
# supports. Each check has a mutant (a copy of the doc or the CI file with ONE bug). Contract: tests/README.md.
set -uo pipefail
kit="${NUIKIT:?run through scripts/test.sh}"; tmp="${NUIKIT_TMP:?}"
cd "$kit"
fail=0
export LUA="${LUA:-$(command -v lua5.4 || command -v lua)}"
have_pil=0; python3 -c 'import PIL' 2>/dev/null && have_pil=1
have_chrome=0; bin/html-shot --find >/dev/null 2>&1 && have_chrome=1
SK=skills/open77-nativeui
files=(README.md docs/cases.md docs/rmlui-traps.md examples/side-menu/README.md .github/workflows/ci.yml
       AGENTS.md "$SK/SKILL.md" "$SK/references/output.md" "$SK/references/porting.md")

ok() { echo "ok   $1"; }
bad() { echo "FAIL $1${2:+: $2}"; }
verdict() { local name="$1"; shift; if "$@"; then ok "$name"; else bad "$name"; fi; }   # verdict NAME CMD...

copy_kit() {   # a copy of the kit to run the docs' commands in (no .git, no node_modules, no outputs)
    rm -rf "$1"; mkdir -p "$1"
    tar --exclude=node_modules --exclude=.git --exclude=out --exclude=shots -cf - . | tar -xf - -C "$1"
}

# run_blocks DOCFILE CWD KITCOPY: the ```sh blocks of DOCFILE, each in a fresh shell in CWD; `lua5.4` is $LUA, the clone and
# the build are left out (the kit is there already), commands whose tool is missing are left out (rml-preview without
# Pillow, html-shot and --compare without Chromium)
run_blocks() {
    local doc="$1" cwd="$2" kc="$3" n=0 b
    mkdir -p "$kc/.blocks"
    python3 - "$doc" "$kc/.blocks" "$have_pil" "$have_chrome" <<'PY'
import re, sys
doc, out, pil, chrome = sys.argv[1], sys.argv[2], sys.argv[3] == '1', sys.argv[4] == '1'
text = open(doc, encoding='utf-8').read()
for i, m in enumerate(re.finditer(r'```sh\n(.*?)```', text, re.S)):
    body = re.sub(r'\\\n\s*', ' ', m.group(1))
    lines = []
    for l in body.split('\n'):
        if 'git clone' in l or 'scripts/build.sh' in l:
            continue
        if ('rml-preview' in l and not pil) or ('html-shot' in l and not chrome) or ('--compare' in l and not chrome):
            continue
        lines.append(l.replace('lua5.4', '"$LUA"'))
    open('%s/b%d.sh' % (out, i), 'w').write('set -euo pipefail\n' + '\n'.join(lines) + '\n')
PY
    for b in "$kc"/.blocks/b*.sh; do
        [ -e "$b" ] || continue
        n=$((n + 1))
        if ! (cd "$cwd" && KIT="$kc" bash "$b" >"$b.log" 2>&1); then echo "block $n of $doc failed:"; tail -5 "$b.log" | sed 's/^/     /'; return 1; fi
    done
    [ "$n" -gt 0 ]
}

same_example() {   # the hand-written files of the example are as in the kit
    local f
    for f in ui/menu.rml ui/menu.rcss client/menu.lua models.lua web/index.html web/app.css cases.json; do
        cmp -s "$kit/examples/side-menu/$f" "$1/examples/side-menu/$f" || { echo "changed: examples/side-menu/$f"; return 1; }
    done
}

# ---- the checks; each takes the directory holding the (possibly mutated) copies of $files ----

chk_readme_run() {
    local d="$1" kc="$tmp/kc-readme$RANDOM"
    copy_kit "$kc"; cp "$d/README.md" "$kc/README.md"
    local o; o=$(run_blocks "$kc/README.md" "$kc" "$kc" 2>&1) && o2=$(same_example "$kc") && ok "README: its commands run, and leave the hand-written example alone" \
        || bad "README: its commands run, and leave the hand-written example alone" "$o ${o2:-}"
}
chk_example_readme_run() {
    local d="$1" kc="$tmp/kc-exreadme$RANDOM"
    copy_kit "$kc"; cp "$d/examples/side-menu/README.md" "$kc/examples/side-menu/README.md"
    local o; o=$(run_blocks "$kc/examples/side-menu/README.md" "$kc/examples/side-menu" "$kc" 2>&1) && o2=$(same_example "$kc") && ok "example README: its commands run, and leave the hand-written example alone" \
        || bad "example README: its commands run, and leave the hand-written example alone" "$o ${o2:-}"
}
chk_cases_snippet() {
    local d="$1" w="$tmp/snip$RANDOM"
    mkdir -p "$w"
    python3 - "$d/docs/cases.md" "$kit" "$w/snippet.lua" <<'PY'
import re, sys
doc, kit, out = sys.argv[1:]
snip = re.search(r'```lua\n(.*?)```', open(doc, encoding='utf-8').read(), re.S).group(1)
models = open(kit + '/examples/side-menu/models.lua', encoding='utf-8').read()
shop = re.search(r'^local (SHOP = \{.*?^\})', models, re.S | re.M).group(1)
open(out, 'w').write(shop + '\n' + snip.replace('path/to/open77-nui-kit', kit))
PY
    if (cd examples/side-menu && "$LUA" "$w/snippet.lua" > "$w/cases.json" 2> "$w/err") \
        && [ -s "$w/cases.json" ] && (cd examples/side-menu && ../../bin/rml-check ui/menu.rml "$w/cases.json" >"$w/check" 2>&1); then
        ok "docs/cases.md: its Lua snippet writes cases that rml-check accepts"
    else bad "docs/cases.md: its Lua snippet writes cases that rml-check accepts" "$(head -c 200 "$w/err") $(tail -2 "$w/check" 2>/dev/null)"; fi
}
chk_node_floor() {
    local d="$1" want
    want=$(python3 - <<'PY'
import json, re
lock = json.load(open('lrbind/tests/package-lock.json'))
eng = lock['packages']['node_modules/jsdom']['engines']['node']
print(re.search(r'\^(\d+\.\d+)', eng).group(1))     # the lowest caret clause: 20.19
PY
)
    if grep -qi "node.* ${want}+" "$d/README.md" && ! grep -qi "node.* 18+" "$d/README.md"; then ok "README: names the Node floor of the pinned jsdom ($want+)"
    else bad "README: names the Node floor of the pinned jsdom ($want+)"; fi
}
chk_lua_names() {
    local d="$1"
    if grep -q 'apt install lua5.4' "$d/README.md" && grep -q 'dnf install lua`' "$d/README.md" && grep -q 'scripts/test.sh` finds either' "$d/README.md"; then
        ok "README: says how Lua 5.4 is named per distro and that test.sh finds either"
    else bad "README: says how Lua 5.4 is named per distro and that test.sh finds either"; fi
}
chk_clone_url() {
    local d="$1"
    if grep -q 'git clone https://github.com/glitchbunny0/open77-nui-kit' "$d/README.md" && ! grep -q '<this repo>' "$d/README.md"; then ok "README: the clone URL is real"
    else bad "README: the clone URL is real"; fi
}
chk_budget() {
    local d="$1" n
    n=$("$LUA" -e 'local F = dofile("fake-nui/fake_nui.lua"); io.write(tostring(F.budget))' | python3 -c 'print(f"{int(input()):,}")')
    if grep -q "$n" "$d/docs/cases.md" "$d/docs/rmlui-traps.md" fake-nui/fake_nui.lua && ! grep -Eq '10 ?000|10k' "$d/README.md" "$d/docs/cases.md" "$d/docs/rmlui-traps.md" fake-nui/fake_nui.lua; then
        ok "docs: the instruction budget they quote is F.budget ($n), and no 10k is left"
    else bad "docs: the instruction budget they quote is F.budget ($n), and no 10k is left"; fi
}
chk_print() {
    local d="$1"
    if ! grep -Eq '^print\(F\.json' "$d/docs/cases.md" && grep -q 'io.write(F.json' "$d/docs/cases.md" && grep -q 'FAKE_NUI_LOG=1' "$d/docs/cases.md"; then
        ok "docs/cases.md: cases are written with io.write and the print capture is explained"
    else bad "docs/cases.md: cases are written with io.write and the print capture is explained"; fi
}
chk_stubs_documented() {   # every method fake-nui only records is named in docs/cases.md
    local d="$1" missing
    missing=$("$LUA" -e 'local F = dofile("fake-nui/fake_nui.lua"); for _, n in ipairs(F.stubs) do io.write(n, "\n") end' | while read -r m; do grep -q "\`$m\`" "$d/docs/cases.md" || echo "$m"; done)
    if [ -z "$missing" ]; then ok "docs/cases.md: names every method fake-nui only records"
    else bad "docs/cases.md: names every method fake-nui only records" "$(echo $missing)"; fi
}
chk_ci() {
    local d="$1" y="$1/.github/workflows/ci.yml" why=""
    grep -q 'NUIKIT_REQUIRE_CHROME: "1"' "$y" || why="$why no NUIKIT_REQUIRE_CHROME;"
    grep -q 'NUIKIT_REQUIRE_PILLOW: "1"' "$y" || why="$why no NUIKIT_REQUIRE_PILLOW;"
    grep -Eq 'timeout-minutes: [0-9]+' "$y" || why="$why no timeout-minutes;"
    python3 - "$y" <<'PY' || why="$why Node version outside jsdom's engines;"
import json, re, sys
eng = json.load(open('lrbind/tests/package-lock.json'))['packages']['node_modules/jsdom']['engines']['node']
m = re.search(r'node-version:\s*"?(\d+)', open(sys.argv[1]).read())
major = int(m.group(1)) if m else 0
ok = any((c.strip().startswith('^') and int(re.match(r'\^(\d+)', c.strip()).group(1)) == major)
         or (c.strip().startswith('>=') and major >= int(re.match(r'>=(\d+)', c.strip()).group(1))) for c in eng.split('||'))
sys.exit(0 if ok else 1)
PY
    python3 - "$y" <<'PY' || why="$why Chromium is not installed before the tests;"
import re, sys
t = open(sys.argv[1]).read()
i, j = t.find('install --with-deps chromium-headless-shell'), t.find('run: scripts/test.sh')
sys.exit(0 if 0 <= i < j else 1)
PY
    if [ -z "$why" ]; then ok "ci.yml: Chromium and Pillow required, run time bounded, Node fits jsdom, Chromium installed first"
    else bad "ci.yml: Chromium and Pillow required, run time bounded, Node fits jsdom, Chromium installed first" "$why"; fi
}

chk_skill_run() {   # the skill's shell blocks run against the example ($KIT = a copy of the kit) and leave it alone
    local d="$1" kc="$tmp/kc-skill$RANDOM"
    copy_kit "$kc"; cp "$d/$SK/SKILL.md" "$kc/$SK/SKILL.md"
    local o; o=$(run_blocks "$kc/$SK/SKILL.md" "$kc" "$kc" 2>&1) && o2=$(same_example "$kc") && ok "skill: its commands run, and leave the example alone" \
        || bad "skill: its commands run, and leave the example alone" "$o ${o2:-}"
}
chk_skill_meta() {   # SKILL.md frontmatter as agentskills.io/specification says: name = folder, charset, lengths
    local d="$1" why
    why=$(python3 - "$d/$SK/SKILL.md" "$(basename "$SK")" <<'PY'
import re, sys
text = open(sys.argv[1], encoding='utf-8').read()
m = re.match(r'---\n(.*?)\n---\n', text, re.S)
if not m:
    print('no frontmatter'); sys.exit()
meta = dict(l.split(':', 1) for l in m.group(1).splitlines() if ':' in l and not l.startswith(' '))
meta = {k.strip(): v.strip() for k, v in meta.items()}
name, desc = meta.get('name', ''), meta.get('description', '')
why = []
if name != sys.argv[2]: why.append(f'name {name!r} is not the folder {sys.argv[2]!r}')
if not re.fullmatch(r'[a-z0-9]+(-[a-z0-9]+)*', name) or len(name) > 64: why.append('name: 1-64 of a-z 0-9 and single hyphens')
if not 1 <= len(desc) <= 1024: why.append(f'description is {len(desc)} chars (1-1024)')
if len(meta.get('compatibility', 'x')) > 500: why.append('compatibility over 500 chars')
if text.count('\n') >= 500: why.append('SKILL.md has 500 lines or more')
print('; '.join(why))
PY
)
    if [ -z "$why" ]; then ok "skill: metadata as the Agent Skills spec says"; else bad "skill: metadata as the Agent Skills spec says" "$why"; fi
}
chk_links() {   # every relative link, and every $KIT/<path>, in the README, AGENTS.md and the skill names a file of the kit
    local d="$1" missing
    missing=$(python3 - "$d" "$kit" README.md AGENTS.md "$SK/SKILL.md" "$SK/references/output.md" "$SK/references/porting.md" <<'PY'
import os, re, sys
d, kit, docs = sys.argv[1], sys.argv[2], sys.argv[3:]
miss = []
for doc in docs:
    text = open(os.path.join(d, doc), encoding='utf-8').read()
    base = os.path.dirname(doc)
    for target in re.findall(r'\]\(([^)\s]+)\)', text):
        if re.match(r'[a-z]+:', target) or target.startswith('#'):
            continue
        if not os.path.exists(os.path.normpath(os.path.join(kit, base, target.split('#')[0]))):
            miss.append(f'{doc}: {target}')
    for path in re.findall(r'\$KIT"?/([\w./-]+)', text):
        path = path.rstrip('.')
        if not os.path.exists(os.path.join(kit, path)):
            miss.append(f'{doc}: $KIT/{path}')
print(' '.join(miss))
PY
)
    if [ -z "$missing" ]; then ok "docs: every link and \$KIT path names a file of the kit"; else bad "docs: every link and \$KIT path names a file of the kit" "$missing"; fi
}
chk_output_forms() {   # every kind of line the tools print is explained in the skill's references/output.md
    local d="$1" missing
    missing=$(python3 - "$d/$SK/references/output.md" <<'PY'
import re, sys
doc = open(sys.argv[1], encoding='utf-8').read()
src = lambda p: open(p, encoding='utf-8').read()
forms = set(re.findall(r"print\(f?'([A-Z]+(?: [A-Z]+)*)\b", src('bin/rml-check')))            # WARN, EVENT, CLICK FAIL, ...
forms |= set(re.findall(r"""notes\.add\(f?['"]([A-Z]+(?: [A-Z]+)*)\b""", src('bin/rml-preview')))   # NOT PAINTED, MISSING, ...
forms |= set(re.findall(r"print\('(not painted \(see rml-preview --help\))", src('bin/rml-preview')))
host = src('host/mode_check.inc')
for line in host.splitlines():                                   # what a click line says happened instead
    if re.search(r'\bgot\s*\+?=', line):
        forms |= {s.strip() for s in re.findall(r'"([a-z ,][a-z -]*[a-z])', line) if len(s.strip()) > 3}
if 'do not list' in src('bin/rml-check'):
    forms.add('do not list')
print(' '.join(sorted(repr(f) for f in forms if f not in doc)))
PY
)
    if [ -z "$missing" ]; then ok "skill: references/output.md explains every kind of line the tools print"
    else bad "skill: references/output.md explains every kind of line the tools print" "$missing"; fi
}
chk_private() {   # agent docs name no home path, tailnet address or account; NUIKIT_PRIVATE_RE adds your own names
    local d="$1" hits re='(^|[^[:alnum:]./])(/home/|/Users/)[[:alnum:]]|\b100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]+\.[0-9]+|github\.com/[[:alnum:]-]+/'
    [ -n "${NUIKIT_PRIVATE_RE:-}" ] && re="$re|$NUIKIT_PRIVATE_RE"
    hits=$(grep -n -i -E "$re" "$d/AGENTS.md" "$d/$SK/SKILL.md" "$d/$SK/references/"*.md || true)
    if [ -z "$hits" ]; then ok "agent docs: no home paths, tailnet addresses or accounts"; else bad "agent docs: no home paths, tailnet addresses or accounts" "$hits"; fi
}

all_checks="chk_readme_run chk_example_readme_run chk_cases_snippet chk_node_floor chk_lua_names chk_clone_url chk_budget chk_print chk_stubs_documented chk_ci chk_skill_run chk_skill_meta chk_links chk_output_forms chk_private"
real="$tmp/real"
for f in "${files[@]}"; do mkdir -p "$real/$(dirname "$f")"; cp "$f" "$real/$f"; done
out=$(for c in $all_checks; do $c "$real"; done)
grep -v '^ok ' <<<"$out" && fail=1
echo "docs: $(grep -c '^ok ' <<<"$out") checks ok on the real files"

# ---- mutants ----
i=0; reds=0
mutant() {   # mutant CHECK-FUNCTION NAME FILE OLD NEW
    local fn="$1" name="$2" file="$3" old="$4" new="$5"
    i=$((i + 1))
    local d="$tmp/mut$i"
    mkdir -p "$d"
    for f in "${files[@]}"; do mkdir -p "$d/$(dirname "$f")"; cp "$f" "$d/$f"; done
    if ! F="$d/$file" OLD="$old" NEW="$new" python3 - <<'PY'
import os, sys
f = os.environ['F']
s = open(f, encoding='utf-8').read()
if s.count(os.environ['OLD']) != 1:
    print('mutant site matches %d times: %r' % (s.count(os.environ['OLD']), os.environ['OLD'][:70])); sys.exit(1)
open(f, 'w', encoding='utf-8').write(s.replace(os.environ['OLD'], os.environ['NEW']))
PY
    then echo "FAIL: mutant $i ($name): the site is gone"; fail=1; return; fi
    local o; o=$($fn "$d")
    if grep -q "^FAIL $name" <<<"$o"; then reds=$((reds + 1))
    else echo "FAIL: mutant $i did not turn '$name' red"; grep -v '^ok ' <<<"$o" | head -3; fail=1; fi
}

mutant chk_readme_run "README: its commands run" README.md '../../bin/html2rml web/index.html --out out/twin --name menu     #' '../../bin/html2rml web/index.html --out ui --name menu     #'
mutant chk_readme_run "README: its commands run" README.md 'git clone https://github.com/glitchbunny0/open77-nui-kit && cd open77-nui-kit
scripts/build.sh                            # fetches RmlUi 6.3 and builds the host once (about a minute)
cd examples/side-menu' 'git clone https://github.com/glitchbunny0/open77-nui-kit && cd open77-nui-kit
scripts/build.sh                            # fetches RmlUi 6.3 and builds the host once (about a minute)'
mutant chk_example_readme_run "example README: its commands run" examples/side-menu/README.md '../../bin/rml-check ui/menu.rml cases.json
../../bin/rml-preview ui/menu.rml' '../../bin/rml-check ui/menu.rml cases.json
../../bin/rml-check2 ui/menu.rml'
mutant chk_example_readme_run "example README: its commands run" examples/side-menu/README.md '../../bin/html2rml web/index.html --out out/twin --name menu ' '../../bin/html2rml web/index.html --out ui --name menu '
mutant chk_cases_snippet "docs/cases.md: its Lua snippet writes cases" docs/cases.md 'io.write(F.json({ F.case("picked"' 'print(F.json({ F.case("picked"'
mutant chk_node_floor "README: names the Node floor" README.md 'Node 20.19+' 'Node 18+'
mutant chk_lua_names "README: says how Lua 5.4 is named" README.md '`dnf install lua` (command `lua`)' '`dnf install lua5.4`'
mutant chk_clone_url "README: the clone URL is real" README.md 'git clone https://github.com/glitchbunny0/open77-nui-kit' 'git clone <this repo>'
mutant chk_budget "docs: the instruction budget" docs/cases.md 'Open77 allows 1,500,000 instructions per coroutine resume (500,000 on older clients)' 'Open77 allows roughly 10 000 instructions per coroutine resume'
mutant chk_budget "docs: the instruction budget" docs/rmlui-traps.md 'Open77 allows 1,500,000 Lua instructions' 'Open77 allows about 10k Lua instructions'
mutant chk_print "docs/cases.md: cases are written with io.write" docs/cases.md '`FAKE_NUI_LOG=1` echoes it to stderr' '`FAKE_NUI_LOG` echoes it'
mutant chk_stubs_documented "docs/cases.md: names every method" docs/cases.md '`unanchor`, ' ''
mutant chk_ci "ci.yml: Chromium and Pillow required" .github/workflows/ci.yml '      NUIKIT_REQUIRE_CHROME: "1"
' ''
mutant chk_ci "ci.yml: Chromium and Pillow required" .github/workflows/ci.yml '      NUIKIT_REQUIRE_PILLOW: "1"
' ''
mutant chk_ci "ci.yml: Chromium and Pillow required" .github/workflows/ci.yml '    timeout-minutes: 60
' ''
mutant chk_ci "ci.yml: Chromium and Pillow required" .github/workflows/ci.yml 'node-version: 22 ' 'node-version: 18 '
mutant chk_ci "ci.yml: Chromium and Pillow required" .github/workflows/ci.yml 'run: npx --yes playwright@${{ env.PLAYWRIGHT_VERSION }} install --with-deps chromium-headless-shell' 'run: echo skipped'

mutant chk_skill_run "skill: its commands run" "$SK/SKILL.md" '"$KIT"/bin/rml-check ui/menu.rml "$o/cases.json"' '"$KIT"/bin/rml-chek ui/menu.rml "$o/cases.json"'
mutant chk_skill_meta "skill: metadata as the Agent Skills spec says" "$SK/SKILL.md" 'name: open77-nativeui' 'name: open77-NativeUI'
mutant chk_links "docs: every link and" "$SK/SKILL.md" '[references/porting.md](references/porting.md): a WebUI' '[references/porting.md](references/port.md): a WebUI'
mutant chk_links "docs: every link and" "$SK/SKILL.md" '`$KIT/docs/cases.md`: the case format' '`$KIT/docs/case.md`: the case format'
mutant chk_output_forms "skill: references/output.md explains every kind" "$SK/references/output.md" '| `off screen at x,y` |' '| `outside at x,y` |'
mutant chk_private "agent docs: no home paths" AGENTS.md 'Instructions for agents changing open77-nui-kit itself.' 'Instructions for agents changing open77-nui-kit itself (clone in /home/someone/kit).'
echo "docs: $reds of $i mutants turn their check red"
[ "$reds" = "$i" ] || fail=1
exit $fail
