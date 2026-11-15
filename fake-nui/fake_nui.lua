-- fake_nui.lua: a fake Open77.ui and a coroutine scheduler, so a NativeUI screen's client Lua runs offline (plain
-- lua5.4) and produces the models rml-check / rml-preview need. It records every document call, stores merged model
-- tables BY REFERENCE (a copy would be counted against the instruction budget it measures), runs CreateThread / Wait
-- as coroutines on 16 ms frames, and counts the Lua instructions of every resume and every direct call (F.maxInstr,
-- F.maxWhere: a client resume gets roughly 10k before the game complains).
-- Load: local F = dofile("<kit>/fake-nui/fake_nui.lua"); F.install()      Example: examples/side-menu/models.lua
local F = { docs = {}, threads = {}, now = 0, maxInstr = 0, maxWhere = "", fonts = {}, refuse = nil, focusResult = true,
    focusWhy = nil, logs = {}, quiet = false }
local FRAME = 16
local wake = {}

local function exists(path)
    local f = io.open(path, "rb")
    if f then f:close() return true end
    return false
end
F.exists = exists

-- instructions of one piece of work, counted in steps of 10 on the running coroutine (or the main thread)
local function counted(where, co, fn, ...)
    local n = 0
    local hook = function() n = n + 10 end
    if co then debug.sethook(co, hook, "", 10) else debug.sethook(hook, "", 10) end
    local res = table.pack(fn(...))
    if co then debug.sethook(co) else debug.sethook() end
    if n > F.maxInstr then F.maxInstr, F.maxWhere = n, where end
    return table.unpack(res, 1, res.n)
end
F.counted = counted

local function resume(co, where)
    local ok, err = counted(where or "thread", co, coroutine.resume, co)
    if not ok then error(debug.traceback(co, tostring(err)), 0) end
end

function F.install()
    CreateThread = function(fn)
        local co = coroutine.create(fn)
        F.threads[#F.threads + 1] = co
        wake[co] = F.now
        resume(co, "thread start")
    end
    Wait = function(ms) wake[coroutine.running()] = F.now + math.max(0, ms or 0); coroutine.yield() end
    GetGameTimer = function() return F.now end
    print = function(s) F.logs[#F.logs + 1] = tostring(s); if not F.quiet and os.getenv("FAKE_NUI_LOG") then io.stderr:write(tostring(s), "\n") end end
    Open77 = Open77 or {}
    Open77.ui = {
        create = function(opts)
            if F.refuse then return nil, F.refuse end
            assert(type(opts) == "table" and type(opts.document) == "string", "create needs a document")
            if not exists(opts.document) then return nil, "undeclared_file:" .. opts.document end
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

-- the fake document: the calls the adapter makes, the model as the document would hold it
function F.newDoc(opts)
    local d = { opts = opts, calls = {}, ev = {}, modelH = {}, dom = {}, visible = opts.visible ~= false, focused = false,
        destroyed = false, merges = 0 }
    local name, model = next(opts.models or {})
    d.modelName, d.model = name, model or {}
    local function rec(m, ...) d.calls[#d.calls + 1] = { m = m, args = table.pack(...) } end
    local function live(m) if d.destroyed then error("NativeUI: " .. m .. " on a destroyed document", 2) end end
    function d:onEvent(kind, fn) live("onEvent"); rec("onEvent", kind); self.ev[kind] = fn; return true end
    function d:onModel(n, fn) live("onModel"); rec("onModel", n); self.modelH[n] = fn; return #self.calls end
    function d:on(t, sel, fn) live("on"); if fn == nil then fn, sel = sel, nil end rec("on", t, sel); self.dom[t] = fn; return #self.calls end
    function d:merge(mn, t)
        live("merge"); rec("merge", mn)
        assert(mn == self.modelName, "merge into an unknown model " .. tostring(mn))
        for k, v in pairs(t) do
            assert(self.model[k] ~= nil, "merge of a field the first model lacks: " .. tostring(k))
            self.model[k] = v   -- by reference
        end
        self.merges = self.merges + 1
        return true
    end
    function d:set(mn, path, v) live("set"); rec("set", mn, path); self.model[path] = v; return true end
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

-- run the scheduler for n frames (default: until nothing is waiting on a frame, at most 400)
function F.frames(n)
    for _ = 1, n or 1 do
        F.now = F.now + FRAME
        for _, co in ipairs(F.threads) do
            if coroutine.status(co) == "suspended" and (wake[co] or 0) <= F.now then resume(co) end
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
    return { name = name, model = doc.model, clicks = cs, events = ev }
end
return F
