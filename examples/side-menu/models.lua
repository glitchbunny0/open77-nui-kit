-- side menu example: run client/menu.lua offline on the kit's fake Open77.ui, click through it like a player, and print
-- one case per state (its model + the clicks rml-check makes in real RmlUi) as JSON.
--   lua5.4 models.lua > cases.json        (from examples/side-menu)
local F = dofile("../../fake-nui/fake_nui.lua")
F.install()
dofile("client/menu.lua")

local SHOP = {
    title = "STREET GEAR", place = "WATSON · KABUKI",
    tabs = { { id = "guns", label = "GUNS" }, { id = "mods", label = "MODS" }, { id = "ammo", label = "AMMO" } },
    items = {
        { id = "unity", tab = "guns", name = "Unity", desc = "Reliable 9 mm. The street standard.", price = 450, rarity = "common" },
        { id = "lexington", tab = "guns", name = "Lexington", desc = "Light pistol, fast trigger.", price = 300, rarity = "common" },
        { id = "overture", tab = "guns", name = "Overture", desc = "Heavy revolver. Six rounds that count.", price = 1800, rarity = "rare" },
        { id = "malorian", tab = "guns", name = "Malorian Arms 3516", desc = "One of a kind, with a story and a price to match.", price = 50000, rarity = "legendary" },
        { id = "scope", tab = "mods", name = "Kanetsugu Scope", desc = "Short scope for pistols.", price = 600, rarity = "uncommon" },
    },
}

local cases = {}
local function state(name, steps, clicks)
    local doc = Menu.open(SHOP, 2400) and F.last
    for _, s in ipairs(steps) do F.event(doc, s[1], table.unpack(s, 2)); F.settle(2) end
    cases[#cases + 1] = F.case(name, doc, clicks)
end

state("browse", {}, { { "#tabs .tab", "tab", { "guns" } }, { "#list .row", "pick", { "unity" } }, { "#foot .close", "close", {} } })
state("picked", { { "pick", "overture" } }, { { "#foot .buy", "buy", {} } })
state("confirm", { { "pick", "unity" }, { "buy" } }, { { "#ask .btn.go", "confirm", {} } })
state("bought", { { "pick", "unity" }, { "buy" }, { "confirm" } })
state("mods", { { "tab", "mods" } })
state("empty", { { "tab", "ammo" } })
io.write(F.json(cases), "\n")
