# AGENTS.md

Instructions for agents changing open77-nui-kit itself. Using the kit to build a screen is a different job: load the
skill in [skills/open77-nativeui/](skills/open77-nativeui/SKILL.md) instead.

## What this repo is

Offline tools for Open77 NativeUI screens (RmlUi 6.3 documents): a check, a preview painter, a WebUI-to-RML
converter, a fake `Open77.ui` for client Lua, and lrbind (RmlUi data bindings for WebUI pages). Everything that
says how RmlUi behaves runs the real RmlUi, built from source by `scripts/build.py`. Linux, macOS and Windows alike.

| Path | What |
|---|---|
| `bin/` | the CLIs (Python 3, stdlib; `rml-preview` needs Pillow) |
| `host/`, `scripts/build.py` | `rmlhost`: real RmlUi with a JSON-fed data model, modes `check`, `layout`, `parity`; RmlUi at a pinned tag, no CMake, no FreeType; g++, clang++ or MSVC (vswhere); the binary is named after a hash of its sources and the compiler (`build.sh` runs `build.py`) |
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
- CI runs the gate on Linux, macOS and Windows (MSVC and MinGW-w64). A change that is green on one OS only is not done.

## Every OS

- **Tools** (`bin/`, `scripts/build.py`, `converter/`): Python standard library, no bash, no shell-outs. No POSIX-only
  call without its Windows path (`os.killpg`, `signal.SIGALRM`, `fcntl`: see `kill_tree` in `bin/html-shot`, the lock
  in `build.py`). Output UTF-8 with `\n` (each `main` reconfigures stdout and stderr); write text files with
  `encoding='utf-8', newline='\n'`; decode a child's output as UTF-8, never with `text=True`. Run a tool on PATH by
  `shutil.which` (Windows starts `.cmd` files only by their full path). The host prints the same bytes everywhere.
  A child that starts children of its own is killed as a tree: a session on POSIX, a job object on Windows
  (`bin/html-shot`). Text is measured and drawn with Pillow's BASIC layout: Raqm depends on whether FriBiDi happens to
  be installed, and draws differently.
- **Suites** (`tests/*.sh`): bash 3.2 (macOS): no `wait -n`, `${a,,}`, `mapfile`; an array that can be empty is
  `${a[@]+"${a[@]}"}` under `set -u`. No GNU-only flags: `sed -i`, sed's `0,/re/`, `sort -V`, `timeout`, `realpath -m`.
  A scripted fake run by a Python tool goes through `shim` from `tests/lib/os.sh` (a `.cmd` on Windows), and a path a
  tool prints is compared through `upath`. Lua on Windows writes `\r\n`: compare its output with the `\r` removed.
  Git Bash rewrites an argument or environment value that looks like a path: mutants are planted with `plant`
  (the text goes through files), folders go to Python as arguments, never inside a file. No heredoc inside `$(...)`
  (bash 3.2 misreads one with an unbalanced quote or parenthesis): put it in a function. Python in a suite writes
  files with `encoding='utf-8'`. A check that cannot fire on one OS says so on a `skip` line, never silently.

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
