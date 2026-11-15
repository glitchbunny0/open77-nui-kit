# Porting a WebUI page to NativeUI

The page keeps working as it is; the native document is generated from it, checked against the same cases, and
compared with it state by state. Run from the resource's folder (the one with `web/`); `$KIT` is the kit's folder.

## 1. Convert into a folder of its own

```sh
"$KIT"/bin/html2rml web/index.html --out out/twin --name <screen> --root .
```

`--root .` writes image and font paths from the resource root (`/web/assets/x.png`), as Open77 resolves them.
html2rml overwrites `--out` on every run: never point it at `ui/`. When the result is right, copy it to `ui/` and
treat `ui/` as yours from then on (or keep converting and never edit `ui/`; pick one per screen and say which in the
resource's README).

`--vars fold` (the default) folds CSS custom properties to numbers from the page's static cascade. `--vars native`
keeps them for RmlUi to resolve at run time; RmlUi 6.3 supports them, whether Open77's build keeps that on is
unproven in the game, so stay on `fold` unless the project has checked it.

## 2. Work the report

`out/twin/<screen>.report.md` lists everything that did not map one to one, with `file:line` and what to do. The
usual work, in order:

1. **Scripts.** Each `<script>` is listed with the ids, classes, styles and attributes it touches. That logic moves
   to the client Lua: values become model fields (computed in Lua, bound with `{{x}}`, `data-class-*`, `data-if`,
   `data-for`), clicks become `data-event-click="name(args)"` handled by the client's `events`. A runtime CSS
   variable set from JS (a mode colour) becomes a class or a `ui:stylesheet` layer.
2. **Fonts.** Make the listed `Open77.ui.loadFont(path, family)` calls before creating the document, under a family
   name of your own, and list the TTFs in the manifest's `files` (WOFF has to be converted to TTF).
3. **Selectors, declarations, markup.** Give elements classes instead of pseudo-elements and `:has()`, write
   numbers instead of `calc()` mixes, replace grid with flex rows and widths. `$KIT/docs/converter.md` has the
   full table and the reason for each.

Re-run html2rml after changing the page; the report shrinks. `--strict` (exit 1 on any item) belongs in the
project's tests once the report is empty or every remaining item is accepted.

## 3. Same cases, both surfaces

The cases come from the client Lua (fake-nui), as for any native screen (`$KIT/docs/cases.md`). Then:

```sh
"$KIT"/bin/rml-check out/twin/<screen>.rml cases.json
"$KIT"/bin/html-shot web/index.html cases.json --out out/shots          # the page per state, in Chromium
"$KIT"/bin/rml-preview out/twin/<screen>.rml cases.json --font <family>=<ttf>,... --out out/preview --compare out/shots
```

Open `out/preview/compare.png`: each state, the page next to the native document. They should match except for what
the report listed and what the preview can't paint. html-shot fails a state whose bindings didn't run, so a blank
shot is never silently compared.

## 4. Keep both surfaces, or not

- **The page stays the fallback:** make it use lrbind (`<script src="lrbind.js">`, the markup's RmlUi bindings
  read in the browser), and the client drives both through one API (`LrBind.create` picks the surface). The
  resource keeps its own copies (`"$KIT"/bin/lrbind-sync add <resource>`). A look change then edits the page and
  re-converts, or edits both sheets by hand: decide which, or they drift.
- **The page goes away:** keep `ui/` only, and delete `web/` once the native screen has been seen in the game.

## 5. What still needs the game

The preview lists what it didn't paint. Beyond that: hover states, motion channels, Open77's filters and `fx()`, the
game's anti-aliasing, custom properties if you used `--vars native`, and anything the report said to check in the
game. Hand that list to whoever runs the game (`nui.hotreload on` reloads the document live).
