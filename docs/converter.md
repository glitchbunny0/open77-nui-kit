# html2rml: from a WebUI page to a NativeUI document

`bin/html2rml` turns a WebUI page (HTML + CSS, with or without RmlUi binding syntax read by `lrbind.js`) into an RmlUi
document and sheet for Open77 NativeUI, plus a report of everything it could not map one to one. Python 3 stdlib only.
It never drops anything silently: every construct it cannot carry over is in the report with its file:line, what it was
and what to do instead.

```sh
bin/html2rml web/index.html --out ui --name menu --root .     # ui/menu.rml, ui/menu.rcss, ui/menu.report.md
bin/rml-check ui/menu.rml cases.json                          # the converted document in real RmlUi, every state
bin/html-shot web/index.html cases.json --out shots           # the page in a browser, one shot per case
bin/rml-preview ui/menu.rml cases.json --font kitraj=fonts/Rajdhani-Regular.ttf --out out --compare shots
```

| Option | Meaning |
|---|---|
| `--css extra.css` | more sheets after the page's own (repeatable) |
| `--name NAME` | output names (default: the page's file name) |
| `--canvas 1920x1080` | the design canvas: `@media` is evaluated for it, `vw`/`vh` become dp on it |
| `--px-per-dp 1` | CSS px per dp; `2` for a page drawn at 4K |
| `--root DIR` | the resource folder: image and font paths are written from it (`/web/assets/x.png`), as Open77 resolves them |
| `--strict` | exit 1 when the report has any item |
| `--report json` | also write `NAME.report.json` (items + the font list) |

## The workflow

1. Convert. Read `NAME.report.md` first: scripts (their logic goes to the client Lua; the report lists the ids,
   classes, attributes, inline styles and custom properties each script touches), fonts (the `Open77.ui.loadFont`
   calls the client needs), then everything else.
2. `rml-check` with your cases. A converted document must load clean; if it does not, that is a converter bug.
3. `html-shot` + `rml-preview --compare`: the page (left) and the converted document (right), state by state.
4. Fix the page where the report says so, convert again. Keep the page as the source while it is the design; once the
   NativeUI document lives on its own, edit that instead.

The example's WebUI twin (`examples/side-menu/web/`) converts to a document that passes `rml-check` with the example's
cases and lays out pixel-identical to the hand-written `ui/menu.rml` in all six states.

## What converts

Every row was checked against real RmlUi 6.3: the converted output loads without a warning (the fixtures in
`converter/tests/fixtures/` run through `rml-check`), and where a value could load but mean something else, the meaning
was measured (`converter/tests/facts.py`, below).

| Page | RML / RCSS |
|---|---|
| `<html>`, `<head>`, `<body>` | `<rml>`, `<head>`, `<body>`; `<title>` kept; stylesheet links and `<style>` become one `<link type="text/rcss" href="NAME.rcss"/>` |
| HTML syntax | XML: void tags closed, attributes quoted, `&`/`<` escaped, entities written as characters, implied `</p>`/`</li>` closed |
| binding attributes (`data-model`, `data-for`, `data-if`, `data-visible`, `data-class-*`, `data-style-*`, `data-attr-*`, `data-event-*`, `data-value`, `data-checked`, `data-rml`, `data-alias-*`) and `{{ }}` | kept verbatim (other `data-*` attributes too: RmlUi ignores them and matches them in attribute selectors) |
| `hidden` attribute, `[hidden]` selectors | class `hidden` + `.hidden { display: none; }` at the head of the sheet (low priority, like the browser's own rule) |
| bare text in a flex box | wrapped in a `<span>` (RmlUi lays out a bare text node in a flex box unpredictably) |
| inline `<svg viewBox>` with one `<path>` | Open77 `<path view-box=".." d=".."/>`, its fill/stroke/stroke-width (scaled to the drawn size) and width/height in a `path.svg-N` rule; selectors `svg`, `.icon path` follow it |
| `style="..."` | converted like any declaration |
| width/height attributes of a `<canvas>`/`<video>`/`<iframe>` | an inline width/height on the `<div>` that stands in |
| browser defaults the page relies on | the base block first: `display: block` for every block-level tag used (`inline-block` for buttons and `<path>`, table displays for tables), body margin/size/colour, heading sizes, `<b>`, `<i>`, list padding |
| `* { box-sizing }` | `box-sizing` on every tag used, in the base block |
| `:root`/`html` | `body` (RmlUi's document element) |
| custom properties, `var()` | folded, with fallbacks and nesting, from the page's static cascade: a property set on an ancestor reaches its descendants; a state rule's override (`#mark.kill { --len: 14px }`) re-states the declarations using it (`#mark.kill i { width: 14dp }`); a selector naming a state (`#mark.head i`) gets that state's values |
| `calc()`, `min()`, `max()`, `clamp()` | folded when the units agree after conversion (`calc(80 * var(--u))` -> `40dp`) |
| units | `px` -> `dp` (/ `--px-per-dp`); `vw`, `vh`, `vmin`, `vmax` -> dp on the canvas; `rem` -> dp with the page's root size; `pt`, `in`, `cm`, `mm`, `pc` -> dp; `ms` -> `s`; `turn`, `grad` -> `deg`; `em`, `%` kept |
| `letter-spacing` / `line-height` in em or % | dp, with the declaring element's font size from the cascade |
| colours | `#RRGGBB` / `#RRGGBBAA` from `rgb()`/`rgba()` (comma or space/slash syntax, %), `hsl()`/`hsla()`, the 148 named colours; hex as written; `transparent` kept |
| `currentColor`, colourless `border`/`box-shadow`/`drop-shadow` | the rule's own `color` when it has one |
| `background` shorthand and longhands | `background-color` + `decorator` (layers in order, first on top as in CSS); size/position/repeat combine across rules as CSS cascades them |
| `background-image: url()` | `decorator: image(path [contain|cover] [align])` from `background-size` (`100% 100%` = fill, the default); `no-repeat` at natural size -> `scale-none` + position |
| gradients | `linear-`, `radial-`, `conic-`, `repeating-*-gradient` with CSS directions, shapes and positions; double-position stops written as two stops; `transparent` stops as the neighbour colour at zero alpha |
| `mask`, `-webkit-mask`, `mask-image`, `-webkit-mask-image` | `mask-image: image(...)` / a gradient |
| `font` shorthand | `font-style`, `font-weight`, `font-size`, `line-height` (`normal` -> `1.2`), `font-family` |
| `font-family` list | the first family (RmlUi takes one; it compares names lower-case) |
| `border`, `border-*` | width + colour (`solid` implied; `none` -> `border-width: 0`; thin/medium/thick) |
| `border-radius: 50%` | half the box when the rule sets equal width and height |
| `display: grid; place-items: center` with one child | `display: flex` centred both ways |
| `inset`, `margin-inline`/`-block`, `padding-inline`/`-block` | kept / physical sides (left to right) |
| keywords RmlUi spells differently | `overflow: clip` -> hidden, `visibility: collapse` -> hidden, `text-align: start/end` -> left/right, `align-*: start/end` -> flex-start/flex-end, `position: sticky` -> relative (reported), `overflow-wrap: anywhere` -> `word-break: break-word`, `line-height: normal` -> 1.2, `opacity: 50%` -> 0.5, `flex: auto` -> `1 1 auto`, `direction` -> `-rmlui-direction` |
| `transition`, `animation` | RmlUi order (duration, delay, tween, count, alternate, paused, name); CSS easings -> the nearest RmlUi tween by maximum error over the curve: `ease` and `ease-out` -> `sine-out`, `ease-in` -> `sine-in`, `ease-in-out` -> `quadratic-in-out`, `linear` -> `linear-in-out`; `cubic-bezier()` fitted the same way (reported) |
| `@keyframes`, `@-webkit-keyframes` | `@keyframes`, frames converted like rules |
| `filter: drop-shadow(x y blur colour)` | `drop-shadow(colour x y blur)` (RmlUi wants the colour first) |
| `box-shadow`, `backdrop-filter`, `filter` (blur, brightness, ...), `transform` | kept, lengths in dp, transform names in RmlUi's spelling (`translateX`) |
| `text-shadow` | `font-effect: shadow(...)` (no blur) or `glow(...)` |
| `@media` | evaluated for the canvas (width/height and min-/max-, ranges, orientation, aspect-ratio, hover, pointer, reduced motion); the matching rules are inlined |
| `@import` of a local file | inlined (RmlUi rejects `@import` and loses the rule after it) |
| selectors | kept: type, class, id, `*`, attribute (`=`, `~=`, `|=`, `^=`, `$=`, `*=`), combinators (` `, `>`, `+`, `~`), `:hover`, `:active`, `:focus`, `:focus-visible`, `:checked`, `:disabled`, `:nth-child()` and the other structural pseudo-classes, `:not(compound)` |
| `fill`, `stroke`, `stroke-*` | kept for Open77's `<path>` (vanilla RmlUi rejects them; `rml-check` allows them) |

## What is reported instead

| Construct | Why / what to do |
|---|---|
| `<script>` | dropped; the report lists what it touches (ids, selectors, toggled classes, `dataset` attributes, `setProperty` custom properties, inline styles, DOM writes): turn those into bindings or `ui:set`/`ui:style` calls. `lrbind.js` is listed as "nothing to do" |
| `@font-face` | the `Open77.ui.loadFont(path, family)` call per face (lower-case family; WOFF needs a TTF; a variable font is flagged) |
| `display: grid` (other than one centred child), grid properties | RmlUi has no grid: flex rows/columns with widths |
| `::before`, `::after`, other pseudo-elements | no generated content: a real element |
| `:not()` with a list or combinator, `:is()`, `:where()`, `:has()`, pseudo-classes RmlUi never sets (`:focus-within`, `:visited`, ...) | the rule is dropped (RmlUi would accept them silently and never match) |
| `calc()` mixing units (`100% - 20px`), units with no RmlUi form (`ch`, `ex`) | the value for the canvas, or `ui:style` from the client |
| `var()` with no static value (set by a script, or nowhere) | the client sets the resulting property; overrides the converter cannot re-state; a per-element variable inside `@keyframes` |
| `!important`, `inherit`, `initial`, `unset` | RmlUi has none |
| `-webkit-*`, `-moz-*` (other than masks) | dropped |
| properties RmlUi does not have | `outline`, `user-select`, `object-fit`, `aspect-ratio`, `order`, `word-spacing`, list markers, counters, blend modes, `clip-path`, animation/transition longhands, ... (the property table in `converter/rmlui_spec.py` is generated from RmlUi's own registry) |
| values RmlUi does not have | `width: fit-content`, `display: contents`, dashed/dotted borders (written solid), elliptical radii, `steps()`, animation fill modes and `reverse`, colour hints in gradients, `hwb()`/`lab()`/`color-mix()`, a tiled background image (written at natural size), background sizes other than contain/cover/100% 100% |
| `@supports`, `@layer`, `@page`, `@container`, non-matching `@media`, a sheet for `media="print"` | rules left out (or, for `@layer`, kept in source order) |
| markup | inline handlers (`onclick`: use `data-event-click`), `<a href>`, `title`/`alt`/`aria-*`/`role`/`tabindex`, `<canvas>`/`<video>`/`<iframe>` (a `<div>` stands in), unknown elements, `<input type>` RmlUi lacks (written as text), an SVG with several shapes (a sized `<div>` stands in), `<meta>` other than charset/viewport, `<link rel=icon>` |

Dropped by rule without a report item, because they change nothing on screen: comments in CSS (HTML comments are
kept), the doctype, `<meta charset>`/`viewport`, `lang`/`xmlns`, `@charset`, generic font fallbacks (`sans-serif`:
RmlUi has no generic families; non-generic fallbacks are reported).

## RmlUi 6.3 facts the mappings rest on

`converter/tests/facts.py` loads a throwaway document per fact in the kit's host and asserts what RmlUi did; it runs in
`scripts/test.sh`, so a new RmlUi pin that changes one of them fails there first.

- `rgba()` alpha is read as 0-255: `rgba(255, 0, 0, .5)` is fully transparent. Hex `#RRGGBBAA` is exact, hence hex out.
- `rgb()` space/slash syntax, 130 of the 148 CSS colour names and `currentColor` are syntax errors.
- `rem` is the document (body) font size, not a 16 px root: folded to dp with the page's own root size.
- `em` works for lengths and letter-spacing, but letter-spacing in em is resolved again on every descendant (a browser
  computes it once): folded to dp.
- `font-family` takes one family, strips quotes and lower-cases it; a list is a syntax error.
- The `font` shorthand has no line-height; `line-height: normal` is an error, a number works.
- `calc()`, `!important`, `inherit`, `initial` are syntax errors.
- `border` takes width and colour only; there is no `border-style`; radii take no `%`.
- `background` is the colour only; images and gradients are decorators. `decorator: image(src contain|cover|scale-none
  left top)` parses, so do lists of decorators and `mask-image` with the same decorators.
- Gradients parse CSS directions, shapes and double-position stops; a colour hint and the `turn` unit do not. Colour
  stops are premultiplied (`PropertyParserColorStopList.cpp`), so a transparent stop takes no colour of its own.
- `drop-shadow` wants the colour first.
- Transitions reject CSS easing names and `ms`; tween names and seconds (with a delay) work. An animation needs a
  duration; keyframes with only `50%` load, and RmlUi fills a missing 0%/100% from the element's value (`Element.cpp`).
- Transform function names are case-sensitive (`skewX`, not `skewx`).
- `display: grid`, `position: sticky`, `overflow: clip`, `width: fit-content`, `text-align: start`,
  `align-items: start`, `opacity: 50%` are errors; `inset`, `flex: none`, `gap`, `box-shadow` lists with `inset`,
  `font-effect` lists and `backdrop-filter` parse.
- Structural pseudo-classes and `:not(compound)` match; `:not()` with a list, `:is()`, `::before` and unknown
  pseudo-classes are accepted silently and never match. RmlUi sets `hover`, `active`, `focus`, `focus-visible`,
  `checked`, `disabled`, `selected`, `placeholder-shown`, `drag` (source grep of `SetPseudoClass`).
- Attribute selectors match; a `hidden` attribute hides nothing.
- `@import` is an invalid at-rule and swallows the rule after it.
- Decorators render back to front from the last listed (`ElementEffects.cpp`): the first is on top, as in CSS.
- An absolutely positioned layer pinned with `inset: 0` inside a sized, positioned parent gets the parent's box (layout
  host), once the sheet makes the `div`s blocks.

## Limits

- The static cascade sees the page as written: classes a script toggles are known only from the selectors that name
  them. Variables a script sets (`setProperty`) are reported, not guessed.
- Selector matching for the cascade covers what the converter needs (custom properties, font sizes, background layers,
  flex boxes for text wrapping); specificity ties follow source order like CSS.
- Not checkable offline: what Open77 adds (path fill defaults, `fx()`), hover states, anti-aliasing. `rml-preview` paints
  M/L/H/V/Z paths only.

## Tests

| What | Run |
|---|---|
| The RmlUi facts above | `converter/tests/facts.py [-v]` |
| The property table vs RmlUi's source | `converter/tests/test_spec.py [--regen]` |
| Ten fixtures (snapshot of rml/rcss/report + rml-check of the output), unit tests of the value layer | `converter/tests/run.py [--regen] [NAME]` |
| The side-menu twin: rml-check with the example's cases, pixel-identical layout to the hand-written document | `scripts/test.sh` |

A fixture is a folder under `converter/tests/fixtures/` with `index.html` (and its sheets), optional `args.txt` and
`cases.json`; `--regen` writes its `expected.*` from the current converter, review the diff before committing.
