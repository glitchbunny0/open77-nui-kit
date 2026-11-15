#!/usr/bin/env bash
# The kit's own tests: lrbind (parity with real RmlUi, page protocol, Lua facade), html2rml (RmlUi facts, fixtures),
# fake-nui, the example screen through rml-check, a mutation the check must catch, and an rml-preview smoke run (when
# Pillow is there).
set -euo pipefail
kit="$(cd "$(dirname "$0")/.." && pwd)"
cd "$kit"
bash scripts/build.sh >/dev/null
fail=0
step() { echo "== $1"; }
step "lrbind parity";   bin/lrbind-parity || fail=1
step "lrbind protocol"; node lrbind/tests/protocol.test.mjs | tail -1 || fail=1
step "lrbind lua";      (cd lrbind && lua5.4 tests/lrbind_lua.lua | tail -1) || fail=1
step "html2rml: the RmlUi facts it relies on"; python3 converter/tests/facts.py || fail=1
step "html2rml: property table";  python3 converter/tests/test_spec.py || fail=1
step "html2rml: fixtures (snapshot + rml-check)"
if out=$(python3 converter/tests/run.py 2>&1); then echo "$out" | tail -1; else echo "$out"; fail=1; fi
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
step "example: the WebUI twin (web/) through html2rml, then rml-check with the same cases"
tw="${TMPDIR:-/tmp}/nuikit-twin"
cmp -s lrbind/lrbind.js examples/side-menu/web/lrbind.js || { echo "FAIL: examples/side-menu/web/lrbind.js differs from lrbind/lrbind.js"; fail=1; }
(cd examples/side-menu && ../../bin/html2rml web/index.html --out "$tw" --name menu >/dev/null \
    && ../../bin/rml-check "$tw/menu.rml" "${TMPDIR:-/tmp}/nuikit-cases.json") || fail=1
if python3 -c 'import PIL' 2>/dev/null; then
    step "example: rml-preview"
    out="${TMPDIR:-/tmp}/nuikit-preview"
    (cd examples/side-menu && ../../bin/rml-preview ui/menu.rml "${TMPDIR:-/tmp}/nuikit-cases.json" \
        --font kitraj=fonts/Rajdhani-Regular.ttf,fonts/Rajdhani-SemiBold.ttf --out "$out" >/dev/null) || fail=1
    n=$(ls "$out"/*.png | wc -l); echo "$n images"; [ "$n" -ge 7 ] || fail=1
    step "example: the converted twin lays out like the hand-written document"
    (cd examples/side-menu && ../../bin/rml-preview "$tw/menu.rml" "${TMPDIR:-/tmp}/nuikit-cases.json" \
        --font kitraj=fonts/Rajdhani-Regular.ttf,fonts/Rajdhani-SemiBold.ttf --out "$tw/png" >/dev/null) || fail=1
    python3 - "$out" "$tw/png" <<'EOF' || fail=1
import os, sys
from PIL import Image, ImageChops
a, b = sys.argv[1:]
names = sorted(n for n in os.listdir(a) if n.endswith('.png') and n != 'sheet.png')
diff = [n for n in names if ImageChops.difference(Image.open(os.path.join(a, n)).convert('RGB'),
                                                  Image.open(os.path.join(b, n)).convert('RGB')).getbbox()]
print(f'{len(names) - len(diff)}/{len(names)} states pixel-identical' + (': differ ' + ', '.join(diff) if diff else ''))
sys.exit(1 if diff else 0)
EOF
else
    echo "== rml-preview skipped (no Pillow)"
fi
[ $fail = 0 ] && echo "ALL OK" || { echo "FAILED"; exit 1; }
