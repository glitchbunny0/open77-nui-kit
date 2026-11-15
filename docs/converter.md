# html2rml: from a WebUI page to a NativeUI document

`bin/html2rml` turns a WebUI page (HTML + CSS, with or without RmlUi binding syntax read by `lrbind.js`) into an RmlUi
document and sheet for Open77 NativeUI, plus a report of everything it could not map one to one. Python 3 stdlib only.
It means to drop nothing silently: every construct it cannot carry over is in the report with its file:line, what it
was and what to do instead. What it knowingly cannot see is under Limits.

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
| `--canvas 1920x1080` | the design canvas: `@media` is evaluated for it, `vw`/`vh` (and `cq*` without a container) become dp on it |
| `--px-per-dp 1` | CSS px per dp; `2` for a page drawn at 4K |
| `--root DIR` | the resource folder: image, font, stylesheet and script paths are read and written from it (`/web/assets/x.png`), as Open77 resolves them |
| `--vars fold\|native` | custom properties and `var()`: `fold` (default) folds them from the page's static cascade; `native` keeps them for RmlUi 6.3 to resolve (below) |
| `--strict` | exit 1 when the report has any item |
| `--report json` | also write `NAME.report.json` (items, the font list, the options) |

## The workflow

1. Convert. Read `NAME.report.md` first: scripts (their logic goes to the client Lua; the report lists the ids,
   classes, attributes, inline styles and custom properties each script touches), fonts (the `Open77.ui.loadFont`
   calls the client needs), then everything else.
2. `rml-check` with your cases. A converted document must load clean; if it does not, that is a converter bug.
3. `html-shot` + `rml-preview --compare`: the page (left) and the converted document (right), state by state.
4. Fix the page where the report says so, convert again. Keep the page as the source while it is the design; once the
   NativeUI document lives on its own, edit that instead.

The example's WebUI twin (`examples/side-menu/web/`) converts to a document that passes `rml-check` with the example's
cases and lays out pixel-identical to the hand-written `ui/menu.rml` in all six states (with `--vars native` too).

## Custom properties: `--vars fold` or `native`

RmlUi 6.3 has CSS custom properties: they cascade and inherit, `var()` resolves at compute time with fallbacks, a
`var()` inside a custom property resolves on the element that declares it, as in CSS (facts below).

- `fold` (the default until Open77's own build is checked in game): every `var()` is replaced by its value from the
  page's static cascade (specificity, source order, `!important`, inline styles, inheritance, resolution where
  declared). An override the cascade sees only in some states is re-stated under its selector, as a hand port would:
  a class state (`#mark.kill { --len: 14px }` -> `#mark.kill i { width: 14dp }`), `:hover`, an attribute
  (`.card[data-state="open"]`) or a structural pseudo-class on `data-for` rows (`.row:nth-child(odd)`). A
  re-statement is left out where a later rule sets the property in every state anyway (it would beat that rule in
  RmlUi). An override that can't be re-stated (a setter on another selector, an inline value up the tree, a value that
  differs between the elements one rule matches) is reported with the value used.
- `native`: custom property declarations are written (px -> dp, colours as hex, `calc()` folded, `url()` as the
  image path, `!important` dropped and reported), and a declaration keeps its `var()` wherever RmlUi computes the
  same value the folding would write. That is checked, not assumed: the rule is mapped once per value each variable
  takes on the page (and once with a made-up value of the same kind); the line must carry that value exactly where the
  `var()` is (`border: var(--w) solid var(--c)` -> `border: var(--w) var(--c)`). Where it does not, the declaration is
  folded as in `fold` mode, with the same re-statements and reports: `var()` inside `calc()` or a colour function
  (RmlUi has no `calc()`, reads `rgba()` alpha as 0-255), mappings that rewrite the value (`font-family` lists,
  shadows reordered, `border-radius: 50%`, em letter-spacing), a variable with no value and no fallback, a value
  RmlUi's parser refuses (a quoted string next to other values). States, attributes, `data-for` rows and per-element
  values then follow at run time, the utility-icon idiom (`.ico { mask: var(--m) }` with a per-element `--m`)
  included.

