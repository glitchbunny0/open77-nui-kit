# lrbind: one markup for a WebUI page and its NativeUI twin

`lrbind.js` runs RmlUi's data bindings (`{{x}}`, `data-for`, `data-if`, `data-class-*`, `data-event-*`, ...) inside a
WebUI page; `lrbind.lua` drives that page with the NativeUI document API. A screen is written once, as HTML/CSS with
RmlUi binding syntax: the page shows it through the shim, the native document reads the same markup natively, and the
client Lua calls `set` / `merge` / `push` / `removeAt` / `onModel` the same way on both. A resource that uses it ships
its own copies; `bin/lrbind-sync` writes them and tells you when one is stale. Both files start with their MIT notice
(`lrbind.js` also carries RmlUi's, whose data-binding code it ports); it is part of the file and every copy keeps it.

## Using it in a resource

```sh
bin/lrbind-sync add path/to/<res>        # writes <res>/web/lrbind.js + <res>/client/lrbind.lua
bin/lrbind-sync refresh path/to/resources # after updating the kit: refresh every copy under that folder
bin/lrbind-sync check path/to/resources   # exit 1 when a copy differs from the kit's (put it in your test run)
```

**What counts as a copy** (the rule `lrbind-sync` applies; a census of your own should apply the same one): every
file named `lrbind.js` or `lrbind.lua` under the folder, wherever it sits (`web/js/lrbind.js` and `web/data/lrbind.js`
too); only `node_modules`, `.git` and the kit's own tree are skipped. A copy is current when it is the kit's file
byte for byte, licence header included. Lines of your own above the kit's first line (`// SPDX-License-Identifier:
MIT`) may stay if they are comments (`//` in lrbind.js, `--` in lrbind.lua) or blank: `check` accepts them and
`refresh`/`add` keep them. Anything else above that line, or a copy without it (from before the header), is stale,
and `refresh` writes the kit's file whole.

Page: `<script src="lrbind.js"></script>` before the page's own script, bindings under one `data-model` root:

```html
<div id="voice" data-model="voice" data-class-talking="state == 'talking'">
  <span class="mode">{{mode | to_upper}}</span> <span>{{distance}}m</span>
  <i data-for="bar, i : bars" data-class-lit="lit > i"></i>
</div>
```

Client (manifest: `client_script "client/lrbind.lua"` before the script that calls it):

```lua
local ui, kind = LrBind.create({
    document = "ui/voice.rml", layer = "hud",                  -- NativeUI when the client has it
    models = { voice = { mode = "Normal", distance = 20, state = "idle", lit = 0, bars = { 1, 2, 3 } } },
    events = { voice = {} },
    web = { entry = "web/index.html", layer = "hud", transparent = true },   -- the page otherwise
})
ui:merge("voice", { distance = 8, state = "talking" })        -- identical call on both surfaces
```

`LrBind.page(page, opts)` wraps a page you created yourself. In a plain browser (a mockup, no `Open77`), call
`LrBind.init({ models = {...}, events = {...} })` from the page; `LrBind.set(name, path, value)` updates it. A path
walks the model's own members only, and an index may append at the end of a list but not leave a hole; `merge`
takes top-level fields of the model.

## Rules that come from RmlUi itself (all reproduced by the shim, all measured against RmlUi 6.3)

- **Every field the markup names must be in the initial model.** An unknown name is a parse error: the binding is
  dropped and a `{{nope}}` text keeps its braces. Fields cannot be added later.
- **Some model names cannot be bound:** `it`, `it_index`, `ev`, `true`, `false`, `size`, `literal` (in any case:
  `Size` too), and any name that does not start with a letter or holds anything but `a-z A-Z 0-9 _`. Such a field is
  refused with a warning at create, and markup naming it gets a parse error.
- **An assignment writes an existing scalar or nothing.** In `data-event-*`, `obj.nope = 5` (a missing member),
  `list.size = 9`, `obj = 5` (a whole struct or list) and an alias that points past the end of a list are refused with
  a warning, and the rest of the chain does not run. Assignments take member paths (`a.b = 1`); `list[0] = 1` is a
  parse error natively too.
- **A bracket mistake in text kills the rest of the document.** `{{a} }}`, a stray `}}`, nested `{{`, an unclosed
  `{{` before the next tag, or `\'` inside `{{ }}` in TEXT stops RmlUi's XML parser: that text and everything after it
  never load. The shim removes the same nodes and says so through `lrbind:error`. Escapes are fine in attributes.
- **Markup must parse as both XML and HTML.** Close every tag, quote attributes, write `&amp;&amp;` and `&lt;` (a raw
  `<` inside `{{ }}` is legal RML but starts a tag in HTML). Use div/span/b/i, not `<p>` (HTML re-nests it).
- **Strings are not truthy.** In a condition only `'1'`/`'true'` (any case) are true; `'abc'` and `'yes'` are false.
- **Booleans print as 1 and 0** (`{{flag}}` shows `1`); numbers print `%.3f` with trailing zeros cut (`1/3` -> `0.333`,
  `-0.0001` -> `-0`), exact halves round to even (`0.0625` -> `0.062`). `format(x, p[, trim])`, `round` (floor of
  x + 0.5), `to_upper`/`to_lower` (ASCII only) are the transforms; a bad call yields an empty value.
- **Precedence:** `!` binds to one factor (`!a == b` is `(!a) == b`); `&&`, `||`, `|` and `?:` share one level and run
  left to right; a ternary's branches take the rest (`t ? 'p' : 'q' | to_upper` pipes only `'q'`); comparisons chain
  (`3 > 2 > 1` is false). `-x` is not an expression (only number literals take a minus).
- **`data-if` / `data-visible` own the inline property:** when true they REMOVE an inline `display` / `visibility`
  the markup set (`style="display: flex"` is gone after the first true). Put display rules in the stylesheet.
- **Global names shadow `data-for` iterators**; a misspelled event or one missing from `events` stops the rest of a
  `data-event` chain. Array paths are 0-based in markup and 1-based from Lua (`lrbind.lua` shifts them).
- **`data-for` takes over its element.** Every other binding on that element (`data-alias-*`, `data-if`, ...) applies
  to each copy instead, never to the element itself, so an alias there cannot name the list. `x : list` and
  `x, i : list` name the iterator and index; any other count of names (`a, b, c : list`) leaves `it`/`it_index`. When
  the view fails (bad syntax, an unknown list) the element stays, empty: its content never becomes elements.
- **`data-checked`:** a bool is the state; any other value checks the box only when it equals the box's non-empty
  `value` attribute (`data-checked="s"` with `s = 'a'` checks `value="a"`; `'true'` checks nothing). Every change of
  the checked state (a click, a view, `data-attrif-checked`) fires `change`, so `data-event-change` sees it and the
  box's `data-checked`/`data-value` writes the state back: a checkbox `true`/`false`, a radio its value. Checking a
  radio unchecks every other radio with the same `name` (an empty name counts) in its `<form>`, or outside any form.
- **A failing call keeps the old text, or prints `#rmlui#`.** `{{nofn(a)}}` alone stays as written; next to a working
  binding in the same text it shows RmlUi's placeholder `#rmlui#`. Only the four transforms above exist.

## Not verifiable offline (check in the game before relying on it)

- How Open77 maps Lua values into the native model (integers vs floats print alike either way; only > 2^53 differ).
- Whether native `onModel("change")` also reports `data-event` assignments, and the path format it uses (the facade
  reports both, 1-based).
- `ev.*` in events: the shim gives the parameters RmlUi gives, with RmlUi's types: `mouse_x`/`mouse_y` on mouse events
  (CSS px of the page, not the game's screen px); `button` (0 left, 1 right, 2 middle) on mousedown/mouseup/click/
  dblclick only; `ctrl_key`, `shift_key`, `alt_key`, `meta_key`, `caps_lock_key`, `num_lock_key`, `scroll_lock_key`
  as ints 0/1 (in Lua `0` is true: test `== 1`); `wheel_delta_x`/`_y` in wheel notches (the DOM's pixels / 100 or
  lines / 3; how the game scales a notch is not verified); a change's `value` (a number from a range input, text
  otherwise) and, from a checkbox or radio, `checked`. RmlUi's `key_identifier` has no equivalent. A range input's
  `data-value` writes a number into the model, as natively.
- NaN prints `nan` here; the game's MSVC runtime prints `-nan(ind)` for 0/0.

## Tests

| What | Where | Run |
|---|---|---|
| Parity: every snapshot of every case compared with real RmlUi 6.3, form controls included (the harness drops only the classes and local styles RmlUi's controls give themselves) | `tests/parity/` (`cases.mjs`, `golden.json`) | `bin/lrbind-parity` |
| Page protocol, form controls, mockup mode | `tests/protocol.test.mjs` | `node lrbind/tests/protocol.test.mjs` |
| Lua facade | `tests/lrbind_lua.lua` | `cd lrbind && lua5.4 tests/lrbind_lua.lua` |
| All of the above, plus the golden regenerated through real RmlUi and compared, and one planted bug per check | `tests/suite.py` (the kit's `tests/lrbind.sh`) | `scripts/test.sh` |

`npm ci` in `tests/` once (jsdom, pinned; `bin/lrbind-parity` does it for you). After adding or changing a parity case,
`bin/lrbind-parity --regen` runs the cases through real RmlUi (the kit's `rmlhost parity`) and rewrites `golden.json`;
commit both. The kit's suite regenerates the golden the same way on every run and fails when it differs from the
committed file, so a stale golden or a hand edit cannot pass. A change to the shim's semantics that `golden.json`
disagrees with is a shim bug unless RmlUi says otherwise. Mutation runs: `LRBIND_SHIM=<copy>` for both node tests,
`LRBIND_LUA=<copy>` for the Lua one; `tests/suite.py` keeps the table of planted bugs, each with the check it must turn
red.

Your own markup can get the same proof: write a cases file that imports `T` and `sharedBlock` from
`lrbind/tests/parity/cases.mjs` (a block of your real document between `<!-- name: begin -->` and `<!-- name: end -->`
markers), then `bin/lrbind-parity my-cases.mjs my-golden.json --regen` once and `bin/lrbind-parity my-cases.mjs
my-golden.json` in your test run.
