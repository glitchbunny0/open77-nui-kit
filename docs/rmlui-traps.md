# RmlUi traps every native document meets

Collected while porting real screens to Open77 NativeUI (RmlUi 6.3). Most of them fail silently in the game: the
screen just looks wrong. `rml-check` catches the ones RmlUi logs; `rml-preview` shows the rest.

## Layout

- **No default stylesheet.** Every element, `div` included, is inline until a sheet says otherwise: widths and
  heights on a `div` do nothing, absolute children fall back to the nearest block ancestor. First lines of every
  sheet: `div { display: block; box-sizing: border-box; }` (Open77's stock `nui://open77/open77.rcss` sets the
  display rule; your own sheet still needs it if it doesn't link that one).
- **`content-box` by default.** A padded fixed-width row grows by its padding. Set `border-box` on `div`.
- **Absolute children need a positioned parent.** A `position: absolute` underline inside a tab lands under the
  first positioned ancestor instead (the example's tabs did exactly this until `position: relative` went on `.tab`).
- **Text in a flex box needs a `<span>`.** A bare text node in a flex container lays out unpredictably.
- **`.gone { display: none }` loses to `#id { display: flex }`** (specificity). Write `#root .gone` and put it last.
- **No `var()`, `calc()`, grid, `background-size` or `-webkit-` prefixes.** Write the numbers. An underline, a
  partial bar or a divider is its own element.
- **Text can't be measured from RCSS.** A long name either overflows or gets cut: measure in your client (the
  sum of the font's advances per character, read once from the TTF) and switch a class (`small`, `two-lines`).
- **Mono text collapses spaces** unless `white-space: pre`.
- **Size layers with width/height**, not left/top/right/bottom pinning.
- **`data-if` / `data-visible` own the inline property.** When true they remove an inline `display`/`visibility`
  the markup set. Put display rules in the sheet.

## Data bindings

- **Every name the markup binds must exist in the first model.** Fields can't be added later; an unknown name drops
  the binding (`{{nope}}` keeps its braces on screen).
- **A bracket mistake in TEXT kills the rest of the document.** `{{a} }}`, a stray `}}`, nested `{{`, or `\'` inside
  `{{ }}` in text stops the XML parser: that text and everything after it never loads, with no error on screen.
- **Strings are false in conditions** unless `'1'` or `'true'`. **Booleans print `1`/`0`.**
- **`&&`, `||`, `|` and `?:` share one precedence level, left to right**; `!` binds to one factor; comparisons
  chain (`3 > 2 > 1` is false). `-x` is not an expression.
- **A misspelled event, or one missing from the document's `events`,** stops the rest of a `data-event` chain.
- **Markup arrays are 0-based**, Lua's are 1-based (`ui:set("m", "rows[1].name", ...)` from Lua is `rows[0]` in markup).
- Only four transforms exist: `format`, `round`, `to_upper`, `to_lower`.

## Open77 specifics

- **Fonts load by family through `Open77.ui.loadFont(path, family)`**; a path is relative to your own resource, so
  copy TTFs you need (with their licence). WOFF must be converted. Check the glyphs you ship exist in the font
  (Rajdhani has no arrow glyph).
- **The `x` / `y` motion channels move in screen pixels, not dp.** Anything that must meet the layout or a projected
  point is placed with `ui:style(sel, { left = "<n>dp", top = "<n>dp" })`; keep the channels for relative flourishes.
- **Panels that lean together share one `perspective`** on a full-screen root and one rotating wrapper; per-panel
  `perspective` gives each its own eye and the edges stop lining up.
- **Every rml/rcss/png/ttf goes in the manifest's `files`**, not `web_files`.
- **The client's instruction budget is small** (around 10k per resume): never deep-compare model tables to find
  changes, key fields instead; big lists go through `data-for`, not a `create` per row.
