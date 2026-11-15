# lrbind: one markup for a WebUI page and its NativeUI twin

`lrbind.js` runs RmlUi's data bindings (`{{x}}`, `data-for`, `data-if`, `data-class-*`, `data-event-*`, ...) inside a
WebUI page; `lrbind.lua` drives that page with the NativeUI document API. A screen is written once, as HTML/CSS with
RmlUi binding syntax: the page shows it through the shim, the native document reads the same markup natively, and the
client Lua calls `set` / `merge` / `push` / `removeAt` / `onModel` the same way on both. A resource that uses it ships
its own copies; `bin/lrbind-sync` writes them and tells you when one is stale.

## Using it in a resource

```sh
bin/lrbind-sync add path/to/<res>        # writes <res>/web/lrbind.js + <res>/client/lrbind.lua
bin/lrbind-sync refresh path/to/resources # after updating the kit: refresh every copy under that folder
bin/lrbind-sync check path/to/resources   # exit 1 when a copy differs from the kit's (put it in your test run)
```

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
`LrBind.init({ models = {...}, events = {...} })` from the page; `LrBind.set(name, path, value)` updates it.

## Rules that come from RmlUi itself (all reproduced by the shim, all measured against RmlUi 6.3)

- **Every field the markup names must be in the initial model.** An unknown name is a parse error: the binding is
  dropped and a `{{nope}}` text keeps its braces. Fields cannot be added later.
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
- **A failing call keeps the old text, or prints `#rmlui#`.** `{{nofn(a)}}` alone stays as written; next to a working
  binding in the same text it shows RmlUi's placeholder `#rmlui#`. Only the four transforms above exist.

## Not verifiable offline (check in the game before relying on it)

- How Open77 maps Lua values into the native model (integers vs floats print alike either way; only > 2^53 differ).
- Whether native `onModel("change")` also reports `data-event` assignments, and the path format it uses (the facade
  reports both, 1-based).
- `ev.*` in events: the shim gives `mouse_x`/`mouse_y` (CSS px of the page, not screen px), `button` (RmlUi
  numbering), modifier keys, `wheel_delta_*`, `value`; RmlUi's `key_identifier` has no equivalent.
- NaN prints `nan` here; the game's MSVC runtime prints `-nan(ind)` for 0/0.

## Tests

| What | Where | Run |
|---|---|---|
| Parity: 50 cases, every snapshot compared with real RmlUi 6.3 | `tests/parity/` (`cases.mjs`, `golden.json`) | `bin/lrbind-parity` |
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
