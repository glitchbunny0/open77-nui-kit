-- fake_nui.lua: a fake Open77.ui and a coroutine scheduler, so a NativeUI screen's client Lua runs offline (plain
-- lua5.4) and produces the models rml-check / rml-preview need. It records every document call, stores merged model
-- tables BY REFERENCE (a copy would be counted against the instruction budget it measures), runs CreateThread / Wait /
-- SetTimeout as coroutines on 16 ms frames, and counts the Lua instructions of every resume and every direct call
-- (F.maxInstr, F.maxWhere; F.budget = 1,500,000 per resume, what Open77 documents, 500,000 on older clients).
-- Load: local F = dofile("<kit>/fake-nui/fake_nui.lua"); F.install()      Example: examples/side-menu/models.lua
local F = { docs = {}, threads = {}, now = 0, maxInstr = 0, maxWhere = "", fonts = {}, refuse = nil, focusResult = true,
    focusWhy = nil, logs = {}, quiet = false, budget = 1500000 }
local FRAME = 16
local wake = {}

local function exists(path)
    local f = io.open(path, "rb")
    if f then f:close() return true end
    return false
end
F.exists = exists

-- Instructions of one piece of work, counted on the running coroutine (or the main thread) in steps of STEP. The count
-- hook is a Lua function whose own instructions eat into the next interval, so a small step overcounts (10 gave +60%);
-- STEP = 1000 keeps that near 1%. Open77 documents 1,500,000 instructions per coroutine resume (500,000 on older
-- clients) and raises "Open77 script execution budget exceeded" past it; F.budget is that limit (nil switches it off),
-- F.maxInstr / F.maxWhere the worst piece seen.
local STEP = 1000
local function counted(where, co, fn, ...)
    local n = 0
    local limit = F.budget
    local hook = function()
        n = n + STEP
        if limit and n > limit then error("Open77 script execution budget exceeded", 0) end
    end
    local oldHook, oldMask, oldCount
    if not co then oldHook, oldMask, oldCount = debug.gethook() end
    if co then debug.sethook(co, hook, "", STEP) else debug.sethook(hook, "", STEP) end
    local res = table.pack(pcall(fn, ...))
    if co then debug.sethook(co) else debug.sethook(oldHook, oldMask, oldCount) end   -- also after an error
    if n > F.maxInstr then F.maxInstr, F.maxWhere = n, where end
    if not res[1] then error(res[2], 0) end
    return table.unpack(res, 2, res.n)
end
F.counted = counted

-- Open77 starts a task on the NEXT scheduler pass (there is no CreateThreadNow), and wakes the waiting ones in order of
-- their wake time, then of their creation. Every task is one coroutine; F.frames(n) is n passes of 16 ms.
local seq = 0
local function resume(co, where)
    local ok, err = counted(where or "thread", co, coroutine.resume, co)
    if not ok then error(debug.traceback(co, tostring(err)), 0) end
end

