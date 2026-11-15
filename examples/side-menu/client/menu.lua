-- side menu example: the client half of ui/menu.rml. Holds the shop's rows, fills the "menu" model and answers its
-- events. In the game: Menu.open(shop) from your resource; offline, models.lua drives it on fake_nui.
Menu = {}
local DOC, MODEL = "ui/menu.rml", "menu"
local EVENTS = { "tab", "pick", "buy", "confirm", "cancel", "close" }
local RARITY = { common = "#D6D0D0", uncommon = "#1DED83", rare = "#2570D4", epic = "#9D2BF5", legendary = "#FB932E" }

local function money(n)
    local s = tostring(math.floor(n))
    while true do
        local t, k = s:gsub("^(%d+)(%d%d%d)", "%1 %2")
        s = t
        if k == 0 then break end
    end
    return "E$ " .. s
end

-- every name the markup binds, present from the start
local function emptyModel()
    return { title = "", place = "", cash = "", tab = "", tabs = {}, rows = {}, pick = "", canBuy = false,
        askOn = false, askHead = "", askLine = "", askPrice = "" }
end

local ui, shop, state

local function rowsOf(tab)
    local out = {}
    for _, it in ipairs(shop.items) do
        if it.tab == tab then
            out[#out + 1] = { id = it.id, name = it.name, desc = it.desc, price = money(it.price),
                rarity = RARITY[it.rarity] or "#2A2A38", own = state.owned[it.id] == true }
        end
    end
    return out
end

local function find(id)
    for _, it in ipairs(shop.items) do if it.id == id then return it end end
end

local function refresh()
    local it = find(state.pick)
    ui:merge(MODEL, { tab = state.tab, rows = rowsOf(state.tab), pick = state.pick, cash = money(state.cash),
        canBuy = it ~= nil and not state.owned[it.id] and state.cash >= it.price })
end

function Menu.open(s, cash)
    shop, state = s, { tab = s.tabs[1].id, pick = "", cash = cash, owned = {} }
    ui = Open77.ui.create({ document = DOC, layer = "menu", visible = true,
        models = { [MODEL] = emptyModel() }, events = { [MODEL] = EVENTS } })
    ui:merge(MODEL, { title = s.title, place = s.place, tabs = s.tabs })
    refresh()
    ui:onModel("tab", function(id) state.tab, state.pick = id, ""; refresh() end)
    ui:onModel("pick", function(id) state.pick = id; refresh() end)
    ui:onModel("buy", function()
        local it = find(state.pick)
        if not it or state.owned[it.id] or state.cash < it.price then return end
        ui:merge(MODEL, { askOn = true, askHead = it.name, askPrice = money(it.price),
            askLine = "Paid from your cash. You keep " .. money(state.cash - it.price) .. "." })
    end)
    ui:onModel("confirm", function()
        local it = find(state.pick)
        state.cash, state.owned[it.id] = state.cash - it.price, true
        ui:merge(MODEL, { askOn = false })
        refresh()
    end)
    ui:onModel("cancel", function() ui:merge(MODEL, { askOn = false }) end)
    ui:onModel("close", function() ui:destroy() end)
    ui:focus()
    return ui
end
