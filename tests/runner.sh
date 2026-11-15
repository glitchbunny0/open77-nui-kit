#!/usr/bin/env bash
# scripts/test.sh itself, run on a stub kit (every tool a stub, so each behaviour is isolated): a red step prints its
# FAIL lines (no `| tail -1` traps), a step that writes nothing is a FAILED line and not an abort, stale files in TMPDIR
# cannot satisfy a step, Lua is found as lua5.4 or lua, a missing Chromium / Pillow is a skip locally and a failure with
# NUIKIT_REQUIRE_CHROME / NUIKIT_REQUIRE_PILLOW, and outputs are removed when green, kept and named when red. Each check
# has a mutant (a copy of test.sh with ONE bug). Contract: tests/README.md.
set -uo pipefail
kit="${NUIKIT:?run through scripts/test.sh}"; tmp="${NUIKIT_TMP:?}"
cd "$kit"
fail=0
have_pil=0; python3 -c 'import PIL' 2>/dev/null && have_pil=1
lua54=$(command -v lua5.4 || command -v lua)

# ---- the stub kit ----
stub="$tmp/stub"
mkdir -p "$stub"/{scripts,bin,lrbind/tests,converter/tests,examples/side-menu/{ui,web,fonts},tests,stubbin,nolua}
echo 'exit 0' > "$stub/scripts/build.sh"
for t in lrbind-parity rml-check; do printf '#!/bin/sh\necho "%s ok"\n' "$t" > "$stub/bin/$t"; done
cat > "$stub/bin/html2rml" <<'EOF'
#!/bin/sh
while [ $# -gt 0 ]; do [ "$1" = --out ] && out="$2"; shift; done
mkdir -p "$out"; echo "<rml/>" > "$out/menu.rml"
EOF
cat > "$stub/bin/rml-preview" <<'EOF'
#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
out = a[a.index('--out') + 1]
os.makedirs(out, exist_ok=True)
names = [c['name'] for c in json.load(open(a[1]))]
mode = os.environ.get('STUB_PREVIEW', 'all')
from PIL import Image
for n in ([] if mode == 'none' else names[:-1] if mode == 'skiplast' else names) + ([] if mode == 'none' else ['sheet']):
    Image.new('RGB', (4, 4), (10, 20, 30)).save(os.path.join(out, n + '.png'))
EOF
cat > "$stub/bin/html-shot" <<'EOF'
#!/usr/bin/env python3
import json, os, sys
a = sys.argv[1:]
if a == ['--find']:
    if os.environ.get('STUB_CHROME') == 'none':
        print('none'); sys.exit(2)
    print('/stub/chrome'); sys.exit(0)
out = a[a.index('--out') + 1]
os.makedirs(out, exist_ok=True)
for c in json.load(open(a[1])):
    open(os.path.join(out, c['name'] + '.png'), 'wb').write(b'x')
EOF
chmod +x "$stub"/bin/*
echo 'print("lua facade: 3 passed")' > "$stub/lrbind/tests/lrbind_lua.lua"
for f in facts test_spec run; do echo 'print("%s ok")' | sed "s/%s/$f/" > "$stub/converter/tests/$f.py"; done
echo 'io.write("[{\"name\":\"one\"},{\"name\":\"two\"}]\n")' > "$stub/examples/side-menu/models.lua"
echo 'var a;' > "$stub/lrbind/lrbind.js"; cp "$stub/lrbind/lrbind.js" "$stub/examples/side-menu/web/lrbind.js"
echo '<html/>' > "$stub/examples/side-menu/web/index.html"
echo '<rml/>' > "$stub/examples/side-menu/ui/menu.rml"
echo 'echo "stub suite ran"' > "$stub/tests/ok.sh"
# the tools the stub kit's PATH holds: the basics (nolua/), Lua under the name Fedora gives it (stubbin/), python3 through a
# wrapper (a venv's python must be started by its own path)
mkdir -p "$stub/nolua"
for t in bash cat cmp cp find grep ls mkdir mktemp node rm sed sort tail wc env dirname basename readlink sleep head tr; do
    ln -sf "$(command -v $t)" "$stub/nolua/$t"
done
printf '#!/bin/sh\nexec "%s" "$@"\n' "$(command -v python3)" > "$stub/nolua/python3"; chmod +x "$stub/nolua/python3"
ln -s "$lua54" "$stub/stubbin/lua"

good_protocol() { echo 'console.log("protocol: 3 passed")' > "$stub/lrbind/tests/protocol.test.mjs"; }
bad_protocol() { echo 'console.log("FAIL a check of the protocol suite"); console.log("protocol: 1 passed, 1 failed"); process.exitCode = 1' > "$stub/lrbind/tests/protocol.test.mjs"; }

# run the stub kit's test.sh: sets $out and $rc; env VARS before it
runner() { out=$(cd "$stub" && env -u NUIKIT_REQUIRE_CHROME -u NUIKIT_REQUIRE_PILLOW "$@" bash scripts/test.sh 2>&1) && rc=0 || rc=$?; }   # CI's own NUIKIT_REQUIRE_* must not leak into the stub runs

# ---- the checks (on a given test.sh) ----
runner_checks() {   # runner_checks TESTSH
    local sh="$1"
    cp "$sh" "$stub/scripts/test.sh"
    rm -rf "$stub/tmp"; mkdir -p "$stub/tmp"
    local P="PATH=$stub/stubbin:$stub/nolua:$stub/bin"      # only the stub tools and the basics

    good_protocol
    runner "$P" TMPDIR="$stub/tmp" LUA= STUB_CHROME=ok
    want "runner: a green stub kit is ALL OK, exit 0" bash -c '[ "$1" = 0 ] && grep -q "^ALL OK" <<<"$2" && grep -q "stub suite ran" <<<"$2"' _ "$rc" "$out"
    want "runner: Lua found under the name lua (Fedora)" bash -c 'grep -q "lua facade: 3 passed" <<<"$1"' _ "$out"
    want "runner: outputs are removed when green" bash -c '[ -z "$(ls "$1")" ]' _ "$stub/tmp"

    bad_protocol
    runner "$P" TMPDIR="$stub/tmp" LUA= STUB_CHROME=ok
    want "runner: a red suite step prints its FAIL lines, not just the last line" bash -c '[ "$1" = 1 ] && grep -q "^FAIL a check of the protocol suite" <<<"$2" && grep -q "^FAILED" <<<"$2"' _ "$rc" "$out"
    want "runner: ... and names the kept outputs" bash -c 'grep -q "outputs kept in $1" <<<"$2" && ls -d "$1"/*/ >/dev/null 2>&1' _ "$stub/tmp" "$out"
    rm -rf "$stub/tmp"; mkdir -p "$stub/tmp"
    good_protocol

    runner "$P" TMPDIR="$stub/tmp" LUA= PATH="$stub/nolua:$stub/bin" STUB_CHROME=ok
    want "runner: no Lua 5.4 is FAILED with a hint, exit 1" bash -c '[ "$1" = 1 ] && grep -q "Lua 5.4 not found" <<<"$2" && grep -q "lua5.4 on Debian" <<<"$2"' _ "$rc" "$out"

    runner "$P" TMPDIR="$stub/tmp" LUA= STUB_CHROME=none
    want "runner: no Chromium is a skip, still ALL OK" bash -c '[ "$1" = 0 ] && grep -q "html-shot skipped" <<<"$2" && grep -q "^ALL OK" <<<"$2"' _ "$rc" "$out"
    runner "$P" TMPDIR="$stub/tmp" LUA= STUB_CHROME=none NUIKIT_REQUIRE_CHROME=1
    want "runner: no Chromium with NUIKIT_REQUIRE_CHROME=1 is a FAIL" bash -c '[ "$1" = 1 ] && grep -q "NUIKIT_REQUIRE_CHROME=1" <<<"$2" && grep -q "^FAILED" <<<"$2"' _ "$rc" "$out"

    if [ "$have_pil" = 1 ]; then
        runner "$P" TMPDIR="$stub/tmp" LUA= STUB_CHROME=ok STUB_PREVIEW=none
        want "runner: a preview that writes no PNG is a FAILED line, not an abort" bash -c '[ "$1" = 1 ] && grep -q "^FAILED" <<<"$2" && grep -q "stub suite ran" <<<"$2"' _ "$rc" "$out"
        # stale outputs of an earlier run in TMPDIR, under the old fixed names, must not satisfy the step
        python3 - "$stub/tmp" <<'PY'
import os, sys
from PIL import Image
for d in ('nuikit-preview', 'nuikit-twin-preview', 'nuikit-twin', 'nuikit-shots'):
    os.makedirs(os.path.join(sys.argv[1], d), exist_ok=True)
    for n in ('one', 'two') + (() if d == 'nuikit-shots' else ('sheet',)):
        Image.new('RGB', (4, 4), (10, 20, 30)).save(os.path.join(sys.argv[1], d, n + '.png'))
PY
        runner "$P" TMPDIR="$stub/tmp" LUA= STUB_CHROME=ok STUB_PREVIEW=none
        want "runner: stale PNGs in TMPDIR do not satisfy a preview that wrote none" bash -c '[ "$1" = 1 ] && grep -q "^FAILED" <<<"$2"' _ "$rc" "$out"
        rm -rf "$stub/tmp"; mkdir -p "$stub/tmp"
        runner "$P" TMPDIR="$stub/tmp" LUA= STUB_CHROME=ok STUB_PREVIEW=skiplast
        want "runner: a preview that skips a state is a FAIL (the count is the cases + the sheet)" bash -c '[ "$1" = 1 ] && grep -q "want 3 images" <<<"$2"' _ "$rc" "$out"
    else
        echo "skip runner: the preview checks (no Pillow)"
    fi
}

