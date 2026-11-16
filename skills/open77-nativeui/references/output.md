# What the tools print, and what to do

Real output, from a probe document with the usual mistakes planted in it.

## rml-check

```text
cases: 1  clicks ok: 0  model: m  outline: /tmp/rml-check-sxnzdk4j.outline.txt
WARN  Could not find variable name 'titel' in data model.  [one]
WARN  Could not load texture: missing.png  [one]
WARN  Syntax error parsing property declaration 'colr: red;' in p.rcss: 3.  [one]
EVENT cancle  data-event-click on <div#btn> at p.rml:7 calls an event that is not in the "events" of [one]
CLICK FAIL one: .row -> covered by div#over at 200,39 (want pick(2))
CLICK FAIL one: #zero -> zero-size box (400x0) at 200,74 (want close())
rml-check: FAIL
```

Exit status: 0 clean, 1 problems listed, 2 a usage or input problem (bad JSON, an empty case list, a misspelt
case key such as `click`, an unreadable document). With exit 2 the last line is `rml-check: <what is wrong>`.

### The summary line

`cases: N  clicks ok: M  model: X  outline: P`. `model` is the data model the cases bind to (the document's
`data-model`; a `note:` line before it says when there are several). `outline` is a text dump of the element tree
per case: tag, id, sorted classes, `[none]` for `display: none`, position and size, inline style, text. Read it
when a box is not where you expect: it is the layout RmlUi computed.

### `WARN  <message>  [cases]`

Something RmlUi logged while loading, laying out or drawing the document with that case's model. The cases in
brackets are the ones that produced it. Every WARN is a failure. The common ones:

| message | means | fix |
|---|---|---|
| `Could not find variable name 'x' in data model.` (with `Error in data expression ...` and `Could not add data-... view` lines) | the markup binds `x`, the case's model has no `x` | fix the name in the markup, or add the field to the FIRST model the client creates (fields can't be added later) |
| `Member x not found in data struct` | `a.x` where the struct `a` has no `x` | same, one level down |
| `Syntax error parsing property declaration '...' in <sheet>: <line>.` | an unknown property or a value RmlUi can't parse (a CSS-only property, `rgba()` with a 0-1 alpha it rejected, `ms`, `ease-out`) | `$KIT/docs/rmlui-traps.md`, "Values"; Open77's own properties (`fill`, `stroke-*`, `trim-*`, the glow / chromatic / scanlines filters, `fx()`) are registered, so a WARN on them is a real value error |
| `Could not load texture: <path>` | an image the document or sheet names is not on disk at that path | fix the path (relative to the document or sheet that names it); a case that tests a missing image on purpose passes `--allow 'Could not load texture: .*/x\.png$'` |
| `No font face defined` | text in a family no `@font-face`/`loadFont` provides | rml-check uses a stand-in font for every family, so this means the document sets no font-family at all |

WARN lines come in the order RmlUi logged them. A data expression error is three in a row: the message, the
expression in quotes, and a caret (`^`) under the fault.

`--allow REGEX` (repeatable) drops matching warnings. Use it only for a warning a case causes on purpose, and say
why next to the case.

### `EVENT <name>  data-event-<x> on <tag#id> at <file>:<line> calls an event that is not in the "events" of [cases]`

A `data-event-*` in the document (or a template it links) calls an event the client does not declare. This is
checked for every handler, clicked or not. Usually a typo (`cancle()`). Otherwise add the name to the case's
`events` list, which must match the `events` the client passes to `Open77.ui.create`. In the game an undeclared
event stops the rest of that handler's chain.

### `CLICK FAIL <case>: <selector> -> <what happened> (want <event(args)>)`

The click is a real mouse press at the centre of the first VISIBLE element the selector matches, so it fails for
the same reasons a player's click would:

| what happened | means | fix |
|---|---|---|
| `other(1)` (a different event or different args) | the click reached a handler, the wrong one or with the wrong arguments | numbers and bools are compared as RmlUi prints them: `pick(2)`, `toggle(1)` for true; check the binding (`pick(r.id)`) against the model |
| `nothing` | the element got the press, and no `data-event-click` fired | put the handler on the element (or an ancestor), or click the element that has it |
| `no element` | the selector matches no visible element in this case | wrong selector, or the element is hidden (`data-if`, `display: none`) in this state |
| `covered by <tag#id.cls> at x,y` | something else is on top at the element's centre: an overlay, a later sibling, `pointer-events: none` on the target | a full-screen layer usually needs `pointer-events: none`, or the target needs to come later / higher |
| `zero-size box (WxH) at x,y` | the element has no width or no height: an inline div without `display: block`, an empty flex child | size it; check the first sheet line (`div { display: block; }`) |
| `off screen at x,y` | its centre is outside the case's `size` | the layout pushed it out, or the case's `size` is too small |
| `a(1), then b(2)` | the click bubbled: the target's handler fired, then an ancestor's | in the game both run: stop it at the target, or move one of the handlers |
| `the case's "events" do not list 'x'` | the case expects an event it doesn't declare | add it to the case's `events` |

### `LOAD FAILED <case>`

