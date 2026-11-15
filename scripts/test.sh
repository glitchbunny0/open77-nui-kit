#!/usr/bin/env bash
# The kit's own tests. Built-in steps: lrbind (parity with real RmlUi, page protocol, Lua facade), html2rml (RmlUi facts,
# property table, fixtures), the example screen (cases from its client Lua, rml-check, the WebUI twin through html2rml,
# rml-preview of both when Pillow is there, html-shot of the twin when a Chromium is there). Then every tests/*.sh is a
# suite of its own (tests/README.md): fake-nui, html-shot, the example's states, ... each with a mutant per check.
#
# Needs: git, g++, python3, lua 5.4 ($LUA, else lua5.4 or lua), node 20.19+ (npm ci runs by itself); optional Pillow and
# Chromium (NUIKIT_CHROME or Playwright's headless shell). CI sets NUIKIT_REQUIRE_PILLOW=1 and NUIKIT_REQUIRE_CHROME=1:
# there, a missing one fails the run instead of skipping its steps.
set -euo pipefail
kit="$(cd "$(dirname "$0")/.." && pwd)"
cd "$kit"

LUA="${LUA:-}"
if [ -z "$LUA" ]; then
    for c in lua5.4 lua; do
        if command -v "$c" >/dev/null 2>&1 && "$c" -v 2>&1 | grep -q 'Lua 5\.4'; then LUA="$c"; break; fi
    done
fi
if [ -z "$LUA" ]; then
    echo "FAILED: Lua 5.4 not found (the binary is lua5.4 on Debian/Ubuntu, lua on Fedora/Arch/Homebrew); set LUA=/path/to/lua"
    exit 1
fi
export LUA

# every step writes into a directory of its own under one root, kept (and named) when something failed
root="$(mktemp -d)"
fail=0
trap '[ "$fail" = 0 ] && rm -rf "$root" || echo "(outputs kept in $root)"' EXIT
sub() { mktemp -d "$root/$1.XXXXXX"; }
step() { echo "== $1"; }
# quiet CMD...: the last line of its output when it passes, all of it when it fails
quiet() {
    local o
    if o=$("$@" 2>&1); then tail -n 1 <<<"$o"; else echo "$o"; fail=1; fi
}

bash scripts/build.sh >/dev/null

step "lrbind parity";   bin/lrbind-parity || fail=1
step "lrbind protocol"; quiet node lrbind/tests/protocol.test.mjs
step "lrbind lua";      quiet bash -c 'cd lrbind && exec "$0" tests/lrbind_lua.lua' "$LUA"
step "html2rml: the RmlUi facts it relies on"; python3 converter/tests/facts.py || fail=1
step "html2rml: property table";  python3 converter/tests/test_spec.py || fail=1
step "html2rml: fixtures (snapshot + rml-check)"; quiet python3 converter/tests/run.py

ex="$kit/examples/side-menu"
cases="$(sub cases)/cases.json"
step "example: cases from the client Lua"
(cd "$ex" && "$LUA" models.lua > "$cases" 2>/dev/null) || fail=1
ncases=$(python3 -c 'import json,sys; print(len(json.load(open(sys.argv[1]))))' "$cases" 2>/dev/null || echo 0)
[ "$ncases" -gt 0 ] || { echo "FAIL: no cases written"; fail=1; }
step "example: rml-check"
(cd "$ex" && ../../bin/rml-check ui/menu.rml "$cases") || fail=1

step "example: the WebUI twin (web/) through html2rml, then rml-check with the same cases"
tw="$(sub twin)"
cmp -s lrbind/lrbind.js "$ex/web/lrbind.js" || { echo "FAIL: examples/side-menu/web/lrbind.js differs from lrbind/lrbind.js"; fail=1; }
(cd "$ex" && ../../bin/html2rml web/index.html --out "$tw" --name menu >/dev/null \
    && ../../bin/rml-check "$tw/menu.rml" "$cases") || fail=1

fonts=kitraj=fonts/Rajdhani-Regular.ttf,fonts/Rajdhani-SemiBold.ttf
if python3 -c 'import PIL' 2>/dev/null; then
    step "example: rml-preview"
    out="$(sub preview)"
    (cd "$ex" && ../../bin/rml-preview ui/menu.rml "$cases" --font "$fonts" --out "$out" >/dev/null) || fail=1
    n=$(find "$out" -name '*.png' | wc -l)
    echo "$n images"; [ "$n" -eq $((ncases + 1)) ] || { echo "FAIL: want $((ncases + 1)) images (a PNG per state and the sheet)"; fail=1; }
    step "example: the converted twin lays out like the hand-written document"
    twp="$(sub twin-preview)"
    (cd "$ex" && ../../bin/rml-preview "$tw/menu.rml" "$cases" --font "$fonts" --out "$twp" >/dev/null) || fail=1
    python3 - "$out" "$twp" <<'EOF' || fail=1
import os, sys
from PIL import Image, ImageChops
a, b = sys.argv[1:]
names = sorted(n for n in os.listdir(a) if n.endswith('.png') and n != 'sheet.png')
diff = [n for n in names if not os.path.exists(os.path.join(b, n)) or ImageChops.difference(
    Image.open(os.path.join(a, n)).convert('RGB'), Image.open(os.path.join(b, n)).convert('RGB')).getbbox()]
print(f'{len(names) - len(diff)}/{len(names)} states pixel-identical' + (': differ ' + ', '.join(diff) if diff else ''))
sys.exit(1 if diff or not names else 0)
EOF
elif [ "${NUIKIT_REQUIRE_PILLOW:-}" = 1 ]; then
    step "example: rml-preview"; echo "FAIL: no Pillow and NUIKIT_REQUIRE_PILLOW=1"; fail=1
else
    echo "== rml-preview skipped (no Pillow)"
fi

if bin/html-shot --find >/dev/null 2>&1; then
    step "example: html-shot of the twin (Chromium found; every shot must have bound)"
    shots="$(sub shots)"
    (cd "$ex" && ../../bin/html-shot web/index.html "$cases" --out "$shots" >/dev/null) || fail=1
    n=$(find "$shots" -name '*.png' | wc -l)
    echo "$n shots"; [ "$n" -eq "$ncases" ] || { echo "FAIL: want $ncases shots"; fail=1; }
elif [ "${NUIKIT_REQUIRE_CHROME:-}" = 1 ]; then
    step "example: html-shot of the twin"
    echo "FAIL: no Chromium and NUIKIT_REQUIRE_CHROME=1 (set NUIKIT_CHROME, or npx playwright install chromium-headless-shell)"; fail=1
else
    echo "== html-shot skipped (no Chromium; optional here)"
fi

# Every tests/*.sh is its own suite (one per area, added by whoever owns that area): it runs from the kit root with
# NUIKIT (kit root), NUIKIT_TMP (a fresh empty dir for it alone) and LUA set, and fails by exiting non-zero.
for t in tests/*.sh; do
    [ -e "$t" ] || continue
    step "suite: $t"
    if NUIKIT="$kit" NUIKIT_TMP="$(sub "suite-$(basename "$t" .sh)")" bash "$t"; then :; else echo "FAIL: $t"; fail=1; fi
done
[ $fail = 0 ] && echo "ALL OK" || { echo "FAILED"; exit 1; }
