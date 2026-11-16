---
name: open77-nativeui
description: Build, port, restyle or debug an Open77 NativeUI screen (an RmlUi 6.3 document, RML + RCSS, driven by Open77.ui from client Lua) offline with open77-nui-kit, without starting the game. Use when writing or changing .rml / .rcss files for Open77, porting a WebUI page (HTML/CSS) to NativeUI, making one markup serve a WebUI page and its NativeUI twin (lrbind), generating cases from client Lua with fake-nui, or reading rml-check, rml-preview, html2rml or html-shot output.
license: MIT
compatibility: Linux, macOS or Windows. Needs the open77-nui-kit folder (a clone or a vendored copy), a C++17 compiler (g++, clang++; on Windows MSVC or MinGW-w64), Python 3.8+, Lua 5.4. Pillow for rml-preview, a Chromium for html-shot.
---

# Open77 NativeUI screens with open77-nui-kit

A NativeUI screen is an RmlUi document: RML markup + an RCSS sheet, created from client Lua with
`Open77.ui.create` and fed through data models. RmlUi is not a browser. It has no default stylesheet, its own CSS
dialect, and most mistakes fail silently in the game: the screen just looks wrong. The kit runs the real RmlUi 6.3
offline, so you can check and see a screen before anyone starts the game.

## 0. Find the kit

`$KIT` below is the kit's folder: the one holding `bin/rml-check`. It is a clone of open77-nui-kit, or a copy
vendored into the project (look for `*/bin/rml-check` next to a `fake-nui/` folder). Build the RmlUi host once; the
tools build it on demand too, so this only moves the wait:

```sh
"$KIT"/scripts/build.sh          # fetches RmlUi 6.3 and builds the host into a cache dir, about a minute the first time
```

Try the loop on the kit's example before your own screen. It touches nothing in the kit (outputs go to a temp dir):

```sh
cd "$KIT/examples/side-menu"
o=$(mktemp -d)
lua5.4 models.lua > "$o/cases.json"                    # the client Lua, run on fake-nui, writes one case per state
"$KIT"/bin/rml-check ui/menu.rml "$o/cases.json"
"$KIT"/bin/rml-preview ui/menu.rml "$o/cases.json" --font kitraj=fonts/Rajdhani-Regular.ttf,fonts/Rajdhani-SemiBold.ttf --out "$o/preview"
```

Where Lua 5.4 is called `lua` (Fedora) or `lua54` (Windows), use that; `lua -v` must say 5.4 (Arch's and Homebrew's
`lua` is 5.5: their 5.4 is `lua54`, `lua@5.4`). On Windows, Git Bash runs these commands as written; from PowerShell
or cmd start each tool through Python: `py <kit>\bin\rml-check ui\menu.rml cases.json`, `py <kit>\scripts\build.py`.

## 1. Pick the loop

- **A, a new native screen:** write `ui/<screen>.rml` + `ui/<screen>.rcss`, cases, check, preview (section 2).
- **B, a WebUI page to port:** convert it with `html2rml` first, never by hand; then the same check and preview, plus
  shots of the page to compare. Steps in [references/porting.md](references/porting.md).
- **C, a restyle or a bug in an existing screen:** change the RCSS, then search the client Lua for numbers laid out
  against the old sizes (bar widths, column positions in dp). They break silently when the panel changes size.
  Then check and preview every state.

## 2. The loop

1. **Start the sheet with the rules RmlUi lacks:** `div { display: block; box-sizing: border-box; }`. Without the
   first, widths and heights on a div do nothing.
2. **Describe the states as cases:** a JSON array of `{ name, model, clicks?, events? }`, one entry per state the
   player can see (empty list, one selected, a dialog open, an error, the longest name you ship). Generate them
   from the real client Lua with fake-nui (`$KIT/examples/side-menu/models.lua` is the pattern), so the models are
   what the client builds. By hand only for a quick look. Format: `$KIT/docs/cases.md`.
3. **`rml-check <doc> <cases>`:** exit 0 is clean; exit 1 lists every problem; exit 2 is a usage or input problem.
   Fix everything it prints. How to read each line: [references/output.md](references/output.md).
4. **`rml-preview <doc> <cases> --font <family>=<ttf>[,<ttf>...] --out <dir>`:** one PNG per state plus
   `sheet.png`. Pass every weight the sheet uses (comma-separated files under one family; RmlUi keeps family names
   lower case). `--bg <game screenshot>` paints over the game, and `--compare <dir of PNGs>` puts a mockup next to
   each state.
5. **Look at every state PNG,** one by one (`sheet.png` is an overview, not a check). Look for overlapping text,
   cut names, an underline under the wrong tab, an empty column, squeezed rows, things off the panel. A clean
   `rml-check` says the document loads and the buttons fire. It says nothing about whether it looks right (in the kit's own example,
   all three tab underlines sat under the middle tab with the check green).
6. Fix and repeat from 3.

## 3. Done means

