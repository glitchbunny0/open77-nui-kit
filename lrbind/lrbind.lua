-- SPDX-License-Identifier: MIT
-- lrbind.lua, part of open77-nui-kit.
-- Copyright (c) 2026 the open77-nui-kit authors
--
-- Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
-- documentation files (the "Software"), to deal in the Software without restriction, including without limitation
-- the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and to
-- permit persons to whom the Software is furnished to do so, subject to the following conditions:
--
-- The above copyright notice and this permission notice shall be included in all copies or substantial portions of
-- the Software.
--
-- THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
-- THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
-- AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
-- TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
-- SOFTWARE.

-- lrbind.lua: a WebUI page that loads web/lrbind.js, driven with the NativeUI document API. Client code calls
-- set / merge / push / removeAt / onModel the same way on either surface (array paths 1-based, as Open77.ui).
--   LrBind.page(page, { models = { name = {...} }, events = { name = { "pick", ... } } }) -> handle
--   LrBind.create(opts) -> handle, "native" | "web"   (NativeUI when the client has it and opts.document is set)
-- The handle keeps the whole model, so a page that reloads gets its state back on its next lrbind:ready.
LrBind = LrBind or {}

local function copy(v)
    if type(v) ~= "table" then return v end
    local out = {}
    for k, x in pairs(v) do out[k] = copy(x) end
    return out
end

