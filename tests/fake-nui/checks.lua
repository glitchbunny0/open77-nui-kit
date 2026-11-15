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

if failed > 0 then say(failed .. " check(s) failed"); os.exit(1) end