function F.install()
    CreateThread = function(fn)
        local co = coroutine.create(fn)
        seq = seq + 1
        F.threads[#F.threads + 1] = co
        wake[co] = { at = F.now, seq = seq }
        return co
    end
    Wait = function(ms)
        seq = seq + 1
        wake[coroutine.running()] = { at = F.now + math.max(0, ms or 0), seq = seq }
        coroutine.yield()
    end
    local timers, timerId = {}, 0
    SetTimeout = function(ms, fn)
        timerId = timerId + 1
        local id = timerId
        timers[id] = true
        CreateThread(function() Wait(ms); if timers[id] then timers[id] = nil; fn() end end)
        return id
    end
    ClearTimeout = function(id) local had = timers[id] == true; timers[id] = nil; return had end
    GetGameTimer = function() return F.now end
    print = function(...)
        local t = table.pack(...)
        for i = 1, t.n do t[i] = tostring(t[i]) end
        local line = table.concat(t, "\t", 1, t.n)
        F.logs[#F.logs + 1] = line
        if not F.quiet and os.getenv("FAKE_NUI_LOG") then io.stderr:write(line, "\n") end
    end
    Open77 = Open77 or {}
    Open77.ui = {
        create = function(opts)
            if F.refuse then return nil, F.refuse end
            assert(type(opts) == "table" and (type(opts.document) == "string") ~= (type(opts.source) == "string"),
                "create needs exactly one of document / source")
            if opts.document and not exists(opts.document) then return nil, "undeclared_file:" .. opts.document end
            local d = F.newDoc(opts)
            F.docs[#F.docs + 1] = d
            F.last = d
            return d
        end,
        loadFont = function(path, family)
            if not exists(path) then return nil, "font_not_declared" end
            F.fonts[#F.fonts + 1] = { path, family }
            return true
        end,
    }
    return F
end

-- "items[2].stock" -> the table that holds the value and the key of it ({ items = { {}, { stock = 5 } } } gives the
-- second entry and "stock"); indices in brackets are 1-based. mustExist: the last key has to be there already
function F.locate(model, path, mustExist)
    assert(type(path) == "string" and path ~= "", "a model path is a non-empty string")
    local keys, i = {}, 1
    while i <= #path do
        local idx, nexti = path:match("^%[(%d+)%]()", i)
        if idx then keys[#keys + 1] = math.tointeger(tonumber(idx)); i = nexti
        else
            local name
            name, nexti = path:match("^%.?([^.%[%]]+)()", i)
            assert(name, "bad model path " .. path)
            keys[#keys + 1] = name; i = nexti
        end
    end
    local t = model
    for n = 1, #keys - 1 do
        t = t[keys[n]]
        assert(type(t) == "table", "model path " .. path .. " leads nowhere at " .. tostring(keys[n]))
    end
    local last = keys[#keys]
    assert(not mustExist or t[last] ~= nil, "model path " .. path .. " leads nowhere at " .. tostring(last))
    return t, last
end

-- the fake document: the calls the adapter makes, the model as the document would hold it
function F.newDoc(opts)
    local d = { opts = opts, calls = {}, ev = {}, modelH = {}, dom = {}, visible = opts.visible ~= false, focused = false,
        destroyed = false, merges = 0, models = {} }
    -- every model by name, by reference; d.model / d.modelName are the first by name (the one a single-model case uses)
    local names = {}
    for n, m in pairs(opts.models or {}) do
        assert(type(m) == "table", "the model " .. tostring(n) .. " must be a table of fields")
        d.models[n] = m
        names[#names + 1] = n
    end
    table.sort(names)
    d.modelName = names[1]
    d.model = d.models[names[1]] or {}
    local function rec(m, ...) d.calls[#d.calls + 1] = { m = m, args = table.pack(...) } end
    local function live(m) if d.destroyed then error("NativeUI: " .. m .. " on a destroyed document", 2) end end
    function d:onEvent(kind, fn) live("onEvent"); rec("onEvent", kind); self.ev[kind] = fn; return true end
    function d:onModel(n, fn) live("onModel"); rec("onModel", n); self.modelH[n] = fn; return #self.calls end
    function d:on(t, sel, fn) live("on"); if fn == nil then fn, sel = sel, nil end rec("on", t, sel); self.dom[t] = fn; return #self.calls end
    local function modelOf(mn, m)
        local model = d.models[mn]
        assert(model, m .. " into an unknown model " .. tostring(mn))
        return model
    end
    function d:merge(mn, t)
        live("merge"); rec("merge", mn)
        local model = modelOf(mn, "merge")
        for k, v in pairs(t) do
            assert(model[k] ~= nil, "merge of a field the model " .. mn .. " lacks: " .. tostring(k))
            model[k] = v   -- by reference
        end
        self.merges = self.merges + 1
        return true
    end
    -- set / push / removeAt take the documented path form: "items[2].stock", array indices 1-based. A path that leads
    -- nowhere asserts, as merge does (the game would report it as an error event)
    function d:set(mn, path, v)
        live("set"); rec("set", mn, path, v)
        local t, key = F.locate(modelOf(mn, "set"), path, true)
        t[key] = v
        return true
    end
    function d:push(mn, path, v)
        live("push"); rec("push", mn, path, v)
        local t, key = F.locate(modelOf(mn, "push"), path, true)
        assert(type(t[key]) == "table", "push to " .. path .. ": not an array")
        t[key][#t[key] + 1] = v
        return true
    end
    function d:removeAt(mn, path, i)
        live("removeAt"); rec("removeAt", mn, path, i)
        local t, key = F.locate(modelOf(mn, "removeAt"), path, true)
        local arr = t[key]
        assert(type(arr) == "table" and math.type(i) == "integer" and i >= 1 and i <= #arr,
            "removeAt " .. tostring(i) .. " of " .. path .. ": no such entry")
        table.remove(arr, i)
        return true
    end
    function d:batch(fn) live("batch"); rec("batch"); fn(); return true end
    function d:show() live("show"); rec("show"); self.visible = true; return true end
    function d:hide() live("hide"); rec("hide"); self.visible = false; return true end
    function d:focus(o)
        live("focus"); rec("focus", o)
        if F.focusResult then self.focused = true; return true end
        return nil, F.focusWhy or "focus_unavailable"
    end
    function d:blur() live("blur"); rec("blur"); self.focused = false; return true end
    function d:hasFocus() return self.focused end
    function d:style(...) live("style"); rec("style", ...); return true end
    function d:destroy() if self.destroyed then return false end rec("destroy"); self.destroyed = true; self.focused = false; self.visible = false; return true end
    return d
end

-- the platform's side: the document loaded, a model event from the markup, a key, a document error event
function F.loaded(d) counted("loaded", nil, d.ev.loaded, "loaded", {}) end
function F.event(d, name, ...)
    local fn = d.modelH[name]
    assert(fn, "no model event handler " .. tostring(name))
    counted("event " .. name, nil, fn, ...)
end
function F.key(d, key) counted("keydown", nil, d.dom.keydown, { key = key, type = "keydown" }) end
function F.docError(d, kind, msg) d.ev.error(kind, { message = msg }) end

-- run the scheduler for n passes (default 1) of 16 ms: the tasks whose wake time has come, earliest first; a task
-- created during a pass starts on the next one
function F.frames(n)
    for _ = 1, n or 1 do
        F.now = F.now + FRAME
        local due = {}
        for i = 1, #F.threads do
            local co = F.threads[i]
            local w = wake[co]
            if coroutine.status(co) == "suspended" and w.at <= F.now then due[#due + 1] = { co = co, w = w } end
        end
        table.sort(due, function(x, y) if x.w.at ~= y.w.at then return x.w.at < y.w.at end return x.w.seq < y.w.seq end)
        for _, d in ipairs(due) do
            if coroutine.status(d.co) == "suspended" and wake[d.co] == d.w then resume(d.co) end
        end
    end
end
function F.settle(maxFrames)
    for _ = 1, maxFrames or 60 do F.frames(1) end
end
function F.advance(ms) F.frames(math.ceil(ms / FRAME)) end

-- JSON for the cases file (strings, numbers, booleans, arrays = sequences, objects with sorted keys; an empty table is
-- an empty array, as NativeUI maps it)
function F.json(v)
    local t = type(v)
    if t == "string" then
        return '"' .. v:gsub('[%c"\\]', function(c)
            if c == '"' then return '\\"' elseif c == "\\" then return "\\\\" elseif c == "\n" then return "\\n" end
            return ("\\u%04x"):format(c:byte())
        end) .. '"'
    elseif t == "number" then
        if math.type(v) == "integer" then return tostring(v) end
        local s = ("%.6g"):format(v)
        return s:find("[%.e]") and s or (s .. ".0")
    elseif t == "boolean" then return tostring(v)
    elseif t == "table" then
        if next(v) == nil or v[1] ~= nil then
            local p = {}
            for i, x in ipairs(v) do p[i] = F.json(x) end
            return "[" .. table.concat(p, ",") .. "]"
        end
        local keys = {}
        for k in pairs(v) do keys[#keys + 1] = k end
        table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
        local p = {}
        for _, k in ipairs(keys) do p[#p + 1] = F.json(tostring(k)) .. ":" .. F.json(v[k]) end
        return "{" .. table.concat(p, ",") .. "}"
    end
    return "null"
end

-- one case for rml-check / rml-preview from a fake document: its model as the client left it, plus what to click
-- (clicks = { { selector, event, { args... } } }) and the model events the document declares
function F.case(name, doc, clicks, events)
    local cs = {}
    for i, k in ipairs(clicks or {}) do cs[i] = { sel = k[1], event = k[2], args = k[3] or {} } end
    local ev = events
    if not ev then
        ev = {}
        for _, list in pairs(doc.opts.events or {}) do for _, e in ipairs(list) do ev[#ev + 1] = e end end
    end
    local c = { name = name, model = doc.model, clicks = cs, events = ev }
    for n, m in pairs(doc.models) do   -- a document with several models: the others go under "models"
        if m ~= doc.model then c.models = c.models or {}; c.models[n] = m end
    end
    return c
end
return F