The host could not create the document for that case at all (an unreadable or empty file). Broken XML does NOT
show up here: RmlUi loads what it parsed up to the fault and logs a WARN, so an unclosed tag, a bare `&` or a bracket
mistake in text (`{{a} }}`, a stray `}}`) shows as WARN lines plus everything after the fault missing from the
outline. When a screen is half empty, read the outline.

### `building the host failed:` and the lines after it

`rml-check` and `rml-preview` get the host from `scripts/build.py`: the prebuilt one from the kit's release when it
has one for these host sources, else one built from source. That stays silent while it works; on failure the tool
prints `building the host failed:` and then `build.py`'s own lines:

- `no prebuilt host (<why>), and none can be built: <why>`: no binary for this checkout and no compiler. `release
  vX.Y.Z has no rmlhost-....zip` means its `host/` changed since that release; `no release vX.Y.Z to fetch from`
  means no network, or the release does not exist yet. Install a C++17 compiler, or use a tagged kit.
- `no prebuilt host (<why>): building from source`, then a compile error: the source build itself failed; the
  compiler's message follows.
- `<name>.zip has SHA-256 <a>, the release lists <b>: not used`: the download is not the file the release published
  (a broken mirror or proxy). The host is built from source instead; tell a human.

## rml-preview

```text
not painted (see rml-preview --help): filter (#fxd)
ok   out/one.png 13 boxes
  WARN Could not find variable name 'titel' in data model.
  WARN Could not load texture: missing.png
  MISSING image missing.png (missing.png; sprite names are not resolved)
  NOT PAINTED decorator fx() (Open77)
sheet out/sheet.png
```

Exit status: 0 when the PNGs were written, even with notes. `--strict` makes it 1 when a case has a host warning,
a `MISSING`, a `NO FONT FACE` or a `NOT PAINTED` decorator or mask. 2 for a usage problem.

| line | means | what to do |
|---|---|---|
| `ok   <png> N boxes` | that state's image, with N laid-out boxes | open it and look |
| `WARN ...` | the same RmlUi warnings rml-check reports | fix them with rml-check first |
| `MISSING image <src> (<resolved path>; ...)` | a decorator or `<img>` names a file that isn't there; the box is painted without it | fix the path; sprite names from a sprite sheet are not resolved, so a sprite shows as missing here |
| `NO FONT FACE 'family' 600 italic: RmlUi draws no text in it` | no `--font` file gives that family, weight and style; RmlUi draws no text for it in the game either | pass the TTF of that weight (`--font fam=Regular.ttf,SemiBold.ttf,...`), or change the sheet to a weight you ship |
| `NOT PAINTED decorator fx() (Open77)`, a filter, a `<shape>`, an `<img>` element | the preview can't paint it | check it in the game; it isn't an error |
| `APPROXIMATED ...` (an `em`/`rem` length in a decorator, a content-box decorator, a mask on an element with children) | the painter drew it close to, not exactly as, RmlUi does | a few pixels may differ in the game; nothing to fix in the document |
| `NOTE image(<src> <fit>): Open77 cannot tile an image() decorator` | a `repeat`-style fit that Open77 doesn't do | use a single image, or a gradient |
| `not painted (see rml-preview --help): <property> (<elements>)` | properties the painter ignores, and where they occur | same: the game shows them |

`--compare <dir>` writes `compare.png`, each state next to the PNG of the same name in `<dir>` (mockups, or
html-shot's shots). `--sheet-crop X0,Y0,X1,Y1` crops each state in `sheet.png`.

## html2rml

`html2rml: wrote <dir>/<name>.rml, <dir>/<name>.rcss; report: N item(s) in <dir>/<name>.report.md`

Exit status: 0 written; 1 written, with `--strict` and a non-empty report; 2 a usage or input problem. The report's
sections:

| section | what to do |
|---|---|
| Scripts (dropped: port their logic to the client Lua) | each `<script>` with the ids, classes and styles it touches: that logic becomes model fields computed in the client, and events. `lrbind.js` itself needs nothing |
| Fonts (the client loads them), Font loading for the client | the `Open77.ui.loadFont` calls to make before creating the document; write the paths from your resource root |
| Markup | elements and attributes RmlUi has no form for (inline handlers, `<a href>`, `<canvas>`, ...) and what replaces them |
| Selectors (rules dropped) | selectors RmlUi can't match (pseudo-elements, `:has()`, ...): give the elements classes |
| Declarations and at-rules | values and rules with no RCSS form (grid beyond one centred child, unsupported units, `@supports`, ...) and the replacement |

Every row has the source `file:line`. Work through the report top to bottom; `--strict` in a test run makes a new
item fail.

## html-shot

`ok   <out>/<case>.png` per case, or `FAIL <case>: <why>`. A shot counts only when the page's bindings ran, so a page
without lrbind, a script error, a `{{ }}` left on the page or a timeout fails. `--find` prints the Chromium it would
use. Names are sanitised: anything outside `[A-Za-z0-9_.-]` becomes `_`.

## lrbind-sync

`lrbind-sync check <folder>` lists every copy of `lrbind.js` / `lrbind.lua` that isn't current and exits 1;
`refresh <folder>` rewrites them (`N copies, M refreshed`). A copy is current when it is the kit's file byte for
byte, optionally below comment lines of your own.