want() { local name="$1"; shift; if "$@"; then echo "ok   $name"; else echo "FAIL $name"; fi; }

real_out=$(runner_checks scripts/test.sh)
grep -v '^ok ' <<<"$real_out" && fail=1
echo "runner: $(grep -c '^ok ' <<<"$real_out") checks ok on the real scripts/test.sh"

# ---- mutants ----
i=0; reds=0
mutant() {   # mutant NAME OLD NEW
    local name="$1" old="$2" new="$3"
    i=$((i + 1))
    local f="$tmp/mutant$i.sh"
    if ! SRC=scripts/test.sh DST="$f" OLD="$old" NEW="$new" python3 - <<'PY'
import os, sys
s = open(os.environ['SRC'], encoding='utf-8').read()
if s.count(os.environ['OLD']) != 1:
    print('mutant site matches %d times: %r' % (s.count(os.environ['OLD']), os.environ['OLD'][:70])); sys.exit(1)
open(os.environ['DST'], 'w', encoding='utf-8').write(s.replace(os.environ['OLD'], os.environ['NEW']))
PY
    then echo "FAIL: mutant $i ($name): the site is gone"; fail=1; return; fi
    local o
    o=$(runner_checks "$f")
    if grep -q "^FAIL $name" <<<"$o"; then reds=$((reds + 1))
    else echo "FAIL: mutant $i did not turn '$name' red"; grep -v '^ok ' <<<"$o" | head -4; fail=1; fi
}

