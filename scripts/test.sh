#!/usr/bin/env bash
# The kit's own tests: lrbind (parity with real RmlUi, page protocol, Lua facade), fake-nui, the example screen through
# rml-check, a mutation the check must catch, and an rml-preview smoke run (when Pillow is there).
set -euo pipefail
kit="$(cd "$(dirname "$0")/.." && pwd)"
cd "$kit"
bash scripts/build.sh >/dev/null
fail=0
step() { echo "== $1"; }
step "lrbind parity";   bin/lrbind-parity || fail=1
step "lrbind protocol"; node lrbind/tests/protocol.test.mjs | tail -1 || fail=1
step "lrbind lua";      (cd lrbind && lua5.4 tests/lrbind_lua.lua | tail -1) || fail=1
step "example: cases from the client Lua"
(cd examples/side-menu && lua5.4 models.lua > "${TMPDIR:-/tmp}/nuikit-cases.json") || fail=1
step "example: rml-check"
(cd examples/side-menu && ../../bin/rml-check ui/menu.rml "${TMPDIR:-/tmp}/nuikit-cases.json") || fail=1
step "example: rml-check must fail on a broken binding and a wrong event"
mut="examples/side-menu/ui/_mutant.rml"
sed 's/{{r.price}}/{{r.prise}}/; s/data-event-click="buy()"/data-event-click="buy2()"/' examples/side-menu/ui/menu.rml > "$mut"
if (cd examples/side-menu && ../../bin/rml-check ui/_mutant.rml "${TMPDIR:-/tmp}/nuikit-cases.json" --quiet >/dev/null); then
    echo "FAIL: the mutant passed"; fail=1
else echo "ok: the mutant failed"; fi
rm -f "$mut"
if python3 -c 'import PIL' 2>/dev/null; then
    step "example: rml-preview"
    out="${TMPDIR:-/tmp}/nuikit-preview"
    (cd examples/side-menu && ../../bin/rml-preview ui/menu.rml "${TMPDIR:-/tmp}/nuikit-cases.json" \
        --font kitraj=fonts/Rajdhani-Regular.ttf,fonts/Rajdhani-SemiBold.ttf --out "$out" >/dev/null) || fail=1
    n=$(ls "$out"/*.png | wc -l); echo "$n images"; [ "$n" -ge 7 ] || fail=1
else
    echo "== rml-preview skipped (no Pillow)"
fi
[ $fail = 0 ] && echo "ALL OK" || { echo "FAILED"; exit 1; }
