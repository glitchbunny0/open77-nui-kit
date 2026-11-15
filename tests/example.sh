#!/usr/bin/env bash
# The side-menu example: its client Lua run on fake-nui writes the states the example's README and screenshots show.
# Checks: models.lua runs, every state means what it says (tests/example/states.py: the confirm click charges the player,
# the bought row is owned, ...), the committed cases.json is what models.lua writes now, one resume stays cheap. Each is
# proven by a mutant: a copy of the example in $NUIKIT_TMP with ONE bug that must turn that check red. Contract:
# tests/README.md.
set -uo pipefail
kit="${NUIKIT:?run through scripts/test.sh}"; tmp="${NUIKIT_TMP:?}"
cd "$kit"
lua="${LUA:-$(command -v lua5.4 || command -v lua)}"
fail=0
limit=10000      # instructions of one resume or event; the game allows 1,500,000, the example needs about a tenth of this

# evaluate DIR: run DIR/examples/side-menu/models.lua, then print one "ok   what" / "FAIL what" line per check
evaluate() {
    local dir="$1/examples/side-menu"
    if ! (cd "$dir" && "$lua" models.lua > "$1/cases.json" 2> "$1/stderr"); then
        echo "FAIL cases: models.lua runs"; head -3 "$1/stderr" | sed 's/^/     /'; return
    fi
    echo "ok   cases: models.lua runs"
    python3 "$kit/tests/example/states.py" "$1/cases.json"
    if cmp -s "$1/cases.json" "$kit/examples/side-menu/cases.json"; then echo "ok   committed: cases.json is what models.lua writes"
    else echo "FAIL committed: cases.json is what models.lua writes"; fi
    local n
    n=$(sed -n 's/^max instructions in one resume or event: \([0-9]*\) .*/\1/p' "$1/stderr")
    if [ -n "$n" ] && [ "$n" -le "$limit" ]; then echo "ok   budget: one resume or event takes $n instructions (limit $limit)"
    else echo "FAIL budget: one resume or event takes ${n:-?} instructions (limit $limit)"; fi
}

copy() {   # a copy of the example and the fake it runs on, to break
    rm -rf "$1"; mkdir -p "$1/examples"
    cp -r examples/side-menu "$1/examples/side-menu"; cp -r fake-nui "$1/fake-nui"
}

copy "$tmp/real"
out=$(evaluate "$tmp/real")
grep -v '^ok ' <<<"$out" || true
echo "example: $(grep -c '^ok ' <<<"$out") checks ok"
grep -q '^FAIL' <<<"$out" && fail=1

# mutant NAME FILE OLD NEW: one edit to a copy of the example; the check starting with NAME must go red
i=0; reds=0
mutant() {
    local name="$1" file="$2" old="$3" new="$4"
    i=$((i + 1))
    local d="$tmp/m$i"
    copy "$d"
    if ! F="$d/examples/side-menu/$file" OLD="$old" NEW="$new" python3 - <<'PY'
import os, sys
f = os.environ['F']
s = open(f, encoding='utf-8').read()
if s.count(os.environ['OLD']) != 1:
    print('mutant site matches %d times: %r' % (s.count(os.environ['OLD']), os.environ['OLD'][:70])); sys.exit(1)
open(f, 'w', encoding='utf-8').write(s.replace(os.environ['OLD'], os.environ['NEW']))
PY
    then echo "FAIL: mutant $i ($name): the site is gone"; fail=1; return; fi
    local o
    o=$(evaluate "$d")
    if grep -q "^FAIL $name" <<<"$o"; then reds=$((reds + 1))
    else echo "FAIL: mutant $i did not turn '$name' red"; grep -v '^ok ' <<<"$o" | head -4; fail=1; fi
}

mutant "cases: models.lua runs" client/menu.lua 'ui:focus()
    return ui' 'ui:nope()
    return ui'
mutant "states: the six states" models.lua 'state("empty", { { "tab", "ammo" } })
' ''
mutant "states: every model carries" client/menu.lua 'place = "", cash' 'place = "", extra = 1, cash'
mutant "browse: the shop" client/menu.lua 'tab = s.tabs[1].id' 'tab = s.tabs[2].id'
mutant "browse: the guns tab" models.lua '{ id = "lexington", tab = "guns"' '{ id = "lexington", tab = "mods"'
mutant "picked: the Overture" client/menu.lua 'state.cash >= it.price })' 'state.cash < it.price })'
mutant "confirm: the dialog is open" client/menu.lua 'ui:merge(MODEL, { askOn = true,' 'ui:merge(MODEL, { askOn = false,'
mutant "confirm: the dialog is open" client/menu.lua '"Paid from your cash. You keep " .. money(state.cash - it.price)' '"Paid from your cash. You keep " .. money(state.cash)'
mutant "confirm: nothing is charged or owned yet" client/menu.lua 'own = state.owned[it.id] == true' 'own = true'
mutant "bought: the player was charged" client/menu.lua 'state.cash, state.owned[it.id] = state.cash - it.price, true' 'state.cash, state.owned[it.id] = state.cash, true'
mutant "bought: the Unity (and only it) is marked owned" client/menu.lua 'state.cash - it.price, true' 'state.cash - it.price, false'
mutant "bought: the dialog is closed and the owned item" client/menu.lua 'canBuy = it ~= nil and not state.owned[it.id] and state.cash' 'canBuy = it ~= nil and state.cash'
mutant "empty: the ammo tab" models.lua '{ id = "scope", tab = "mods"' '{ id = "scope", tab = "ammo"'
mutant "mods: the mods tab" models.lua '{ id = "scope", tab = "mods"' '{ id = "scope", tab = "guns"'
mutant "clicks: browse, picked and confirm" models.lua '{ "#foot .buy", "buy", {} }' '{ "#foot .buy2", "buy", {} }'
mutant "committed: cases.json is what models.lua writes" models.lua 'Reliable 9 mm. The street standard.' 'Reliable 9mm. The street standard.'
mutant "budget: one resume or event" client/menu.lua 'function Menu.open(s, cash)
' 'function Menu.open(s, cash)
    for _ = 1, 20000 do end
'
mutant "budget: one resume or event" models.lua 'io.stderr:write(("max instructions in one resume or event: %d (%s)\n"):format(F.maxInstr, F.maxWhere))' ''

echo "example: $reds of $i mutants turn their check red"
[ "$reds" = "$i" ] || fail=1
exit $fail