## What converts

Every row was checked against real RmlUi 6.3: the converted output loads without a warning (the fixtures in
`converter/tests/fixtures/` run through `rml-check`, some with the values RmlUi computes asserted), and where a value
could load but mean something else, the meaning was measured (`converter/tests/facts.py`, below).

| Page | RML / RCSS |
|---|---|
| `<html>`, `<head>`, `<body>` | `<rml>`, `<head>`, `<body>`; `<title>` kept; stylesheet links and `<style>` become one `<link type="text/rcss" href="NAME.rcss"/>`. A page that leaves them out gets them as a browser builds them; content after `</body>` or `</html>` and flow content written in `<head>` go into the body |
| HTML syntax | XML: void tags closed, attributes quoted, `&`/`<`/`"` escaped, entities written as characters, the browser's implied end tags (`</p>`, `</li>`, `</option>`, `</dt>`/`</dd>`, `</td>`/`</th>`/`</tr>`, table sections, `</rt>`/`</rp>`); `<div/>` stays open as in a browser (reported) |
| binding attributes (`data-model`, `data-for`, `data-if`, `data-visible`, `data-class-*`, `data-style-*`, `data-attr-*`, `data-event-*`, `data-value`, `data-checked`, `data-rml`, `data-alias-*`) and `{{ }}` | kept verbatim (other `data-*` attributes too: RmlUi ignores them and matches them in attribute selectors); `<img src="{{icon}}">` kept as is (reported: the path resolves from the document) |
| `hidden` attribute, `[hidden]` selectors | class `html2rml-hidden` + `.html2rml-hidden { display: none; }` at the head of the sheet (a page's own `.hidden` class stays its own) |
| bare text in a flex box | wrapped in a `<span>` (RmlUi lays out a bare text node in a flex box unpredictably); reported when structural, `+`/`~` or `span` rules select that box's children |
| inline `<svg viewBox>` with one `<path>` | Open77 `<path view-box=".." d=".."/>`, its fill/stroke/stroke-width (scaled to the drawn size) and width/height in a `path.svg-N` rule; selectors `svg`, `.icon path` follow it |
| `style="..."` | converted like any declaration (custom properties kept inline with `--vars native`) |
| width/height attributes of `<canvas>`, `<video>`, `<iframe>`, `<object>`, `<embed>`, table cells and columns | an inline width/height (on the `<div>` that stands in) |
| browser defaults the page relies on | the base block first: `display: block` for every block-level tag used (`inline-block` for buttons and `<path>`, table displays for tables), body margin/size/colour, heading sizes, `<b>`, `<i>`, list padding |
| `* { box-sizing }` | `box-sizing` on every tag used, in the base block |
| `:root`, `html` | `body` (RmlUi's document element); `:root` inside a longer selector (`:root .x`) becomes the class `html2rml-root`, put on `<body>`, so it keeps a class's specificity as in CSS |
| custom properties, `var()` | folded or kept: see `--vars` above |
| `calc()`, `min()`, `max()`, `clamp()` | folded when the units agree after conversion (`calc(80 * var(--u))` -> `40dp`) |
| units | `px` -> `dp` (/ `--px-per-dp`); `vw`, `vh`, `vmin`, `vmax` -> dp on the canvas; `cqw`, `cqh`, `cqi`, `cqb`, `cqmin`, `cqmax` -> dp on the query container's fixed size (the canvas without a container, as CSS takes the viewport); `rem` -> dp with the root element's font size as the cascade computes it (vw, `var()`, `calc()`, the `font` shorthand, `html, body {}`); `pt`, `in`, `cm`, `mm`, `pc`, `q` -> dp; `ms` -> `s`; `turn`, `grad` -> `deg`; `em`, `%` kept |
| `letter-spacing` / `line-height` in em or % | dp, with the declaring element's font size from the cascade (also for rules on elements only a script builds: what they inherit from the page's elements counts) |
| colours | `#RRGGBB` / `#RRGGBBAA` from `rgb()`/`rgba()` (comma or space/slash syntax, %), `hsl()`/`hsla()` (deg, rad, turn hues; half rounds up as in browsers), the 148 named colours; hex as written; `transparent` kept; `lab()`, `lch()`, `oklab()`, `oklch()` passed in the form RmlUi parses (space syntax, the hue as a plain degree number) |
| `currentColor`, colourless `border`/`box-shadow`/`text-shadow`/`drop-shadow` | the rule's own `color` when it has one, else the colour the elements get from the page's cascade (reported: a state that changes `color` does not change it) |
| `background` shorthand and longhands | `background-color` + `decorator` (layers in order, first on top as in CSS); size/position/repeat combine across rules as CSS cascades them |
| `background-image: url()` | `decorator: image(path [fit] [align])`: `background-size` contain/cover (`100% 100%` = fill, the default); at natural size `repeat`/`repeat-x`/`repeat-y` tile with RmlUi's fit modes of those names, `no-repeat` is `scale-none`; the position in two values (a 3-4 value position read; offsets in dp written in px, as RmlUi takes only px, % or keywords there); a path with spaces quoted |
| gradients | `linear-`, `radial-`, `conic-`, `repeating-*-gradient` with CSS directions, shapes and positions, in RmlUi's order (radial shape before size, `at` in two values); double-position stops written as two stops; `transparent` stops as the neighbour colour at zero alpha; `-webkit-linear-gradient()` as `linear-gradient()` (start side and angle turned); a linear gradient across an axis tiled along it by `background-size` (the stripe and grid idiom) as a `repeating-linear-gradient` with the tile as its period |
| `mask`, `-webkit-mask`, `mask-image`, `-webkit-mask-image` | `mask-image: image(...)` / a gradient, as for backgrounds |
| `font` shorthand | `font-style`, `font-weight`, `font-size`, `line-height` (`normal` -> `1.2`), `font-family` |
| `font-family` list | the first family (RmlUi takes one; it compares names lower-case); escaped names (`\5FAE\8F6F...`) decoded |
| `border`, `border-*` | width + colour (`solid` implied; `none` or a zero width -> `border-width: 0`; thin/medium/thick) |
| `border-radius: 50%` | half the box when the rule sets equal width and height |
| `display: grid; place-items: center` with one child | `display: flex` centred both ways |
| `inset`, `margin-inline`/`-block`, `padding-inline`/`-block` | kept / physical sides (left to right) |
| keywords | in any case (`DISPLAY: FLEX`); spelled RmlUi's way: `overflow: clip` -> hidden, `visibility: collapse` -> hidden, `text-align: start/end` -> left/right, `align-*: start/end` -> flex-start/flex-end, `position: sticky` -> relative (reported), `overflow-wrap: anywhere` -> `word-break: break-word`, `line-height: normal` -> 1.2, `opacity: 50%` -> 0.5, `flex: auto` -> `1 1 auto`, `direction` -> `-rmlui-direction` |
| `transition`, `animation` | RmlUi order (duration, delay, tween, count, alternate, paused, name); CSS easings -> the nearest RmlUi tween by maximum error over the curve: `ease` -> `quadratic-out`, `ease-out` -> `sine-out`, `ease-in` -> `sine-in`, `ease-in-out` -> `quadratic-in-out`, `linear` -> `linear-in-out`; `cubic-bezier()` fitted the same way, the `back` tweens included (reported); an item whose properties are all dropped is dropped; `all` is written alone (RmlUi refuses it in a list; reported unless it is the last item) |
| `@keyframes`, `@-webkit-keyframes` | `@keyframes`, frames converted like rules |
| `filter: drop-shadow(x y blur colour)` | `drop-shadow(colour x y blur)` (RmlUi wants the colour first) |
| `box-shadow`, `backdrop-filter`, `filter` (blur, brightness, ...), `transform` | kept, lengths in dp; transforms in the forms RmlUi parses: names in its spelling (`translateX`), `translate()`/`skew()` with both arguments, `scale()` in numbers (`50%` -> `0.5`) |
| `text-shadow` | `font-effect: shadow(...)` (no blur) or `glow(...)` |
| `@media` | evaluated for the canvas (width/height and min-/max-, ranges, orientation, aspect-ratio, hover, pointer, reduced motion); the matching rules are inlined |
| `@import` of a local file | inlined (RmlUi rejects `@import` and loses the rule after it), with its media query evaluated; `layer()` kept in source order (reported) |
| CSS nesting | flattened: `.a { &:hover {} .b {} }` -> `.a`, `.a:hover`, `.a .b`; a nested `@media` wraps the parent's selector |
| selectors | kept: type, class, id, `*`, attribute (`=`, `~=`, `\|=`, `^=`, `$=`, `*=`; names lower-cased like the markup's), combinators (` `, `>`, `+`, `~`), `:hover`, `:active`, `:focus`, `:focus-visible`, `:checked`, `:disabled`, `:nth-child()` and the other structural pseudo-classes, `:not(compound)` |
| `fill`, `stroke`, `stroke-*` | kept for Open77's `<path>` (vanilla RmlUi rejects them; `rml-check` allows them) |

## What is reported instead

| Construct | Why / what to do |
|---|---|
| `<script>` | dropped; the report lists what it touches (ids, selectors, toggled classes, `dataset` attributes, `setProperty` custom properties, inline styles, DOM writes): turn those into bindings or `ui:set`/`ui:style` calls. `lrbind.js` is listed as "nothing to do" |
| `@font-face` | the `Open77.ui.loadFont(path, family)` call per face (lower-case family; WOFF needs a TTF; a variable font is flagged) |
| `display: grid` (other than one centred child), grid properties | RmlUi has no grid: flex rows/columns with widths |
| `::before`, `::after`, other pseudo-elements | no generated content: a real element |
| `:not()` with a list or combinator, `:is()`, `:where()`, `:has()`, pseudo-classes RmlUi never sets (`:focus-within`, `:visited`, ...) | the rule is dropped (RmlUi would accept them silently and never match) |
| a selector on an attribute the conversion drops or rewrites (`[role]`, `a[href]`, `[title]`, `[width]` on a div, `input[type=number]`) | the rule is dropped: it could never match |
| `:last-child`, `:nth-last-child`, `:last-of-type`, `:only-*` on `data-for` rows | RmlUi keeps the template element after the rows: they never match one; a class from the model instead |
| `calc()` mixing units (`100% - 20px`), without spaces around `+`/`-`, adding a number to a length; units with no RmlUi form (`ch`, `ex`); `cq*` units whose container has no fixed size | the value for the canvas, or `ui:style` from the client |
| `var()` with no static value (set by a script, or nowhere) | the client sets the resulting property; overrides the converter cannot re-state; a per-element variable inside `@keyframes`; custom properties inside `@keyframes` (RmlUi cannot animate them) |
| `!important` (on custom properties too), `inherit`, `initial`, `unset` | RmlUi has none |
| `-webkit-*`, `-moz-*` (other than masks) | dropped |
| properties RmlUi does not have | `outline`, `user-select`, `object-fit`, `aspect-ratio`, `order`, `word-spacing`, list markers, counters, blend modes, `clip-path`, `container-type`, animation/transition longhands, ... (the property table in `converter/rmlui_spec.py` is generated from RmlUi's own registry); reported as missing whatever the value |
| values RmlUi does not have | `width: fit-content`, `display: contents`, dashed/dotted borders (written solid), elliptical radii, `steps()`, animation fill modes and `reverse`, an animation count of 0, colour hints in gradients, `in <colour space>` (sRGB is used), `hwb()`/`color()`/`color-mix()`, colour names RmlUi does not know (CSS system colours), a gradient layer sized or placed other than as a stripe (written filling the box), image `space`/`round` tiling (written as repeat), background sizes other than contain/cover/100% 100%, an image position offset from right/bottom in a length, image paths with `;` `{` `}` (RmlUi's parser cuts them), the other prefixed gradients |
| html and body both setting a property | RmlUi has one root element: both land on `<body>` and the later one wins |
| `@supports`, `@layer`, `@page`, `@container`, non-matching `@media`; `@import` with `supports()`, a non-matching media query, or after other rules; a sheet for `media="print"`, a `disabled` or alternate one, a `<style>` of another type or inside `<template>` | rules left out, as a browser leaves them (or, for `@layer`, kept in source order) |
| CSS syntax a browser recovers from | a string a newline ends (the declaration it is in is dropped, as in a browser), the root font size when it can't be read (rem is 16px) |
| markup | inline handlers (`onclick`: use `data-event-click`), `<a href>`, `title`/`alt`/`aria-*`/`role`/`tabindex`, `width`/`height` where a browser ignores them, `<canvas>`/`<video>`/`<iframe>` (a `<div>` stands in), unknown elements, `<input type>` RmlUi lacks (written as text), an SVG with several shapes (a sized `<div>` stands in), SVG gradients, clips, defs and path attributes Open77's `<path>` lacks, `url(#...)` paint, `<div/>`, paths inside bindings (they resolve from the document), `<meta>` other than charset/viewport, `<link rel=icon>` |

Dropped by rule without a report item, because they change nothing on screen: comments in CSS (HTML comments are
kept, in their order; those outside the body come before it), the doctype, `<meta charset>`/`viewport`,
`lang`/`xmlns`, `@charset`, generic font fallbacks (`sans-serif`: RmlUi has no generic families; non-generic
fallbacks are reported once per list and sheet).

## RmlUi 6.3 facts the mappings rest on

`converter/tests/facts.py` loads a throwaway document per fact in the kit's host and asserts what RmlUi did; it runs in
`scripts/test.sh`, so a new RmlUi pin that changes one of them fails there first.

- `rgba()` alpha is read as 0-255: `rgba(255, 0, 0, .5)` is fully transparent. Hex `#RRGGBBAA` is exact, hence hex out.
- `rgb()` space/slash syntax, 130 of the 148 CSS colour names, CSS system colours and `currentColor` are syntax
  errors; `lab()`, `lch()`, `oklab()`, `oklch()` parse (space syntax, alpha 0-1).
- `rem` is the document (body) font size, not a 16 px root: folded to dp with the page's own root size.
- `em` works for lengths and letter-spacing, but letter-spacing in em is resolved again on every descendant (a browser
  computes it once): folded to dp.
- `font-family` takes one family, strips quotes and lower-cases it; a list is a syntax error.
- The `font` shorthand has no line-height; `line-height: normal` is an error, a number works.
- `calc()`, `!important`, `inherit`, `initial` are syntax errors.
- `border` takes width and colour only; there is no `border-style`; radii take no `%`.
- `background` is the colour only; images and gradients are decorators. `decorator: image(src contain|cover|scale-none
  left top)` parses, so do the `repeat`, `repeat-x`, `repeat-y` fit modes, a quoted path, lists of decorators and
  `mask-image` with the same decorators. The image alignment takes px, % or keywords; dp is refused.
- Gradients parse CSS directions, shapes and double-position stops; a colour hint, the `turn` unit, a radial size
  before its shape, `in <colour space>` and a 4-value `at` position do not. Colour stops are premultiplied
  (`PropertyParserColorStopList.cpp`), so a transparent stop takes no colour of its own.
- `drop-shadow` wants the colour first.
- Transitions reject CSS easing names, `ms`, and `all` inside a list; tween names and seconds (with a delay) work. An
  animation needs a duration; keyframes with only `50%` load, and RmlUi fills a missing 0%/100% from the element's
  value (`Element.cpp`).
- Transform function names are case-sensitive (`skewX`, not `skewx`); `translate()` and `skew()` need two arguments,
  `scale()` numbers.
- `display: grid`, `position: sticky`, `overflow: clip`, `width: fit-content`, `text-align: start`,
  `align-items: start`, `opacity: 50%` are errors; `inset`, `flex: none`, `gap`, `box-shadow` lists with `inset`,
  `font-effect` lists and `backdrop-filter` parse.
- Structural pseudo-classes and `:not(compound)` match; `:not()` with a list, `:is()`, `::before` and unknown
  pseudo-classes are accepted silently and never match. RmlUi sets `hover`, `active`, `focus`, `focus-visible`,
  `checked`, `disabled`, `selected`, `placeholder-shown`, `drag` (source grep of `SetPseudoClass`).
- `:last-child`, `:nth-last-child`, `:last-of-type` never match `data-for` rows: the template element stays after them.
- Attribute selectors match; a `hidden` attribute hides nothing.
- `@import` is an invalid at-rule and swallows the rule after it.
- Custom properties cascade and inherit; `var()` resolves at compute time, with fallbacks, and inside a custom property
  on the element that declares it; overrides by attribute and `:nth-child` reach `data-for` rows. `!important` makes a
  custom property's value invalid where it is used; a quoted string next to other values is a syntax error. A variable
  on `<body>` set through body's class warns once (the class arrives after a first style pass), through the `body`
  tag it does not: a lone `:root` is written as `body`.
- Decorators render back to front from the last listed (`ElementEffects.cpp`): the first is on top, as in CSS.
- An absolutely positioned layer pinned with `inset: 0` inside a sized, positioned parent gets the parent's box (layout
  host), once the sheet makes the `div`s blocks.

## Limits

- The static cascade sees the page as written: classes a script toggles are known only from the selectors that name
  them. Variables a script sets (`setProperty`) are reported, not guessed.
- Selector matching for the cascade covers what the converter needs (custom properties, font sizes, colours,
  background layers, flex boxes for text wrapping, container sizes); specificity and source order follow CSS. RmlUi
  weighs a selector as tag 10 000, class 100 000, id 1 000 000 (`StyleSheetSelector.h`): ten tags equal one class
  there, never in CSS.
- `--vars native` decides per declaration from the values the page itself gives each variable; a value a script sets
  later is not among them.
- Not checkable offline: what Open77 adds (path fill defaults, `fx()`), whether Open77's build keeps RmlUi's custom
  properties on, hover states, anti-aliasing. `rml-preview` paints M/L/H/V/Z paths only.

## Tests

| What | Run |
|---|---|
| The RmlUi facts above | `converter/tests/facts.py [-v]` |
| The property table vs RmlUi's source | `converter/tests/test_spec.py [--regen]` |
| Fifteen fixtures (snapshot of rml/rcss/report + rml-check of the output, the values RmlUi computes where a fixture has `layout.json`), unit tests of the value layer | `converter/tests/run.py [--regen] [--unit[=LABEL]] [NAME]` |
| One planted bug per check: each must turn its fixture, unit test or fact red on its own | `converter/tests/mutants.py [ID ...]` |
| All of the above but the property table, as the kit's suite | `tests/converter.sh` (run by `scripts/test.sh`) |
| The side-menu twin: rml-check with the example's cases, pixel-identical layout to the hand-written document | `scripts/test.sh` |

A fixture is a folder under `converter/tests/fixtures/` with `index.html` (and its sheets), optional `args.txt`,
`cases.json` and `layout.json` (what RmlUi's layout must give: `{"expect": [{"sel": "#id", "bg": "#ff0000ff"}]}`);
`--regen` writes its `expected.*` from the current converter, review the diff before committing. A new check gets a
mutant in `converter/tests/mutants.py`.