- `rml-check` prints `rml-check: ok` for every case you wrote, with no `--allow` you can't justify in one line.
- You opened every state PNG, and it looks as intended.
- `rml-preview` listed no `MISSING image` or `NO FONT FACE` you didn't expect (`--strict` makes them fail).
- You hand a human the list of what only the game shows for this screen: Open77's own filters (glow, chromatic,
  scanlines), `fx()` decorators, `<shape>` paint, motion channels, `<scene3d>`, hover states, the game's
  anti-aliasing, and custom properties (`var()`) if you kept any. In the game: `nui.hotreload on`.

## 4. The traps that cost the most

All of them, with the reasons: `$KIT/docs/rmlui-traps.md`. These come up on almost every screen:

- **No default stylesheet:** every element is inline until the sheet says otherwise (see step 1).
- **`content-box` by default:** a padded fixed-width row grows by its padding.
- **An absolute child needs a positioned parent:** otherwise it lands under the nearest positioned ancestor.
- **No `calc()`, grid, `background-size` or `-webkit-` prefixes.** Write the numbers. An underline, a partial
  bar or a divider is its own element.
- **Text can't be measured in RCSS.** For long names, measure in the client (sum the font's advances) and switch
  a class (`small`, `two-lines`). Preview the longest name you ship.
- **`rgba()` alpha is 0-255,** not 0-1. `rgba(255, 97, 89, .5)` is invisible; write `#FF615980`.
- **`.gone { display: none }` loses to `#id { display: flex }`:** write `#root .gone` and put it last.
- **Every name the markup binds must be in the FIRST model:** fields can't be added later.
- **A bracket mistake in text** (`{{a} }}`, a stray `}}`) stops the parser: the rest of the document never loads.
- **A scrolling box needs scrollbar styles** (`scrollbarvertical { width: 8dp; }` and its `sliderbar`): without
  them an overflowing list squeezes its rows to one word per line, and rml-check stays green.
- **Markup arrays are 0-based, Lua paths 1-based** (`ui:set("m", "rows[1].name", ...)` is `rows[0]` in markup).
- **The `x`/`y` motion channels move in screen pixels, not dp.** Place things with `ui:style(sel, { left =
  "<n>dp", top = "<n>dp" })`; keep the channels for flourishes.
- **The instruction budget:** never deep-compare model tables to find changes; key fields instead.
  fake-nui counts instructions and fails past Open77's budget.

## 5. Don't

- **Edit html2rml's `--out` folder by hand.** It is overwritten on the next run. Convert into its own folder,
  then copy what you keep into `ui/`.
- **`--allow` a warning away** because it's noisy. Allow only a warning the case causes on purpose (a missing image
  you test), and say so next to it.
- **Trust the preview for Open77's own effects.** It lists them as `NOT PAINTED`. Check them in the game.
- **Ship text in a glyph the font lacks.** Rajdhani has no arrow. Check the strings against the font first.
- **Load a font under a common family name.** The client ships fonts of its own (Rajdhani among them): load yours
  with `Open77.ui.loadFont(path, family)` under a family name of your own, and list every rml/rcss/png/ttf in the
  manifest's `files`.

## 6. The Open77 side

The manifest, `Open77.ui.create`, `loadFont`, layers, input and the dev console are Open77's API, documented by
Open77 (https://open2077.net/llms-full.txt, the NativeUI section), not by the kit. The parts every screen needs:

- Every file the document opens goes in the manifest's `files` (globs work): `files { "ui/*.rml", "ui/*.rcss",
  "ui/img/*", "fonts/*.ttf" }`, next to `client_script "client/<screen>.lua"`. An undeclared file fails with
  `undeclared_file:<path>`.
- In a document in a sub-folder, image paths are written from the resource root (`/ui/img/logo.png`).
- How the server receives a choice is the resource's own business (an event, an export): the kit doesn't model it.
  Say in the hand-off which call you assumed.

## 7. One markup for both surfaces (lrbind)

`lrbind.js` runs RmlUi's data bindings in a WebUI page, and `lrbind.lua` gives client Lua one API for both surfaces.
So the same markup serves a WebUI page and its NativeUI twin, and its behaviour is measured against real RmlUi case by
case. A resource keeps its own copies: `"$KIT"/bin/lrbind-sync add <resource>` writes them,
`lrbind-sync refresh <folder>` updates old copies after a kit update, and `lrbind-sync check <folder>` (exit 1 when a
copy is not current) belongs in the project's tests. Details: `$KIT/lrbind/README.md`.

## Reference

- [references/output.md](references/output.md): every line the tools print, and what to do about it.
- [references/porting.md](references/porting.md): a WebUI page to NativeUI, step by step.
- `$KIT/docs/cases.md`: the case format, and what fake-nui runs and only records.
- `$KIT/docs/rmlui-traps.md`: the traps, in full.
- `$KIT/docs/converter.md`: what html2rml maps, what it reports, and the RmlUi facts behind each mapping.
