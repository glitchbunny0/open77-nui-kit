# Cases: the states of a screen

`rml-check` and `rml-preview` take the same input: a JSON array of cases, one per state of your screen. A case is
what your client Lua would have put into the document's data model at that moment, plus what to click.

```json
[
  {
    "name": "browse",
    "model": { "title": "STREET GEAR", "tab": "guns", "tabs": [{ "id": "guns", "label": "GUNS" }], "rows": [] },
    "events": ["tab", "pick", "close"],
    "clicks": [
      { "sel": "#tabs .tab", "event": "tab", "args": ["guns"] },
      { "sel": "#foot .close", "event": "close", "args": [] }
    ]
  }
]
```

| Field | Required | Meaning |
|---|---|---|
| `name` | yes | the state's name; also the PNG's file name in `rml-preview` |
| `model` | usually | the data model's fields, bound under the document's `data-model` name (or `--model NAME`) |
| `models` | no | more models by name, `{ "other": { ... } }`, for a document with several `data-model` roots |
| `events` | no | the model event names the client declares (`events = { menu = { ... } }` in `Open77.ui.create`). A `data-event-*` that calls a name not listed here is an error, as in the game |
| `clicks` | no | `rml-check` clicks the first VISIBLE element matching `sel` (real RmlUi event dispatch) and expects the model event `event` with `args` (compared as text). `CLICK FAIL ... -> nothing` means the click reached no listener |
| `place` | no | `{ "selector": [left, top] }` in dp: positions your client writes at run time with `ui:style` (a marker over a projected point). Set before layout |
| `size` | no | `[width, height]` of the context, default `[1920, 1080]`; 1 dp = 1 px here |

## Values

- Arrays are 0-based in markup (`rows[0]`) and JSON arrays; your Lua builds them 1-based, NativeUI maps them.
- An empty Lua table becomes an empty array (`[]`), as NativeUI maps it. `fake_nui.lua`'s `F.json` does the same.
- Numbers print with up to three decimals, trailing zeros cut (`3.0` prints `3`, `1/3` prints `0.333`). Booleans print `1`/`0`.
- Every field the markup binds must be in the model of every case: RmlUi drops a binding to a name it does not know
  (the check reports `Member x not found in data struct`).

## Making cases from your client Lua

Hand-written cases drift from what the client really builds. `fake-nui/fake_nui.lua` lets plain `lua5.4` run the
client file: `Open77.ui.create` returns a fake document that keeps the model, `onModel` handlers can be fired like a
click, `CreateThread`/`Wait` run as coroutines on 16 ms frames.

```lua
local F = dofile("path/to/open77-nui-kit/fake-nui/fake_nui.lua")
F.install()
dofile("client/menu.lua")                       -- your file, unchanged
local doc = Menu.open(SHOP, 2400) and F.last    -- F.last: the document the client created
F.event(doc, "pick", "overture")                -- what the markup's data-event-click would call
F.settle()                                      -- run waiting threads for 60 frames
print(F.json({ F.case("picked", doc, { { "#foot .buy", "buy", {} } }) }))
```

`F.maxInstr` / `F.maxWhere` report the most Lua instructions any single resume or event took: a client resume gets
roughly 10 000 before the game warns, so a test can assert on it. `examples/side-menu/models.lua` is the whole
pattern.

## Hooks for rml-preview

`--hook hook.py` loads a Python file with two optional functions:

```python
def place(case):               # positions the client writes at run time, merged into case["place"]
    return {"#marker": [960, 540]}

def paint(draw, el, case, rgba):   # after the built-in paint of each box; el has tag, cls, x, y, w, h, ...
    if el["tag"] == "shape" and "ring" in el["cls"]:
        draw.ellipse([el["x"], el["y"], el["x"] + el["w"], el["y"] + el["h"]], outline=rgba("#5EF6FF"))
```

Use it for Open77-only elements vanilla RmlUi lays out but never paints (`<shape>`, `fx()`), drawn from your model.
