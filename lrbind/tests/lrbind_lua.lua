-- lrbind.lua offline: the WebUI facade speaks the page protocol of lrbind.js and keeps the NativeUI API.
-- Run from lrbind/: lua5.4 tests/lrbind_lua.lua   (LRBIND_LUA=<copy> tests a copy instead: mutation runs)
local pass, fail = 0, 0
local function check(cond, what)   -- io.write: print is captured below
    if cond then pass = pass + 1 else fail = fail + 1; io.write("FAIL " .. what .. "\n") end
end

local printed = {}
local realPrint = print
print = function(...) local t = {} for i = 1, select("#", ...) do t[#t + 1] = tostring(select(i, ...)) end printed[#printed + 1] = table.concat(t, " ") end

local function fakePage()
    local p = { sent = {}, handlers = {}, shown = 0, destroyed = false }
    function p:send(event, payload) self.sent[#self.sent + 1] = { event, payload }; return true end
    function p:on(event, fn) self.handlers[event] = fn; return #self.sent end
    function p:show() self.shown = self.shown + 1 end
    function p:hide() end
    function p:destroy() self.destroyed = true end
    function p:fire(event, payload) return self.handlers[event](payload) end
    function p:last() return self.sent[#self.sent] end
    return p
end

dofile(os.getenv("LRBIND_LUA") or "lrbind.lua")
check(type(LrBind) == "table" and type(LrBind.page) == "function", "LrBind.page exists")

-- init on ready, with the current state (and again after a page reload)
local page = fakePage()
local ui = LrBind.page(page, {
    models = { voice = { mode = "Normal", distance = 20, items = { { name = "a" }, { name = "b" } }, empty = {} } },
    events = { voice = { "pick" } },
})
check(#page.sent == 0, "nothing sent before the page is ready")
page:fire("lrbind:ready", {})
local init = page:last()
check(init[1] == "lrbind:init" and init[2].models.voice.mode == "Normal" and init[2].events.voice[1] == "pick", "ready -> lrbind:init with models and events")

-- set: 1-based paths become 0-based, the Lua copy follows
check(ui:set("voice", "distance", 8) == true, "set returns the send result")
check(page:last()[1] == "lrbind:set" and page:last()[2].path == "distance" and page:last()[2].value == 8, "set scalar")
ui:set("voice", "items[2].name", "B")
check(page:last()[2].path == "items[1].name", "set shifts array indices to 0-based")
check(ui:model("voice").items[2].name == "B", "set updates the Lua copy at the 1-based index")
local before = #page.sent
check(ui:set("voice", "items[0].name", "x") == false and #page.sent == before, "index 0 is refused, nothing sent")
check(ui:set("nope", "x", 1) == false, "unknown model refused")
check(ui:set("voice", "mode.deeper", 1) == false, "a path through a scalar is refused")
ui:set("voice", "items[3]", { name = "c" })
check(ui:model("voice").items[3].name == "c" and page:last()[2].path == "items[2]", "set appends at n + 1")

-- merge / push / removeAt
ui:merge("voice", { mode = "Whisper", distance = 3 })
check(page:last()[1] == "lrbind:merge" and page:last()[2].fields.mode == "Whisper" and ui:model("voice").distance == 3, "merge")
ui:push("voice", "items", { name = "d" })
check(page:last()[1] == "lrbind:push" and page:last()[2].path == "items" and #ui:model("voice").items == 4, "push")
ui:removeAt("voice", "items", 1)
check(page:last()[1] == "lrbind:removeAt" and page:last()[2].index == 0 and ui:model("voice").items[1].name == "B", "removeAt 1 -> index 0")
check(ui:removeAt("voice", "items", 9) == false, "removeAt out of range refused")
check(ui:push("voice", "mode", 1) == false, "push on a scalar refused")
ui:push("voice", "empty", "first")
check(ui:model("voice").empty[1] == "first", "push into {} (an empty array)")

-- paths: only name, [n] (n >= 1) and .member; anything else is refused before the copy or the page sees it, so the two
-- never act on different places (natively the same call would fail)
do
    local function same(a, b)
        if type(a) ~= "table" or type(b) ~= "table" then return a == b end
        for k, v in pairs(a) do if not same(v, b[k]) then return false end end
        for k in pairs(b) do if a[k] == nil then return false end end
        return true
    end
    local function snapshot(t) local c = {} for k, v in pairs(t) do c[k] = type(v) == "table" and snapshot(v) or v end return c end
    local p = fakePage()
    local u = LrBind.page(p, { models = { m = { rows = { { name = "a" }, { name = "b" } }, grid = { { 1, 2 }, { 3, 4 } }, n = 1, e = {} } } })
    local copyBefore = snapshot(u:model("m"))
    for _, bad in ipairs({ "rows[0]", "rows[0].name", "rows[x]", "rows[ 1 ].name", "rows[-1]", "rows[1.5]", "rows[]",
                          "rows..name", "rows.", "rows[1]name", " rows", "1rows", "rows[4]", "rows[3].name", "nope", "n.deeper", "rows[1][1]", "rows.name" }) do
        local sent = #p.sent
        local ok = u:set("m", bad, "Z")
        check(ok == false and #p.sent == sent and same(u:model("m"), copyBefore), "set refuses the path " .. bad)
    end
    for _, bad in ipairs({ "rows[x]", "rows[-1]", "rows[ 1 ]", "nope", "n" }) do
        local sent = #p.sent
        check(u:push("m", bad, { name = "p" }) == false and #p.sent == sent and same(u:model("m"), copyBefore), "push refuses the path " .. bad)
        check(u:removeAt("m", bad, 1) == false and #p.sent == sent and same(u:model("m"), copyBefore), "removeAt refuses the path " .. bad)
    end
    local sent = #p.sent
    local okFrac, retFrac = pcall(u.removeAt, u, "m", "rows", 1.5)
    check(okFrac and retFrac == false and #p.sent == sent and #u:model("m").rows == 2, "removeAt refuses a fractional index " .. tostring(retFrac))
    u:removeAt("m", "rows", 2.0)
    check(p:last()[2].index == 1 and #u:model("m").rows == 1, "removeAt takes an integral float")
    u:push("m", "rows", { name = "b" })
    u:set("m", "grid[2][1]", 9)
    check(p:last()[2].path == "grid[1][0]" and u:model("m").grid[2][1] == 9, "nested indices shift each")
    u:set("m", "rows[3]", { name = "c" })
    check(p:last()[2].path == "rows[2]" and #u:model("m").rows == 3, "set at #list + 1 appends")
    -- merge: top-level fields the model had at create; a path key or a new name is refused, nothing written for it
    local fields = { rows = { { name = "x" } }, ["rows[1].name"] = "M", nope = 1 }
    u:merge("m", fields)
    local sentFields = p:last()[2].fields
    check(p:last()[1] == "lrbind:merge" and sentFields.rows and sentFields["rows[1].name"] == nil and sentFields.nope == nil
        and u:model("m")["rows[1].name"] == nil and u:model("m").nope == nil, "merge keeps top-level fields the model has")
    fields.rows[1].name = "changed later"
    check(u:model("m").rows[1].name == "x", "merge copies what it keeps (a later change of the caller's table stays out)")
    local ok, err = pcall(function() return u:merge("m", nil) end)
    check(ok and err == false, "merge without fields is refused, not an error " .. tostring(err))
    -- event arity follows n, holes and all
    local count
    u:onModel("two", function(...) count = select("#", ...) end)
    p:fire("lrbind:event", { model = "m", name = "two", args = {}, n = 2 })
    check(count == 2, "an event with two empty arguments reaches the handler with two")
end

-- a reload re-sends the state as it is now
page:fire("lrbind:ready", {})
check(page:last()[1] == "lrbind:init" and page:last()[2].models.voice.mode == "Whisper" and #page:last()[2].models.voice.items == 3, "second ready re-sends current state")

-- events: arguments unpacked, holes kept by n, "*" sees all
local got, star = nil, {}
ui:onModel("pick", function(a, b, c) got = { a, b, c } end)
local starId = ui:onModel("*", function(name, ...) star[#star + 1] = name end)
page:fire("lrbind:event", { model = "voice", name = "pick", args = { 3, nil, "x" }, n = 3 })
check(got and got[1] == 3 and got[2] == nil and got[3] == "x", "event args unpacked with a hole")
check(star[1] == "pick", "* listener sees the event name")
ui:off(starId)
page:fire("lrbind:event", { model = "voice", name = "pick", args = {}, n = 0 })
check(#star == 1, "off removes a listener")

-- change: the page's 0-based path comes back 1-based, the copy follows
local change
ui:onModel("change", function(path, value, model) change = { path, value, model } end)
page:fire("lrbind:change", { model = "voice", path = "items[0].name", value = "Z" })
check(change and change[1] == "items[1].name" and change[2] == "Z" and change[3] == "voice", "change path back to 1-based")
check(ui:model("voice").items[1].name == "Z", "change updates the Lua copy")

-- page errors land in the client log
page:fire("lrbind:error", { message = "Could not find data variable with name 'x'." })
check(printed[#printed]:find("[lrbind] Could not find", 1, true) ~= nil, "lrbind:error is printed")

-- create(): NativeUI when available, the page otherwise or on prefer = "web"
local nativeOpts
Open77 = { ui = { create = function(o) nativeOpts = o; return { kind = "doc" } end } }
WebUI = { create = function(o) local p = fakePage(); p.opts = o; return p end }
local h, kind = LrBind.create({ document = "ui/voice.rml", layer = "hud", models = { voice = {} }, web = { entry = "web/index.html" } })
check(kind == "native" and h.kind == "doc" and nativeOpts.document == "ui/voice.rml" and nativeOpts.layer == "hud", "create picks NativeUI")
h, kind = LrBind.create({ document = "ui/voice.rml", prefer = "web", models = { voice = {} }, web = { entry = "web/index.html" } })
check(kind == "web" and h.page.opts.entry == "web/index.html", "prefer = web forces the page")
Open77.ui.create = function() return nil, "nativeui_instance_limit" end
h, kind = LrBind.create({ document = "ui/voice.rml", models = { voice = {} }, web = { entry = "web/index.html" } })
check(kind == "web" and printed[#printed]:find("nativeui_instance_limit", 1, true), "a refused document falls back to the page and says why")
Open77 = {}
h, kind = LrBind.create({ document = "ui/voice.rml", models = {}, web = { entry = "web/index.html" } })
check(kind == "web", "no Open77.ui -> page")
WebUI = nil
h, kind = LrBind.create({ document = "ui/voice.rml", models = {} })
check(h == nil and kind == "no_surface", "no surface at all -> nil, reason")

print = realPrint
print(("lrbind.lua: %d passed, %d failed"):format(pass, fail))
if fail > 0 then os.exit(1) end
