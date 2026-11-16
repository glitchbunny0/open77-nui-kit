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
| `events` | no | the model event names the client declares (`events = { menu = { ... } }` in `Open77.ui.create`). Every `data-event-*` call in the document (and the templates it links) is checked against this list whether a case clicks it or not: a misspelt `cancle()` fails |
| `clicks` | no | `rml-check` presses the mouse at the centre of the first VISIBLE element matching `sel`, through the context as the game does (so `pointer-events: none`, a zero-size box or an overlay on top count), and expects exactly one model event, `event` with `args`. Numbers and bools are compared as RmlUi prints them (`pick(2)`, `toggle(1)`). `CLICK FAIL` names what happened instead: `nothing`, `no element`, `covered by <tag#id.cls>`, `zero-size box`, `off screen`, or `a(1), then b(2)` when a parent's handler fires too |
| `place` | no | `{ "selector": [left, top] }` in dp: positions your client writes at run time with `ui:style` (a marker over a projected point). Set before layout |
| `size` | no | `[width, height]` of the context, default `[1920, 1080]`; 1 dp = 1 px here |

## Values

- Arrays are 0-based in markup (`rows[0]`) and JSON arrays; your Lua builds them 1-based, NativeUI maps them.
- An empty Lua table becomes an empty array (`[]`), as NativeUI maps it. `fake_nui.lua`'s `F.json` does the same.
- Numbers print with up to three decimals, trailing zeros cut (`3.0` prints `3`, `1/3` prints `0.333`). Booleans print `1`/`0`.
- Every field the markup binds must be in the model of every case: RmlUi drops a binding to a name it does not know
  (the check reports `Member x not found in data struct`).
- An empty case list (`[]`) is an error, and so is a misspelt key (`click` for `clicks`). Warnings are reported per
  case (each case runs in its own host process), and an image or texture the document names but that is not on disk
  is reported (`Could not load texture: ...`).

## Making cases from your client Lua

Hand-written cases drift from what the client really builds. `fake-nui/fake_nui.lua` lets plain Lua 5.4 run the client
file: `Open77.ui.create` returns a fake document that keeps its models, `onModel` handlers are fired like the markup's
`data-event-click` would, and `CreateThread` / `Wait` / `SetTimeout` run as coroutines on 16 ms passes.

```lua
local F = dofile("path/to/open77-nui-kit/fake-nui/fake_nui.lua")
F.install()
dofile("client/menu.lua")                       -- your file, unchanged
local doc = F.counted("Menu.open", nil, Menu.open, SHOP, 2400) and F.last   -- F.last: the document the client created
F.event(doc, "pick", "overture")                -- what the markup's data-event-click would call
F.settle()                                      -- run the scheduler for 60 passes (F.frames(n): n passes)
io.write(F.json({ F.case("picked", doc, { { "#foot .buy", "buy", {} } }) }), "\n")
```

Write the cases with `io.write`, not `print`: `F.install()` replaces `print` by a capture into `F.logs` (all arguments,
tab-joined; `FAKE_NUI_LOG=1` echoes it to stderr), so a `print(F.json(...))` writes nothing and the cases file stays
empty. `F.counted(where, nil, fn, ...)` runs `fn` and counts its instructions, like every `F.event` and scheduler pass
(`Menu.open` runs outside both, so it is wrapped). `examples/side-menu/models.lua` is the whole pattern.

### What the fake does

It follows the NativeUI reference (`Open77.ui` documents, data and events). The scheduler:

- `CreateThread(fn)` starts the task on the **next** pass, as Open77 does (there is no `CreateThreadNow`); a thread
  that calls `CreateThread` does not see the new task run before it yields. `Wait(ms)` wakes at the first pass at or
  after its time; due tasks run by wake time, then by creation order (the game documents neither tie-break).
  `SetTimeout` / `ClearTimeout` are tasks of the same scheduler. `F.frames(n)` runs n passes of 16 ms.
- **Instruction budget:** Open77 allows 1,500,000 instructions per coroutine resume (500,000 on older clients) and
  raises `Open77 script execution budget exceeded` past it; the fake does the same (`F.budget`, nil switches it off).
  `F.maxInstr` / `F.maxWhere` report the largest piece of work seen, counted in steps of 1,000 (about 1% over the VM's
  count). The instruction budget is not what limits UI work: Open77 also gives the client host 6 ms of Lua per frame,
  and instructions do not measure time, so keep the work per frame small as well.

The document (`F.last`, `Open77.ui.create(...)`):

- **Models:** every model of `models` is kept by name, by reference. `merge` asserts a field the model lacks and an
  unknown model. `set` / `push` / `removeAt` take the documented paths (`"items[2].stock"`, indices 1-based) and assert
  a path that leads nowhere (the game reports it as an error event). A document with several models gives its first
  model (by name) as the case's `model` and the others under `models`.
- **Listeners:** `onModel(name, fn)` (also `"*"`), `on(type, [selector], fn)`, `onEvent(kind, fn)`; each returns an id
  for `off(id)`. You drive the platform's side: `F.loaded(doc)`, `F.event(doc, name, ...)`, `F.emit(doc, type, detail)`
  / `F.key(doc, key)` (DOM listeners all fire; the selector is not matched), `F.docError(doc, command, message)`.
- **Focus:** `focus()` takes the input lease; `blur()`, `hide()` and `destroy()` release it (`onEvent("focus")` gets
  `blur` with reason `released`); `F.focusLost(doc, "taken", "other_resource")` takes it away; `F.focusResult = false`
  makes `focus()` fail with `focus_unavailable` and an `error` event, as in the game. `destroy()` fires `closed`.
- **Create:** `document` or `source` (exactly one), at most 32 live documents (`nativeui_instance_limit`),
  `undeclared_file:<path>` for a missing file, `loadFont` with `font_not_declared`, `registerEffect`, `stats`.
- **Recorded only** (`F.stubs`, `doc.calls`): `text`, `rml`, `attr`, `class`, `setClasses`, `value`, `click`,
  `focusElement`, `blurElement`, `scrollTo`, `insert`, `remove`, `stylesheet`, `watch`, `unwatch`, `setZIndex`,
  `animate`, `keyframes`, `stop`, `settle`, `layout`, `scene`, `anchor`, `unanchor`, `projection`, `style`. They return
  `true`, run no layout and never call a callback. `create(parent, spec)` returns a fresh `"@serial"`; `rect` is nil
  ("until published"); `state()` is a table with `loaded`, `visible`, `focused` and a size.

`F.json` writes cases: floats keep every digit, an empty table is `[]`, every character outside ASCII is a `\u` escape
(ASCII reaches the cases file unchanged through any shell; Windows PowerShell 5 reads a program's output in the
console's code page), and NaN, infinity, a string that is not UTF-8, a table that mixes an array with other keys and a
function are errors naming the path (`$.rows[2].price`).

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
