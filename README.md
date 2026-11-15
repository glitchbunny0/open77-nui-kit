# open77-nui-kit

Offline tools for [Open77](https://open2077.net) NativeUI screens: RmlUi documents (RML + RCSS) driven from client
Lua. See what a screen really does before you start the game.

- **`rml-check`** loads your document in real RmlUi for every state you describe and fails on anything RmlUi
  complains about: a binding to a model field that doesn't exist, an unknown property or value (Open77's own
  properties, filters and `fx()` included: the host registers them, so their values are checked too), broken XML, a
  `data-for` over a non-array, a missing image, an event the client does not declare, a button whose click (a real
  press at its centre) calls nothing, the wrong event or the wrong arguments.
- **`rml-preview`** lays the document out in real RmlUi with your real fonts and paints a PNG per state (boxes,
  borders and radii, gradients of every RmlUi kind, image decorators with their fit and alignment, masks, vector
  paths, text) over a backdrop. Real sizes, wrapping, clipping, overflow. What it can't paint it lists per state
  (`NOT PAINTED ...`, missing images and font faces); `--strict` turns those into a failure.
- **`lrbind`** (the kit's own name for it) runs RmlUi's data bindings inside a WebUI page, so one markup serves a
  WebUI page and its NativeUI twin; its behaviour is measured against real RmlUi case by case (`bin/lrbind-parity`).
- **`fake-nui`** is a fake `Open77.ui` for plain Lua 5.4: it implements the documented document API (models with
  `set`/`push`/`removeAt` paths, listeners, focus, the scheduler's next-pass `CreateThread`, the instruction budget)
  or records the call where it cannot run it (DOM edits, motion, scenes). Run your screen's client Lua offline, click
  through it, and write the states out as cases for the two tools above. What it does and does not do:
  [docs/cases.md](docs/cases.md).
- **`html2rml`** converts a WebUI page (HTML + CSS, lrbind bindings kept) into an RmlUi document and sheet, and reports
  everything it could not map with file:line and what to do instead. **`html-shot`** shoots the page per state so
  `rml-preview --compare` shows the browser and NativeUI side by side.

![The example side menu, six states, painted by rml-preview](docs/img/side-menu-sheet.png)

The kit shows layout and bindings. It does **not** show what Open77 adds on top of RmlUi 6.3 (glow, chromatic and
scanline filters, `fx()` decorators, `<shape>` paint, motion channels, `<scene3d>`), hover states, or the game's
anti-aliasing. Check those in the game with `nui.hotreload on`.

## Quick start

Needs `git`, `g++` (C++17), `python3`, Lua 5.4 and, for lrbind's tests, Node 20.19+ (22 in CI). Optional: Pillow for
previews, a Chromium for `html-shot`.

| | Debian / Ubuntu | Fedora | Arch / Homebrew |
|---|---|---|---|
| Lua 5.4 (command `lua5.4`) | `apt install lua5.4` | `dnf install lua` (command `lua`) | `lua` |
| Pillow | `apt install python3-pil` | `dnf install python3-pillow` | `pip install Pillow` |

Chromium for `html-shot`: `npx playwright install chromium-headless-shell` (any OS; found under Playwright's cache,
`PLAYWRIGHT_BROWSERS_PATH` and `XDG_CACHE_HOME` honoured), or `NUIKIT_CHROME=/path/to/chrome`.

The commands below say `lua5.4`; where the binary is called `lua`, use that (`scripts/test.sh` finds either, or `LUA=...`).

```sh
git clone https://github.com/glitchbunny0/open77-nui-kit && cd open77-nui-kit
scripts/build.sh                            # fetches RmlUi 6.3 and builds the host once (about a minute)
cd examples/side-menu
lua5.4 models.lua > cases.json              # the client Lua, run on fake-nui, writes one case per state
../../bin/rml-check ui/menu.rml cases.json
../../bin/rml-preview ui/menu.rml cases.json --font kitraj=fonts/Rajdhani-Regular.ttf,fonts/Rajdhani-SemiBold.ttf --out out
```

`out/` now holds `browse.png`, `confirm.png`, ... and `sheet.png`. The example's README walks through what each file
does and the bug the preview caught while it was written.

## The loop for your own screen

1. Write `ui/<screen>.rml` + `.rcss`. Start the sheet with `div { display: block; box-sizing: border-box; }`
   (RmlUi has no default stylesheet; see [docs/rmlui-traps.md](docs/rmlui-traps.md)).
2. Describe its states as cases: a JSON array of `{ name, model, clicks?, events? }`
   ([docs/cases.md](docs/cases.md)). Hand-write them, or generate them from your client Lua with fake-nui so the
   models are exactly what the client builds.
3. `rml-check ui/<screen>.rml cases.json` in your test run. It exits 1 on any problem.
4. `rml-preview ui/<screen>.rml cases.json --font <family>=<ttf>... --bg <a game screenshot>` while you design.
   `--compare <folder of mockup shots>` puts your mockup next to each state.
5. In the game: `nui.hotreload on`, then look at the effects the kit can't show.

## Starting from a WebUI page

Run from your resource's folder (the one with `web/`); `<kit>` is where you cloned the kit. The example
`examples/side-menu` is such a folder, so this block runs there as written. `--out` takes a folder of its own: html2rml
overwrites what it finds there, so never point it at a hand-written `ui/`.

```sh
cd examples/side-menu
../../bin/html2rml web/index.html --out out/twin --name menu     # out/twin/menu.rml + .rcss + menu.report.md
../../bin/rml-check out/twin/menu.rml cases.json
../../bin/html-shot web/index.html cases.json --out shots         # optional: needs a Chromium; fails when the bindings did not run
../../bin/rml-preview out/twin/menu.rml cases.json --font kitraj=fonts/Rajdhani-Regular.ttf,fonts/Rajdhani-SemiBold.ttf --out out/twin-preview --compare shots
```

(From your own resource: `<kit>/bin/html2rml web/index.html --out out/twin --name menu`, and so on. Pass every font weight
the sheet uses to `--font`, comma-separated, or the missing weights are painted with the first file.)

The report lists the scripts to port to the client Lua (with the ids, classes and styles each one touches), the
`Open77.ui.loadFont` calls the client needs, and every rule, value and element RmlUi has no form for.
[docs/converter.md](docs/converter.md) lists what converts, what is reported, and the RmlUi facts behind each mapping
(measured in real RmlUi by `converter/tests/facts.py`).

## What's in the repo

| Path | What |
|---|---|
| `bin/rml-check`, `bin/rml-preview` | the two CLIs (Python 3; preview needs Pillow) |
| `bin/lrbind-parity`, `bin/lrbind-sync` | lrbind's parity runner and the copy helper for resources |
| `bin/html2rml`, `converter/` | the WebUI -> NativeUI converter (Python stdlib), its fixtures and RmlUi fact tests |
| `bin/html-shot` | screenshots of a WebUI page per case (optional Chromium) |
| `host/` | `rmlhost`: real RmlUi with a JSON-fed dynamic data model; modes `check`, `layout`, `parity` |
| `scripts/build.sh` | builds RmlUi (pinned tag, no CMake, no FreeType) and the host into a cache dir |
| `lrbind/` | `lrbind.js`, `lrbind.lua`, their tests and the parity suite ([lrbind/README.md](lrbind/README.md)) |
| `fake-nui/fake_nui.lua` | fake `Open77.ui` (documented document API, recorded stubs for DOM/motion calls), a scheduler for `CreateThread`/`Wait`/`SetTimeout`, an instruction counter with Open77's budget, JSON out |
| `examples/side-menu/` | a complete small screen: document, sheet, client Lua, offline driver, fonts, and its WebUI twin |
| `docs/` | the case format and what fake-nui fakes, the RmlUi traps every native document meets, the converter |
| `tests/`, `scripts/test.sh` | the suites: one `tests/<area>.sh` per area, each check proven by a mutant ([tests/README.md](tests/README.md)) |

The RmlUi checkout and build live in `${XDG_CACHE_HOME:-~/.cache}/open77-nui-kit/` (override with
`NUIKIT_RMLUI_DIR`); nothing is vendored. `scripts/test.sh` runs the kit's own tests; CI sets
`NUIKIT_REQUIRE_CHROME=1` and `NUIKIT_REQUIRE_PILLOW=1`, so there a missing Chromium or Pillow fails the run instead of
skipping its steps.

## License

MIT ([LICENSE](LICENSE)). lrbind.js ports parts of RmlUi (MIT); the notice is in [NOTICE](NOTICE). The example's
font is Rajdhani under the SIL OFL. Not affiliated with the Open2077 project. The example's item names come from
Cyberpunk 2077, a trademark of CD PROJEKT S.A.; the kit is not affiliated with CD PROJEKT.
