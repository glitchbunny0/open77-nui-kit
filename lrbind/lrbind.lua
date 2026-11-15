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

-- "items[2].name" (1-based, Lua) <-> "items[1].name" (0-based, the page)
local function toPage(path)
    local bad = false
    local out = path:gsub("%[(%-?%d+)%]", function(n)
        n = tonumber(n)
        if n < 1 then bad = true end
        return "[" .. (n - 1) .. "]"
    end)
    if bad then return nil end
    return out
end

local function toLua(path)
    return (tostring(path):gsub("%[(%d+)%]", function(n) return "[" .. (tonumber(n) + 1) .. "]" end))
end

-- the table and key a path ends at, inside the Lua copy of a model (nil when it runs through a scalar)
local function locate(model, path)
    local parent, key = nil, nil
    local cur = model
    for name, rest in path:gmatch("([^%.%[]*)([^%.]*)") do
        if name ~= "" then
            if type(cur) ~= "table" then return nil end
            parent, key, cur = cur, name, cur[name]
        end
        for idx in rest:gmatch("%[(%d+)%]") do
            if type(cur) ~= "table" then return nil end
            parent, key, cur = cur, tonumber(idx), cur[tonumber(idx)]
        end
    end
    return parent, key
end

function LrBind.page(page, opts)
    opts = opts or {}
    local models = copy(opts.models or {})
    local events = copy(opts.events or {})
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

    function self:set(model, path, value)
        local m = models[model]
        if not m then return bad("set: no model", model, path) end
        local pagePath = toPage(path)
        local parent, key = locate(m, path)
        if not pagePath or not parent then return bad("set: bad path", model, path) end
        parent[key] = copy(value)
        return page:send("lrbind:set", { model = model, path = pagePath, value = value })
    end

    function self:merge(model, fields)
        local m = models[model]
        if not m then return bad("merge: no model", model, "") end
        for k, v in pairs(fields) do m[k] = copy(v) end
        return page:send("lrbind:merge", { model = model, fields = fields })
    end

    function self:push(model, path, value)
        local m = models[model]
        local parent, key
        if m then parent, key = locate(m, path) end
        local list = parent and parent[key]
        if type(list) ~= "table" then return bad("push: not an array", model, path) end
        list[#list + 1] = copy(value)
        return page:send("lrbind:push", { model = model, path = toPage(path), value = value })
    end

    function self:removeAt(model, path, index)
        local m = models[model]
        local parent, key
        if m then parent, key = locate(m, path) end
        local list = parent and parent[key]
        if type(list) ~= "table" or type(index) ~= "number" or index < 1 or index > #list then
            return bad("removeAt: no entry " .. tostring(index) .. " in", model, path)
        end
        table.remove(list, index)
        return page:send("lrbind:removeAt", { model = model, path = toPage(path), index = index - 1 })
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
        local m = models[payload.model]
        local parent, key
        if m then parent, key = locate(m, path) end
        if parent then parent[key] = payload.value end
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
