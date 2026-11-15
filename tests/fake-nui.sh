#!/usr/bin/env bash
# fake-nui's own tests: tests/fake-nui/checks.lua on the real fake_nui.lua, then on broken copies (one bug each) that
# must each turn the named check red. Suite contract: tests/README.md.
set -uo pipefail
kit="${NUIKIT:?run through scripts/test.sh}"; tmp="${NUIKIT_TMP:?}"
cd "$kit"
lua="${LUA:-$(command -v lua5.4 || command -v lua)}"
fail=0
real=fake-nui/fake_nui.lua
checks=tests/fake-nui/checks.lua

out=$("$lua" "$checks" "$real") && rc=0 || rc=$?
echo "$out" | grep -v '^ok ' || true
n=$(echo "$out" | grep -c '^ok ' || true)
if [ "$rc" != 0 ]; then echo "FAIL: fake-nui checks on the real file"; fail=1; fi
echo "fake-nui: $n checks ok on the real file"

# mutant CHECK OLD NEW: one edit to a copy of fake_nui.lua; the check whose name starts with CHECK must go red
i=0
mutant() {
    local name="$1" old="$2" new="$3"
    i=$((i + 1))
    local f="$tmp/mutant$i.lua"
    if ! SRC="$real" DST="$f" OLD="$old" NEW="$new" python3 - <<'PY'
import os, sys
s = open(os.environ['SRC'], encoding='utf-8').read()
if s.count(os.environ['OLD']) != 1:
    print('mutant site matches %d times: %r' % (s.count(os.environ['OLD']), os.environ['OLD'][:70])); sys.exit(1)
open(os.environ['DST'], 'w', encoding='utf-8').write(s.replace(os.environ['OLD'], os.environ['NEW']))
PY
    then echo "FAIL: mutant $i ($name): the site is gone"; fail=1; return; fi
    local o
    o=$("$lua" "$checks" "$f" 2>&1) && rc=0 || rc=$?
    if [ "$rc" != 0 ] && echo "$o" | grep -q "^FAIL $name"; then echo "ok   mutant -> red: $name"
    else echo "FAIL: mutant $i did not turn '$name' red (rc $rc)"; echo "$o" | grep -v '^ok ' | head -5; fail=1; fi
}

# the scheduler
mutant "wait: a thread wakes after its time" 'F.now + math.max(0, ms or 0)' 'F.now'
mutant "wait: Wait(0) resumes on a later pass" 'coroutine.yield()
    end
    local timers' 'if ms ~= 0 then coroutine.yield() end
    end
    local timers'
mutant "wait: waiting threads wake by wake time" 'if x.w.at ~= y.w.at then return x.w.at < y.w.at end return x.w.seq < y.w.seq end' 'return x.w.seq < y.w.seq end'
mutant "wait: waiting threads wake by wake time" 'return x.w.seq < y.w.seq end)' 'return x.w.seq > y.w.seq end)'
mutant "CreateThread starts the task on the next pass" 'wake[co] = { at = F.now, seq = seq }
        return co' 'wake[co] = { at = F.now, seq = seq }
        resume(co, "thread start")
        return co'
mutant "SetTimeout fires once after its time" 'Wait(ms); if timers[id]' 'Wait(0); if timers[id]'
mutant "SetTimeout fires once after its time" 'timers[id] = nil; return had end' 'return had end'
mutant "GetGameTimer follows the passes" 'GetGameTimer = function() return F.now end' 'GetGameTimer = function() return 0 end'
mutant "print keeps every argument" 'table.concat(t, "\t", 1, t.n)' 'table.concat(t, "\t", 1, 1)'
# the instruction counter
mutant "instruction counter: a resume's" 'n = n + STEP' 'n = n + 0'
mutant "instruction counter: a direct call" 'counted("event " .. name, nil, fn, ...)' 'fn(...)'
mutant "budget: 1,500,000" 'budget = 1500000 }' 'budget = 150000 }'
mutant "budget: a resume past it" 'if limit and n > limit then error("Open77 script execution budget exceeded", 0) end' ''
mutant "counted: the hook is restored" 'table.pack(pcall(fn, ...))' 'table.pack(true, fn(...))'

exit $fail
