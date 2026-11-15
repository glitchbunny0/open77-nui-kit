-- fake_nui.lua: a fake Open77.ui and a coroutine scheduler, so a NativeUI screen's client Lua runs offline (plain
-- lua5.4) and produces the models rml-check / rml-preview need. It records every document call, stores merged model
-- tables BY REFERENCE (a copy would be counted against the instruction budget it measures), runs CreateThread / Wait /
-- SetTimeout as coroutines on 16 ms frames, and counts the Lua instructions of every resume and every direct call
-- (F.maxInstr, F.maxWhere; F.budget = 1,500,000 per resume, what Open77 documents, 500,000 on older clients).
--
-- What is faked, from Open77's NativeUI reference: create (document or source, every model by name, the 32 documents
-- limit), loadFont, registerEffect, stats; per document the data (set / push / removeAt with 1-based paths, merge,
-- batch), listeners (onModel incl. "*", on, onEvent, off), show / hide / focus / blur / hasFocus with the input lease and
-- its focus / blur / error / closed events, reload, state, rect (nil), create (a @serial), id. What only RECORDS its call
-- (d.calls, no layout is run, callbacks never called): F.stubs (text, rml, attr, class, animate, scene, ...). The
-- platform's side is driven by you: F.loaded, F.event (a model event), F.emit / F.key (DOM events), F.docError,
-- F.focusLost, then F.frames / F.settle / F.advance for the scheduler.
-- Load: local F = dofile("<kit>/fake-nui/fake_nui.lua"); F.install()      Example: examples/side-menu/models.lua
local F = { docs = {}, threads = {}, now = 0, maxInstr = 0, maxWhere = "", fonts = {}, refuse = nil, focusResult = true,
    focusWhy = nil, logs = {}, quiet = false, budget = 1500000, effects = {} }
local FRAME = 16
local listenerId = 0
local wake = {}

