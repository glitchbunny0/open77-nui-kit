-- The checks of fake-nui itself: lua5.4 tests/fake-nui/checks.lua <path to fake_nui.lua>.
-- One line per check ("ok   name" / "FAIL name: why"); exit 1 when any failed. tests/fake-nui.sh runs it on the real
-- file and on broken copies (one bug each) that must turn exactly the named check red.
local path = assert(arg[1], "usage: checks.lua <fake_nui.lua>")
local failed = 0
local function say(s) io.write(s, "\n") end   -- print is the fake's

-- a fresh fake for every check (the file keeps its state in upvalues, so it is loaded again)
local function fresh()
    CreateThread, Wait, SetTimeout, ClearTimeout, GetGameTimer, Open77 = nil, nil, nil, nil, nil, nil
    local F = dofile(path)
    F.install()
    return F
end

local function check(name, fn)
    local ok, err = pcall(fn)
    if ok then say("ok   " .. name)
    else failed = failed + 1; say("FAIL " .. name .. ": " .. tostring(err)) end
end

local function eq(got, want, what)
    if got ~= want then error((what or "value") .. ": got " .. tostring(got) .. ", want " .. tostring(want), 2) end
end

local function list(t) return table.concat(t, ",") end

-- ---- the scheduler ----

check("wait: a thread wakes after its time and not before", function()
    local F = fresh()
    local o = {}
    CreateThread(function() o[#o + 1] = "start"; Wait(50); o[#o + 1] = "woke" end)
    F.frames(1)
    eq(list(o), "start", "after the first pass")
    F.frames(2)                       -- 48 ms in: still waiting
    eq(list(o), "start", "before the wait is over")
    F.frames(2)                       -- 80 ms in
    eq(list(o), "start,woke", "after the wait")
end)

check("wait: Wait(0) resumes on a later pass, not in the same one", function()
    local F = fresh()
    local o = {}
    CreateThread(function() o[#o + 1] = "a"; Wait(0); o[#o + 1] = "b" end)
    F.frames(1)
    eq(list(o), "a")
    F.frames(1)
    eq(list(o), "a,b")
end)

check("wait: waiting threads wake by wake time, then by creation order", function()
    local F = fresh()
    local o, started = {}, {}
    local function task(name, ms) CreateThread(function() started[#started + 1] = name; Wait(ms); o[#o + 1] = name end) end
    task("slow", 100); task("fast", 50); task("fast2", 50); task("fast3", 50)
    F.frames(1)                        -- all four started (in creation order) and waiting
    eq(list(started), "slow,fast,fast2,fast3", "start order")
    F.now = F.now + 200                -- ... and due in the same pass
    F.frames(1)
    eq(list(o), "fast,fast2,fast3,slow", "wake order")
end)

check("CreateThread starts the task on the next pass, also from inside a thread", function()
    local F = fresh()
    local o = {}
    CreateThread(function()
        o[#o + 1] = "outer"
        CreateThread(function() o[#o + 1] = "inner" end)
        o[#o + 1] = "outer end"
    end)
    o[#o + 1] = "after CreateThread"
    eq(list(o), "after CreateThread", "before any pass")
    F.frames(1)
    eq(list(o), "after CreateThread,outer,outer end", "first pass")
    F.frames(1)
    eq(list(o), "after CreateThread,outer,outer end,inner", "second pass")
end)

check("SetTimeout fires once after its time; ClearTimeout cancels it", function()
    local F = fresh()
    local o = {}
    SetTimeout(40, function() o[#o + 1] = "fired" end)
    local id = SetTimeout(40, function() o[#o + 1] = "cleared" end)
    eq(ClearTimeout(id), true, "ClearTimeout result")
    F.frames(3)                       -- 48 ms in; the timers run at 56
    eq(#o, 0, "before the time")
    F.frames(5)
    eq(list(o), "fired")
    F.frames(5)
    eq(list(o), "fired", "fires once")
end)

check("GetGameTimer follows the passes", function()
    local F = fresh()
    F.frames(3)
    eq(GetGameTimer(), 48)
end)

check("F.frames() is one pass of 16 ms, F.settle() sixty, F.advance(ms) as many as cover the time", function()
    local F = fresh()
    F.frames(); eq(GetGameTimer(), 16, "F.frames()")
    F.settle(); eq(GetGameTimer(), 16 + 60 * 16, "F.settle()")
    local t = GetGameTimer()
    F.advance(40); eq(GetGameTimer(), t + 48, "F.advance(40)")
end)

check("print keeps every argument", function()
    local F = fresh()
    F.quiet = true
    print("clicked", "unity", 3, nil, true)
    eq(F.logs[1], "clicked\tunity\t3\tnil\ttrue")
end)

-- ---- the instruction counter ----

local function loop(n) local x = 0 for i = 1, n do x = x + i end return x end

check("instruction counter: a resume's instructions are counted, in a plausible range", function()
    local F = fresh()
    CreateThread(function() loop(10000) end)
    F.frames(1)
    -- two VM instructions per step (add, loop) = 20000, counted in steps of 1000
    if F.maxInstr < 18000 or F.maxInstr > 24000 then error("maxInstr " .. F.maxInstr .. " for a 10000-step loop") end
    eq(F.maxWhere, "thread")
end)

check("instruction counter: a direct call (a model event) is counted too", function()
    local F = fresh()
    local d = Open77.ui.create({ document = path, models = { m = { a = 1 } }, events = { m = { "go" } } })
    d:onModel("go", function() loop(10000) end)
    F.event(d, "go")
    if F.maxInstr < 18000 or F.maxInstr > 24000 then error("maxInstr " .. F.maxInstr) end
    eq(F.maxWhere, "event go")
end)

check("budget: 1,500,000 instructions per resume, the documented quota", function()
    eq(fresh().budget, 1500000)
end)

check("budget: a resume past it raises the documented error", function()
    local F = fresh()
    F.budget = 1000
    CreateThread(function() loop(100000) end)
    local ok, err = pcall(F.frames, 1)
    eq(ok, false, "the pass ran on")
    if not tostring(err):find("Open77 script execution budget exceeded", 1, true) then error("error was: " .. tostring(err)) end
end)

check("counted: the hook is restored and the error re-raised when the counted function errors", function()
    local F = fresh()
    local ok, err = pcall(F.counted, "x", nil, function() error("boom", 0) end)
    eq(ok, false)
    eq(err, "boom", "the error")
    eq(debug.gethook(), nil, "the hook still set")
end)

-- ---- documents and models ----

-- a document on the fake (document files must exist: the checks file itself will do)
local function newdoc(F, models, opts)
    opts = opts or {}
    opts.document = opts.document or path
    opts.models = models
    return assert(Open77.ui.create(opts))
end

local function errors(fn, needle, what)
    local ok, err = pcall(fn)
    if ok then error((what or "call") .. ": expected an error containing '" .. needle .. "', got none", 2) end
    if not tostring(err):find(needle, 1, true) then error((what or "call") .. ": error was: " .. tostring(err), 2) end
end

check("set: a documented path (items[2].stock, 1-based) updates the model and adds no stray key", function()
    local F = fresh()
    local m = { items = { { stock = 3 }, { stock = 4 } }, money = 9 }
    local d = newdoc(F, { shop = m })
    eq(d:set("shop", "items[2].stock", 0), true)
    eq(m.items[2].stock, 0, "items[2].stock")
    eq(m.items[1].stock, 3, "items[1].stock")
    d:set("shop", "money", 1250)
    eq(m.money, 1250, "money")
    local n = 0
    for _ in pairs(m) do n = n + 1 end
    eq(n, 2, "keys of the model")
end)

check("set: a path that leads nowhere is an error and writes nothing", function()
    local F = fresh()
    local m = { items = { { stock = 3 } }, money = 9 }
    local d = newdoc(F, { shop = m })
    errors(function() d:set("shop", "items[5].stock", 1) end, "leads nowhere", "items[5].stock")
    errors(function() d:set("shop", "items[0].stock", 1) end, "leads nowhere", "items[0].stock")
    errors(function() d:set("shop", "items[1].price", 1) end, "leads nowhere", "an unknown field")
    errors(function() d:set("shop", "nope", 1) end, "leads nowhere", "an unknown top-level field")
    eq(m.nope, nil)
    eq(m.items[1].price, nil)
end)

check("set, push, merge: an unknown model name is an error", function()
    local F = fresh()
    local m = { money = 9 }
    local d = newdoc(F, { shop = m })
    errors(function() d:set("other", "money", 1) end, "unknown model", "set")
    errors(function() d:push("other", "money", 1) end, "unknown model", "push")
    errors(function() d:merge("other", { money = 1 }) end, "unknown model", "merge")
    eq(m.money, 9, "the only model was written")
end)

check("push appends an entry to the array at the path", function()
    local F = fresh()
    local m = { items = { { id = 1 } } }
    local d = newdoc(F, { shop = m })
    d:push("shop", "items", { id = 9 })
    eq(#m.items, 2); eq(m.items[2].id, 9, "the new entry is last")
    errors(function() d:push("shop", "items[1].id", 1) end, "not an array", "push to a number")
end)

check("removeAt removes the 1-based entry; an index out of range is an error", function()
    local F = fresh()
    local m = { items = { { id = 1 }, { id = 2 }, { id = 3 } } }
    local d = newdoc(F, { shop = m })
    d:removeAt("shop", "items", 1)
    eq(#m.items, 2); eq(m.items[1].id, 2, "the first entry is gone")
    errors(function() d:removeAt("shop", "items", 3) end, "no such entry", "past the end")
    errors(function() d:removeAt("shop", "items", 0) end, "no such entry", "index 0")
    eq(#m.items, 2)
end)

check("models: every model of the document is kept by name and can be merged into", function()
    local F = fresh()
    local a, b = { x = 1 }, { y = 2 }
    local d = newdoc(F, { a = a, b = b })
    d:merge("a", { x = 10 }); d:merge("b", { y = 20 })
    eq(a.x, 10); eq(b.y, 20)
    errors(function() d:merge("b", { z = 1 }) end, "lacks", "a field the model lacks")
    errors(function() d:merge("c", { x = 1 }) end, "unknown model", "an unknown model")
end)

check("F.case: a document with several models writes the others under models", function()
    local F = fresh()
    local d = newdoc(F, { a = { x = 1 }, b = { y = 2 } })
    local c = F.case("two", d)
    eq(c.model.x, 1, "model is the first by name")
    eq(c.models.b.y, 2, "models.b")
    eq(c.models.a, nil, "models.a (it is model)")
    eq(F.case("one", newdoc(F, { a = { x = 1 } })).models, nil, "a single-model case has no models")
end)

check("create accepts source (inline RML) and needs exactly one of document / source", function()
    local F = fresh()
    local d = assert(Open77.ui.create({ source = "<rml/>", models = { m = { a = 1 } } }))
    eq(d.opts.source, "<rml/>")
    errors(function() Open77.ui.create({ models = {} }) end, "exactly one", "neither")
    errors(function() Open77.ui.create({ document = path, source = "<rml/>" }) end, "exactly one", "both")
end)

check("create: a document file that does not exist is nil, undeclared_file", function()
    fresh()
    local d, why = Open77.ui.create({ document = "no/such.rml" })
    eq(d, nil); eq(why, "undeclared_file:no/such.rml")
end)

-- ---- focus, events, listeners ----

-- a document whose focus events are collected
local function watched(F)
    local d = newdoc(F, { m = { a = 1 } }, { events = { m = { "go" } } })
    local ev = {}
    d:onEvent("focus", function(name, detail) ev[#ev + 1] = name .. (detail.reason and (":" .. detail.reason) or "") end)
    return d, ev
end

check("focus: focus() takes it and tells the document once", function()
    local F = fresh()
    local d, ev = watched(F)
    eq(d:focus(), true); d:focus()
    eq(d:hasFocus(), true)
    eq(list(ev), "focus")
end)

check("focus: hide() releases it (blur, reason released)", function()
    local F = fresh()
    local d, ev = watched(F)
    d:show(); d:focus()
    d:hide()
    eq(d:hasFocus(), false, "hasFocus after hide")
    eq(d.visible, false, "visible after hide")
    eq(list(ev), "focus,blur:released")
end)

check("focus: blur() releases it (blur, reason released)", function()
    local F = fresh()
    local d, ev = watched(F)
    d:focus(); d:blur()
    eq(d:hasFocus(), false)
    eq(list(ev), "focus,blur:released")
    d:blur()
    eq(list(ev), "focus,blur:released", "a blur without the focus says nothing")
end)

check("focus: destroy() releases it and fires closed; a second destroy is false", function()
    local F = fresh()
    local d, ev = watched(F)
    local closed = 0
    d:onEvent("closed", function() closed = closed + 1 end)
    d:focus()
    eq(d:destroy(), true)
    eq(d:hasFocus(), false)
    eq(list(ev), "focus,blur:released")
    eq(closed, 1, "closed events")
    eq(d:destroy(), false, "second destroy")
    errors(function() d:show() end, "destroyed document", "a call on a destroyed document")
end)

check("focus: another surface taking it is a blur with reason taken and by", function()
    local F = fresh()
    local d = newdoc(F, { m = { a = 1 } })
    local got
    d:onEvent("focus", function(name, detail) if name == "blur" then got = detail end end)
    d:focus()
    F.focusLost(d, "taken", "other_resource")
    eq(d:hasFocus(), false)
    eq(got.reason, "taken"); eq(got.by, "other_resource")
end)

check("focus: a refused focus is nil, reason and an error event focus on the document", function()
    local F = fresh()
    F.focusResult = false
    local d = newdoc(F, { m = { a = 1 } })
    local kind, msg
    d:onEvent("error", function(name, detail) kind, msg = name, detail.message end)
    local ok, why = d:focus()
    eq(ok, nil); eq(why, "focus_unavailable")
    eq(d:hasFocus(), false)
    eq(kind, "focus"); eq(msg, "focus_unavailable")
end)

check("events: F.loaded fires loaded and the state says so", function()
    local F = fresh()
    local d = newdoc(F, { m = { a = 1 } })
    local got
    d:onEvent("loaded", function(name, detail) got = name end)
    eq(d:state().loaded, false, "loaded before")
    F.loaded(d)
    eq(got, "loaded"); eq(d:state().loaded, true, "loaded after")
end)

check("model events: every listener of the name, then the * listeners with the name first; off removes one", function()
    local F = fresh()
    local d = newdoc(F, { m = { a = 1 } }, { events = { m = { "go" } } })
    local o = {}
    d:onModel("go", function(x) o[#o + 1] = "one:" .. tostring(x) end)
    local id = d:onModel("go", function(x) o[#o + 1] = "two:" .. tostring(x) end)
    d:onModel("*", function(name, x) o[#o + 1] = "star:" .. name .. ":" .. tostring(x) end)
    F.event(d, "go", 7)
    eq(list(o), "one:7,two:7,star:go:7")
    eq(d:off(id), true)
    eq(d:off(id), false, "off of an id that is gone")
    o = {}
    F.event(d, "go", 8)
    eq(list(o), "one:8,star:go:8")
    errors(function() F.event(newdoc(F, { m = { a = 1 } }), "go") end, "no model event handler", "an event nobody listens to")
end)

check("DOM events: F.key / F.emit reach the listeners of the type with the detail; off removes", function()
    local F = fresh()
    local d = newdoc(F, { m = { a = 1 } })
    local keys = {}
    local id = d:on("keydown", function(e) keys[#keys + 1] = e.key end)
    d:on("keydown", "#search", function(e) keys[#keys + 1] = "sel:" .. e.key end)
    d:on("click", ".item", function(e) keys[#keys + 1] = "click:" .. e.id end)
    F.key(d, "escape")
    F.emit(d, "click", { id = "row1" })
    eq(list(keys), "escape,sel:escape,click:row1")
    d:off(id)
    F.key(d, "a")
    eq(list(keys), "escape,sel:escape,click:row1,sel:a")
end)

-- ---- the documented methods that only record ----

local DOC_METHODS = { "text", "rml", "attr", "class", "setClasses", "value", "click", "focusElement", "blurElement",
    "scrollTo", "insert", "remove", "stylesheet", "watch", "unwatch", "setZIndex", "animate", "keyframes", "stop",
    "settle", "layout", "scene", "anchor", "unanchor", "projection" }

check("documented methods (DOM, motion, scene) exist, record their arguments and refuse a destroyed document", function()
    local F = fresh()
    local d = newdoc(F, { m = { a = 1 } })
    for _, name in ipairs(DOC_METHODS) do
        if type(d[name]) ~= "function" then error("missing: " .. name) end
        eq(d[name](d, "#sel", "x", 3), true, name)
        local last = d.calls[#d.calls]
        eq(last.m, name, "recorded method"); eq(last.args[1], "#sel", name .. " arg 1"); eq(last.args[3], 3, name .. " arg 3")
    end
    d:destroy()
    for _, name in ipairs(DOC_METHODS) do errors(function() d[name](d, "#sel") end, "destroyed document", name) end
end)

check("documented methods: set/push/removeAt/merge record every argument", function()
    local F = fresh()
    local d = newdoc(F, { m = { a = 1, items = { 1, 2 } } })
    d:set("m", "a", 5); d:push("m", "items", 3); d:removeAt("m", "items", 1)
    eq(d.calls[1].args[3], 5, "set value"); eq(d.calls[2].args[3], 3, "push value"); eq(d.calls[3].args[3], 1, "removeAt index")
end)

check("documented methods: create returns a distinct @serial, rect is nil, state/sceneState are tables, id a number", function()
    local F = fresh()
    local d = newdoc(F, { m = { a = 1 } })
    local a, b = d:create("#toasts", { text = "x" }), d:create("#toasts", { text = "y" })
    if not tostring(a):match("^@%d+$") then error("serial " .. tostring(a)) end
    if a == b then error("two creates gave the same serial " .. a) end
    eq(d:rect("#panel"), nil, "rect")
    eq(type(d:state()), "table"); eq(type(d:sceneState("s")), "table"); eq(type(d:id()), "number")
    eq(d:state().focused, false); eq(d:state().visible, true)
end)

check("documented methods: reload fires reloaded", function()
    local F = fresh()
    local d = newdoc(F, { m = { a = 1 } })
    local n = 0
    d:onEvent("reloaded", function() n = n + 1 end)
    d:reload()
    eq(n, 1)
end)

check("create: a resource owns at most 32 documents (nativeui_instance_limit); destroying frees one", function()
    local F = fresh()
    local docs = {}
    for i = 1, 32 do docs[i] = newdoc(F, { m = { a = 1 } }) end
    local d, why = Open77.ui.create({ document = path, models = { m = { a = 1 } } })
    eq(d, nil); eq(why, "nativeui_instance_limit")
    docs[1]:destroy()
    eq(Open77.ui.create({ document = path, models = { m = { a = 1 } } }) ~= nil, true, "after a destroy")
end)

check("Open77.ui: registerEffect records the effect, stats has a text, loadFont keeps the fallback flag", function()
    local F = fresh()
    eq(Open77.ui.registerEffect("glow2", "float4 main() {}"), true)
    eq(F.effects.glow2, "float4 main() {}")
    eq(select(2, Open77.ui.registerEffect("x")), "invalid_effect")
    eq(type(Open77.ui.stats().text), "string")
    eq(Open77.ui.loadFont(path, "Fam", true), true)
    eq(F.fonts[1][2], "Fam"); eq(F.fonts[1][3], true, "fallback flag")
    local ok, why = Open77.ui.loadFont("no/such.ttf", "Fam")
    eq(ok, nil); eq(why, "font_not_declared")
end)

-- ---- F.json ----

check("json: strings, escapes, booleans, nested objects with sorted keys, an empty table is []", function()
    local F = fresh()
    eq(F.json({ b = { 1, 2 }, a = false, [ "q" ] = "x\"y\\z\n\1" }), '{"a":false,"b":[1,2],"q":"x\\"y\\\\z\\n\\u0001"}')
    eq(F.json({}), "[]")
    eq(F.json({ {} , { n = {} } }), '[[],{"n":[]}]')
end)

check("json: floats keep every digit and stay floats", function()
    local F = fresh()
    eq(F.json({ 1234567.5, 0.1, 3.0, -2.5e-9 }), "[1234567.5,0.1,3.0,-2.5e-09]")
    local third = F.json(1 / 3)
    eq(tonumber(third), 1 / 3, "1/3 reads back as itself (" .. third .. ")")
end)

check("json: NaN and infinity are an error naming the path", function()
    local F = fresh()
    errors(function() F.json({ rows = { 1, 0 / 0 } }) end, "$.rows[2]", "NaN")
    errors(function() F.json({ math.huge }) end, "$[1]", "inf")
    errors(function() F.json({ -math.huge }) end, "$[1]", "-inf")
end)

check("json: a table mixing an array with other keys, or with holes, is an error naming the path", function()
    local F = fresh()
    errors(function() F.json({ rows = { 1, x = 2 } }) end, "$.rows mixes", "mixed")
    errors(function() F.json({ [1] = "a", [3] = "c" }) end, "$ mixes", "a hole")
end)

check("json: a function (or anything else JSON cannot hold) is an error naming the path", function()
    local F = fresh()
    errors(function() F.json({ f = print }) end, "$.f", "function")
end)

if failed > 0 then say(failed .. " check(s) failed"); os.exit(1) end