-- A path from Lua: a field name, then any run of [n] (1-based, n >= 1) and .member, e.g. "items[2].name" or
-- "grid[1][3]". Returns its keys ({ "items", 2, "name" }), or nil for anything else (rows[x], rows[ 1 ], rows[-1],
-- rows[1.5], a.b..c), so the Lua copy and the page never act on different places.
local function parsePath(path)
    if type(path) ~= "string" then return nil end
    local name = path:match("^%a[%w_]*")
    if not name then return nil end
    local keys, pos = { name }, #name + 1
    while pos <= #path do
        local idx = path:match("^%[(%d+)%]", pos)
        if idx then
            local n = math.tointeger(tonumber(idx))
            if not n or n < 1 then return nil end
            keys[#keys + 1] = n
            pos = pos + #idx + 2
        else
            local member = path:match("^%.([%a_][%w_]*)", pos)
            if not member then return nil end
            keys[#keys + 1] = member
            pos = pos + #member + 1
        end
    end
    return keys
end

-- the page's path for those keys (0-based)
local function toPage(keys)
    local out = keys[1]
    for i = 2, #keys do
        local k = keys[i]
        out = out .. (math.type(k) == "integer" and ("[" .. (k - 1) .. "]") or ("." .. k))
    end
    return out
end

-- a path from the page (0-based) as Lua writes it
local function toLua(path)
    return (tostring(path):gsub("%[(%d+)%]", function(n) return "[" .. (tonumber(n) + 1) .. "]" end))
end

-- The table and key a path ends at in the Lua copy of a model, or nil: every step before the last must be a table
-- that is there; a last index must be on a list and may append (#list + 1) but not leave a hole; a last member must
-- not be on a list (the page refuses both too).
local function locate(model, keys)
    local cur = model
    for i = 1, #keys - 1 do
        cur = cur[keys[i]]
        if type(cur) ~= "table" then return nil end
    end
    local last = keys[#keys]
    if math.type(last) == "integer" then
        if last > #cur + 1 then return nil end
        for k in pairs(cur) do if type(k) ~= "number" then return nil end end
    elseif #cur > 0 then
        return nil
    end
    return cur, last
end

function LrBind.page(page, opts)
    opts = opts or {}
    local models = copy(opts.models or {})
    local events = copy(opts.events or {})
    local fields = {}   -- each model's top-level names, fixed at create as natively
    for name, m in pairs(models) do
        fields[name] = {}
        if type(m) == "table" then for k in pairs(m) do fields[name][k] = true end end
    end
    local handlers, nextId = {}, 0
    local self = { page = page }

    local function fire(name, ...)
        for _, h in pairs(handlers) do
            if h.name == name then h.fn(...) end
            if h.name == "*" then h.fn(name, ...) end
        end
    end

    local function bad(what, model, path)
        print(("[lrbind] %s: %s %s"):format(what, tostring(model), tostring(path)))
        return false
    end

    -- the keys of a path into model and where it ends in the Lua copy, or nil
    local function find(model, path)
        local keys = parsePath(path)
        if not models[model] or not keys or not fields[model][keys[1]] then return nil end
        local parent, key = locate(models[model], keys)
        if parent == nil then return nil end
        return keys, parent, key
    end

    function self:set(model, path, value)
        if not models[model] then return bad("set: no model", model, path) end
        local keys, parent, key = find(model, path)
        if not keys then return bad("set: bad path", model, path) end
        parent[key] = copy(value)
        return page:send("lrbind:set", { model = model, path = toPage(keys), value = value })
    end

    -- top-level fields only (set takes a path), each one the model had at create
    function self:merge(model, values)
        local m = models[model]
        if not m then return bad("merge: no model", model, "") end
        if type(values) ~= "table" then return bad("merge: no fields for", model, "") end
        local sent = {}
        for k, v in pairs(values) do
            if type(k) == "string" and fields[model][k] then
                m[k] = copy(v)
                sent[k] = v
            else
                bad("merge: not a top-level field of", model, k)
            end
        end
        return page:send("lrbind:merge", { model = model, fields = sent })
    end

    function self:push(model, path, value)
        local keys, parent, key = find(model, path)
        local list = keys and parent[key]
        if type(list) ~= "table" then return bad("push: not an array", model, path) end
        list[#list + 1] = copy(value)
        return page:send("lrbind:push", { model = model, path = toPage(keys), value = value })
    end

    function self:removeAt(model, path, index)
        local keys, parent, key = find(model, path)
        local list = keys and parent[key]
        local i = math.tointeger(index)
        if type(list) ~= "table" or not i or i < 1 or i > #list then
            return bad("removeAt: no entry " .. tostring(index) .. " in", model, path)
        end
        table.remove(list, i)
        return page:send("lrbind:removeAt", { model = model, path = toPage(keys), index = i - 1 })
    end

    function self:onModel(name, fn)
        nextId = nextId + 1
        handlers[nextId] = { name = name, fn = fn }
        return nextId
    end

    function self:off(id) handlers[id] = nil end
    function self:show() return page:show() end
    function self:hide() return page:hide() end
    function self:destroy() return page:destroy() end
    function self:model(name) return models[name] end

    page:on("lrbind:ready", function()
        page:send("lrbind:init", { models = models, events = events })
    end)
    page:on("lrbind:event", function(payload)
        if type(payload) ~= "table" then return end
        local args = payload.args or {}
        fire(tostring(payload.name), table.unpack(args, 1, tonumber(payload.n) or #args))
    end)
    page:on("lrbind:change", function(payload)
        if type(payload) ~= "table" then return end
        local path = toLua(payload.path)
        local keys, parent, key = find(payload.model, path)
        if keys then parent[key] = payload.value end
        fire("change", path, payload.value, payload.model)
    end)
    page:on("lrbind:error", function(payload)
        print("[lrbind] " .. tostring(type(payload) == "table" and payload.message or payload))
    end)
    return self
end

-- opts: document, layer, zIndex, visible, models, events (Open77.ui.create) + web = { WebUI.create options }.
-- opts.prefer = "web" forces the page (an A/B switch). Returns the handle and which surface it is, or nil, reason.
function LrBind.create(opts)
    local native = opts.prefer ~= "web" and opts.document and type(Open77) == "table"
        and type(Open77.ui) == "table" and type(Open77.ui.create) == "function"
    if native then
        local ui, reason = Open77.ui.create({
            document = opts.document, layer = opts.layer, zIndex = opts.zIndex, visible = opts.visible,
            models = opts.models, events = opts.events, projection = opts.projection, hotReload = opts.hotReload,
        })
        if ui then return ui, "native" end
        print("[lrbind] NativeUI refused the document (" .. tostring(reason) .. "), using the WebUI page")
    end
    if not opts.web or type(WebUI) ~= "table" then return nil, "no_surface" end
    local page, reason = WebUI.create(opts.web)
    if not page then return nil, reason end
    return LrBind.page(page, opts), "web"
end