-- the documented document methods that only record their call (F.stubs); the ones with a behaviour are in newDoc
F.stubs = { "text", "rml", "attr", "class", "setClasses", "value", "click", "focusElement", "blurElement", "scrollTo",
    "insert", "remove", "stylesheet", "watch", "unwatch", "setZIndex", "animate", "keyframes", "stop", "settle", "layout",
    "scene", "anchor", "unanchor", "projection" }

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
            local open = 0
            for _, x in ipairs(F.docs) do if not x.destroyed then open = open + 1 end end
            if open >= 32 then return nil, "nativeui_instance_limit" end
            local d = F.newDoc(opts)
            d.docId = #F.docs + 1
            F.docs[#F.docs + 1] = d
            F.last = d
            return d
        end,
        loadFont = function(path, family, fallback)
            if not exists(path) then return nil, "font_not_declared" end
            F.fonts[#F.fonts + 1] = { path, family, fallback }
            return true
        end,
        registerEffect = function(name, hlsl)
            if type(name) ~= "string" or type(hlsl) ~= "string" then return nil, "invalid_effect" end
            F.effects[name] = hlsl
            return true
        end,
        stats = function() return { text = "fake-nui: " .. #F.docs .. " documents" } end,
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
    -- listeners by kind ("event", "model", "dom") and name, in registration order; the id they return goes to d:off
    d.listeners = { event = {}, model = {}, dom = {} }
    local function listen(kind, name, fn)
        assert(type(fn) == "function", "a listener is a function")
        listenerId = listenerId + 1
        local l = d.listeners[kind]
        l[name] = l[name] or {}
        l[name][#l[name] + 1] = { id = listenerId, fn = fn }
        return listenerId
    end
    function d:onEvent(kind, fn) live("onEvent"); rec("onEvent", kind); listen("event", kind, fn); self.ev[kind] = fn; return true end
    function d:onModel(n, fn) live("onModel"); rec("onModel", n); self.modelH[n] = fn; return listen("model", n, fn) end
    -- DOM listeners are delegated by selector in the game; the fake keeps the selector for the record and fires them
    -- all (F.emit)
    function d:on(t, sel, fn)
        live("on"); if fn == nil then fn, sel = sel, nil end
        rec("on", t, sel); self.dom[t] = fn
        return listen("dom", t, fn)
    end
    function d:off(id)
        live("off"); rec("off", id)
        for _, byName in pairs(d.listeners) do
            for _, list in pairs(byName) do
                for i, l in ipairs(list) do if l.id == id then table.remove(list, i); return true end end
            end
        end
        return false
    end
    local function fire(kind, name, ...)   -- every listener of that kind and name, as the platform calls them
        for _, l in ipairs({ table.unpack(d.listeners[kind][name] or {}) }) do l.fn(...) end
    end
    d.fire = fire
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
    -- the input lease: focus() takes it, blur() / hide() / destroy() give it back ("released"); the document is told
    -- through onEvent("focus"): name "focus" or "blur" with detail.reason (taken, released, suspended) and detail.by
    local function release(reason, by)
        if not d.focused then return end
        d.focused = false
        fire("event", "focus", "blur", { reason = reason, by = by })
    end
    d.release = release
    function d:hide() live("hide"); rec("hide"); self.visible = false; release("released"); return true end
    function d:focus(o)
        live("focus"); rec("focus", o)
        if F.focusResult then
            if not self.focused then self.focused = true; fire("event", "focus", "focus", {}) end
            return true
        end
        local why = F.focusWhy or "focus_unavailable"
        fire("event", "error", "focus", { message = why })   -- the document is told as well
        return nil, why
    end
    function d:blur() live("blur"); rec("blur"); release("released"); return true end
    function d:hasFocus() return self.focused end
    function d:style(...) live("style"); rec("style", ...); return true end
    function d:destroy()
        if self.destroyed then return false end
        rec("destroy")
        self.visible = false
        release("released")
        fire("event", "closed", "closed", {})
        self.destroyed = true
        return true
    end
    -- the documented DOM, motion and scene calls: recorded (d.calls), not run: they return true, as the game does for a
    -- queued command, and a callback argument (onDone) is never called
    for _, name in ipairs(F.stubs) do
        d[name] = function(self, ...) live(name); rec(name, ...); return true end
    end
    local serial = 1073741824
    function d:create(parent, spec) live("create"); rec("create", parent, spec); serial = serial + 1; return "@" .. serial end
    function d:id() live("id"); return d.docId end
    function d:rect(sel) live("rect"); rec("rect", sel); return nil end   -- "nil until published"
    function d:state()
        live("state")
        return { loaded = d.loaded == true, visible = d.visible, focused = d.focused, width = 1920, height = 1080,
            perf = { fps = 60, frameMs = 0, updateMs = 0, renderMs = 0, sceneDraws = 0, sceneRenders = 0, sceneInstances = 0, sceneGpuMB = 0 } }
    end
    function d:sceneState(...) live("sceneState"); rec("sceneState", ...); return {} end
    function d:reload() live("reload"); rec("reload"); fire("event", "reloaded", "reloaded", {}); return true end
    return d
end

-- the platform's side: the document loaded, a model event from the markup, a DOM event, a key, a document error event,
-- the input taken away
function F.loaded(d) d.loaded = true; counted("loaded", nil, d.fire, "event", "loaded", "loaded", {}) end
function F.event(d, name, ...)   -- a model event: the listeners of that name, then the "*" ones (name first)
    local own, star = d.listeners.model[name], d.listeners.model["*"]
    assert((own and #own > 0) or (star and #star > 0), "no model event handler " .. tostring(name))
    local args = table.pack(...)
    counted("event " .. name, nil, function()
        d.fire("model", name, table.unpack(args, 1, args.n))
        d.fire("model", "*", name, table.unpack(args, 1, args.n))
    end)
end
function F.emit(d, kind, detail)   -- a DOM event of that type reaches every listener of it (the selector is not matched)
    counted(kind, nil, d.fire, "dom", kind, detail)
end
function F.key(d, key) F.emit(d, "keydown", { key = key, type = "keydown" }) end
function F.docError(d, kind, msg) d.fire("event", "error", kind, { message = msg }) end
function F.focusLost(d, reason, by) d.release(reason or "taken", by) end

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
-- an empty array, as NativeUI maps it). What JSON cannot hold is an error naming the path ($.rows[2].price): NaN and
-- infinity, a table that mixes a sequence with other keys (or has holes), a function. Floats keep every digit (the
-- shortest of 15..17 that reads back the same).
local function jsonOf(v, path)
    local t = type(v)
    if t == "string" then
        return '"' .. v:gsub('[%c"\\]', function(c)
            if c == '"' then return '\\"' elseif c == "\\" then return "\\\\" elseif c == "\n" then return "\\n" end
            return ("\\u%04x"):format(c:byte())
        end) .. '"'
    elseif t == "number" then
        if math.type(v) == "integer" then return tostring(v) end
        if v ~= v or v == math.huge or v == -math.huge then error("F.json: " .. tostring(v) .. " at " .. path .. " is not JSON", 0) end
        local s
        for digits = 15, 17 do
            s = ("%." .. digits .. "g"):format(v)
            if tonumber(s) == v then break end
        end
        return s:find("[%.eE]") and s or (s .. ".0")
    elseif t == "boolean" then return tostring(v)
    elseif t == "table" then
        local count = 0
        for _ in pairs(v) do count = count + 1 end
        if count == 0 or v[1] ~= nil then
            if count ~= #v then error("F.json: " .. path .. " mixes an array with other keys, or has holes", 0) end
            local p = {}
            for i, x in ipairs(v) do p[i] = jsonOf(x, path .. "[" .. i .. "]") end
            return "[" .. table.concat(p, ",") .. "]"
        end
        local keys = {}
        for k in pairs(v) do keys[#keys + 1] = k end
        table.sort(keys, function(a, b) return tostring(a) < tostring(b) end)
        local p = {}
        for _, k in ipairs(keys) do p[#p + 1] = jsonOf(tostring(k), path) .. ":" .. jsonOf(v[k], path .. "." .. tostring(k)) end
        return "{" .. table.concat(p, ",") .. "}"
    end
    error("F.json: a " .. t .. " at " .. path .. " is not JSON", 0)
end
function F.json(v) return jsonOf(v, "$") end

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
