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
mutant "instruction counter: a direct call" 'counted("event " .. name, nil, function()' '(function(w, c, f) return f() end)("event " .. name, nil, function()'
mutant "budget: 1,500,000" 'budget = 1500000,' 'budget = 150000,'
mutant "budget: a resume past it" 'if limit and n > limit then error("Open77 script execution budget exceeded", 0) end' ''
mutant "counted: the hook is restored" 'table.pack(pcall(fn, ...))' 'table.pack(true, fn(...))'

# documents and models
mutant "set: a documented path" '        t[key] = v
' '        d.model[path] = v
'
mutant "set: a path that leads nowhere" 'assert(not mustExist or t[last] ~= nil,' 'assert(true or t[last] ~= nil,'
mutant "set: a path that leads nowhere" 'assert(type(t) == "table", "model path "' 'assert(true, "model path "'
mutant "set, push, merge: an unknown model" 'assert(model, m .. " into an unknown model " .. tostring(mn))' 'model = model or d.model'
mutant "push appends" 't[key][#t[key] + 1] = v' 'table.insert(t[key], 1, v)'
mutant "push appends" 'assert(type(t[key]) == "table", "push to "' 'assert(true, "push to "'
mutant "removeAt removes" 'table.remove(arr, i)' 'table.remove(arr)'
mutant "removeAt removes" 'i <= #arr,' 'i <= #arr + 1,'
mutant "removeAt removes" 'i >= 1 and' 'i >= 0 and'
mutant "models: every model" '        d.models[n] = m
' '        if not next(d.models) then d.models[n] = m end
'
mutant "models: every model" 'assert(model[k] ~= nil, "merge of a field the model "' 'assert(true, "merge of a field the model "'
mutant "F.case: a document with several models" 'if m ~= doc.model then' 'if false then'
mutant "create accepts source" 'if opts.document and not exists(opts.document)' 'if not exists(opts.document)'
mutant "create accepts source" '(type(opts.document) == "string") ~= (type(opts.source) == "string")' '(type(opts.document) == "string") or (type(opts.source) == "string")'
mutant "create: a document file that does not exist" 'return nil, "undeclared_file:" .. opts.document' 'return nil, "undeclared"'

# focus, events, listeners
mutant "focus: hide() releases it" 'self.visible = false; release("released"); return true end' 'self.visible = false; return true end'
mutant "focus: blur() releases it" 'rec("blur"); release("released"); return true end' 'rec("blur"); return true end'
mutant "focus: destroy() releases it" '        self.visible = false
        release("released")' '        self.visible = false'
mutant "focus: destroy() releases it" '        fire("event", "closed", "closed", {})
' ''
mutant "focus: focus() takes it and tells the document once" 'if not self.focused then self.focused = true; fire("event", "focus", "focus", {}) end' 'self.focused = true; fire("event", "focus", "focus", {})'
mutant "focus: another surface taking it" 'release(reason or "taken", by)' 'release("released", by)'
mutant "focus: a refused focus" '        fire("event", "error", "focus", { message = why })   -- the document is told as well
' ''
mutant "events: F.loaded fires loaded" 'd.loaded = true; counted("loaded"' 'counted("loaded"'
mutant "model events: every listener" '        d.fire("model", "*", name, table.unpack(args, 1, args.n))
' ''
mutant "model events: every listener" 'if l.id == id then table.remove(list, i); return true end' 'if l.id == id then return true end'
mutant "DOM events: F.key / F.emit" 'F.emit(d, "keydown", { key = key, type = "keydown" })' 'F.emit(d, "keyup", { key = key, type = "keydown" })'
mutant "documented methods (DOM, motion, scene) exist" '"blurElement", "scrollTo",' '"blurElement",'
mutant "documented methods (DOM, motion, scene) exist" 'live(name); rec(name, ...); return true end' 'live(name); return true end'
mutant "documented methods (DOM, motion, scene) exist" 'live(name); rec(name, ...); return true end' 'rec(name, ...); return true end'
mutant "documented methods: set/push/removeAt/merge record" 'rec("set", mn, path, v)' 'rec("set", mn, path)'
mutant "documented methods: create returns" 'serial = serial + 1; return "@" .. serial' 'return "@" .. serial'
mutant "documented methods: create returns" 'rec("rect", sel); return nil end' 'rec("rect", sel); return {} end'
mutant "documented methods: create returns" 'focused = d.focused,' 'focused = true,'
mutant "documented methods: reload fires reloaded" 'fire("event", "reloaded", "reloaded", {})' ''
mutant "create: a resource owns at most 32" 'if open >= 32 then' 'if open >= 33 then'
mutant "create: a resource owns at most 32" 'if not x.destroyed then open = open + 1 end' 'open = open + 1'
mutant "Open77.ui: registerEffect records" 'F.effects[name] = hlsl' ''
mutant "Open77.ui: registerEffect records" 'return nil, "invalid_effect"' 'return nil, "x"'
mutant "Open77.ui: registerEffect records" '{ path, family, fallback }' '{ path, family }'

# F.json
mutant "json: strings, escapes" 'table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)' 'table.sort(keys, function(a, b) return tostring(a) > tostring(b) end)'
mutant "json: strings, escapes" 'if count == 0 or v[1] ~= nil then' 'if v[1] ~= nil then'
mutant "json: floats keep every digit" 'for digits = 15, 17 do' 'for digits = 6, 6 do'
mutant "json: floats keep every digit" 'return s:find("[%.eE]") and s or (s .. ".0")' 'return s'
mutant "json: NaN and infinity" 'if v ~= v or v == math.huge or v == -math.huge then' 'if v ~= v then'
mutant "json: NaN and infinity" 'if v ~= v or v == math.huge or v == -math.huge then' 'if v == math.huge or v == -math.huge then'
mutant "json: a table mixing" 'if count ~= #v then error(' 'if false then error('
mutant "json: a function" '    error("F.json: a " .. t .. " at " .. path .. " is not JSON", 0)' '    return "null"'

exit $fail
