# AGENTS.md

Instructions for agents changing open77-nui-kit itself. Using the kit to build a screen is a different job: load the
skill in [skills/open77-nativeui/](skills/open77-nativeui/SKILL.md) instead.

## What this repo is

Offline tools for Open77 NativeUI screens (RmlUi 6.3 documents): a check, a preview painter, a WebUI-to-RML
converter, a fake `Open77.ui` for client Lua, and lrbind (RmlUi data bindings for WebUI pages). Everything that
says how RmlUi behaves runs the real RmlUi, built from source by `scripts/build.sh`.

| Path | What |
|---|---|
| `bin/` | the CLIs (Python 3, stdlib; `rml-preview` needs Pillow) |
| `host/`, `scripts/build.sh` | `rmlhost`: real RmlUi with a JSON-fed data model, modes `check`, `layout`, `parity`; RmlUi at a pinned tag, no CMake, no FreeType; the binary is named after a hash of its sources |
| `lrbind/` | `lrbind.js`, `lrbind.lua`, the parity suite against real RmlUi (`lrbind/tests/parity/golden.json`) |
| `fake-nui/` | the fake `Open77.ui`, its scheduler and Open77's instruction budget |
| `converter/` | html2rml; `converter/tests/facts.py` measures every RmlUi fact a mapping rests on |
| `examples/side-menu/` | a complete screen and its WebUI twin; the suites use it |
| `docs/` | the reference: cases, RmlUi traps, the converter |
| `skills/open77-nativeui/` | the agent skill for kit users (`.agents/skills`, `.claude/skills` link to `skills/`) |
| `tests/`, `scripts/test.sh` | one suite per area, every check proven by a mutant |

## The gate

- `scripts/test.sh` must end with `ALL OK` before any commit. Check the last line (`tail -1 | grep -qx 'ALL OK'`):
  never chain a commit after a test run that wasn't checked. It takes a few minutes; one suite alone:
  `NUIKIT=$PWD NUIKIT_TMP=$(mktemp -d) bash tests/<area>.sh`.
- Pillow and Chromium are optional: without them the suite skips their steps. Before a release, run it with
  `NUIKIT_REQUIRE_PILLOW=1 NUIKIT_REQUIRE_CHROME=1` as CI does.
- `NUIKIT_RMLUI_DIR` names the RmlUi build dir. Give parallel work separate dirs; a first build takes about a minute.

## Rules

- **Every new check gets a mutant:** a copy of the tool with ONE planted bug, listed in its suite, that turns
  exactly that check red ([tests/README.md](tests/README.md)). A check no mutant can turn red proves nothing. When
  you change code a mutant plants its bug in, the suite tells you (`the site is gone`): move the mutant, don't
  delete it.
- **Measure RmlUi, don't assume it.** A converter mapping rests on a fact in `converter/tests/facts.py`, run in
  real RmlUi. lrbind behaviour is a parity case compared with real RmlUi. "CSS does X, so RmlUi probably does too"
  has been wrong often enough.
- **Host output changes ripple.** After changing `host/`: `bin/lrbind-parity --regen` and read the golden diff
  case by case; `bash tests/rml-preview.sh --regen` for the reference PNGs, and OPEN every changed image before
  committing it. A regenerated reference nobody looked at hides the bug it was meant to catch.
- **Docs are tested.** `tests/docs.sh` runs the README's and the skill's shell blocks in a copy of the kit, checks
  the numbers the docs quote, the skill's metadata, every link, and that `references/output.md` names every line
  the tools print. Change a tool's output, and update the docs in the same commit.
- **No consumer specifics.** No project, server, person or host names, home paths or account names in any file.
  The docs suite greps the agent docs for home paths, tailnet addresses and accounts; set `NUIKIT_PRIVATE_RE` to a
  regex of your own project's names to grep for those too (never write them into the kit).
  `lrbind.js` / `lrbind.lua` are copied into resources that ship to players, so their header names no account
  either (the lrbind suite checks it).
- **Releases:** tag only after CI is green on the commit. Never move or delete a tag: consumers pin tags and refuse
  a moved one. A fix after a tag is a new tag.
- Atomic commits, one concern each, with the subject saying what changed for a user of the kit.