mutant "runner: a green stub kit" 'sub() { mktemp -d "$root/$1.XXXXXX"; }' 'sub() { mktemp -d "$root/$1.XXXXXX"; false; }'
mutant "runner: Lua found under the name lua" 'for c in lua5.4 lua; do' 'for c in lua5.4; do'
mutant "runner: outputs are removed when green" 'trap '"'"'[ "$fail" = 0 ] && rm -rf "$root" || echo "(outputs kept in $root)"'"'"' EXIT' 'trap '"'"'echo "(outputs kept in $root)"'"'"' EXIT'
mutant "runner: a red suite step prints its FAIL lines" 'if o=$("$@" 2>&1); then tail -n 1 <<<"$o"; else echo "$o"; fail=1; fi' 'if o=$("$@" 2>&1); then tail -n 1 <<<"$o"; else tail -n 1 <<<"$o"; fail=1; fi'
mutant "runner: ... and names the kept outputs" 'echo "(outputs kept in $root)"' 'echo "(outputs removed)"; rm -rf "$root"'
mutant "runner: no Lua 5.4 is FAILED with a hint" 'if [ -z "$LUA" ]; then
    echo "FAILED' 'if false; then
    echo "FAILED'
mutant "runner: no Chromium is a skip" 'elif [ "${NUIKIT_REQUIRE_CHROME:-}" = 1 ]; then' 'elif true; then'
mutant "runner: no Chromium with NUIKIT_REQUIRE_CHROME=1" 'elif [ "${NUIKIT_REQUIRE_CHROME:-}" = 1 ]; then' 'elif false; then'
mutant "runner: a preview that writes no PNG" "n=\$(find \"\$out\" -name '*.png' | wc -l)" "n=\$(ls \"\$out\"/*.png | wc -l)"
mutant "runner: stale PNGs in TMPDIR" 'sub() { mktemp -d "$root/$1.XXXXXX"; }' 'sub() { mkdir -p "${TMPDIR:-/tmp}/nuikit-$1"; echo "${TMPDIR:-/tmp}/nuikit-$1"; }'
mutant "runner: a preview that skips a state" '[ "$n" -eq $((ncases + 1)) ]' '[ "$n" -ge 1 ]'

echo "runner: $reds of $i mutants turn their check red"
[ "$reds" = "$i" ] || fail=1
exit $fail
