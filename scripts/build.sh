#!/usr/bin/env bash
# Build the kit's RmlUi host (host/rmlhost.cpp) against a pinned RmlUi release. Needs git and g++ (C++17); no CMake,
# no FreeType: the host brings its own null renderer and font engines.
#   scripts/build.sh [--host DIR] [--out FILE]
# The RmlUi checkout and its objects live in a cache dir, never in the repo:
#   NUIKIT_RMLUI_DIR   default ${XDG_CACHE_HOME:-~/.cache}/open77-nui-kit/rmlui-<tag>
#   NUIKIT_RMLUI_TAG   default 6.3; a git checkout in NUIKIT_RMLUI_DIR at another tag is an error, never used silently
#   NUIKIT_RMLUI_URL   where the checkout is cloned from (default: RmlUi on GitHub)
# The binary is <dir>/build/rmlhost-<hash>, the hash taken over the host sources, the tag and the compile flags: kit
# checkouts sharing one cache dir never run each other's host, and a changed host/ always gets its own build.
# --host builds another host source dir (the suite's mutants); --out writes the binary to FILE instead of the cache.
# The clone and the core build hold an flock on <dir>.lock, so builds started together wait for each other (without
# the flock command they run unlocked). A clone goes to <dir>.tmp.<pid> and is renamed once complete, so a killed
# clone never leaves a half checkout in <dir>.
# Prints the path of the built binary on its last line.
set -euo pipefail
tag="${NUIKIT_RMLUI_TAG:-6.3}"     # Open77's NativeUI is RmlUi 6.3; move this pin when Open77 moves
url="${NUIKIT_RMLUI_URL:-https://github.com/mikke89/RmlUi.git}"
kit="$(cd "$(dirname "$0")/.." && pwd)"
dir="${NUIKIT_RMLUI_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/open77-nui-kit/rmlui-$tag}"
src="$kit/host"
out=""
while [ $# -gt 0 ]; do
    case "$1" in
    --host) src="$(cd "$2" && pwd)"; shift 2 ;;
    --out) out="$2"; shift 2 ;;
    *) echo "usage: scripts/build.sh [--host DIR] [--out FILE]" >&2; exit 2 ;;
    esac
done
flags=(-std=c++17 -O1 -w -DRMLUI_STATIC_LIB)

mkdir -p "$(dirname "$dir")"
if command -v flock >/dev/null 2>&1; then
    exec 9>"$dir.lock"
    flock 9
fi
if [ ! -d "$dir/Source/Core" ]; then
    if [ -e "$dir" ]; then
        echo "build.sh: $dir exists but holds no RmlUi checkout (no Source/Core): remove it or set NUIKIT_RMLUI_DIR" >&2
        exit 2
    fi
    rm -rf "$dir".tmp.*          # left by a killed clone (we hold the lock: nobody else is cloning now)
    git -c advice.detachedHead=false clone -q --depth 1 --branch "$tag" "$url" "$dir.tmp.$$"
    mv "$dir.tmp.$$" "$dir"
fi
if [ -e "$dir/.git" ]; then
    have="$(git -C "$dir" describe --tags --exact-match 2>/dev/null || echo 'no tag')"
    if [ "$have" != "$tag" ]; then
        echo "build.sh: $dir is RmlUi at '$have', not $tag (NUIKIT_RMLUI_TAG): set NUIKIT_RMLUI_DIR to another dir" >&2
        exit 2
    fi
fi
mkdir -p "$dir/build/obj"
if [ ! -f "$dir/build/.core-built" ]; then
    echo "building RmlUi $tag core (once, about a minute)" >&2
    (cd "$dir" && find Source/Core -name '*.cpp' -not -path '*FontEngineDefault*' | sort \
        | xargs -P "$(nproc 2>/dev/null || echo 4)" -I{} sh -c 'g++ -std=c++17 -O1 -w -DRMLUI_STATIC_LIB -IInclude -c "$1" -o "build/obj/$(echo "$1" | tr / _).o"' _ {})
    touch "$dir/build/.core-built"
fi
exec 9>&-    # the host needs no lock: it is linked to a private name, then renamed into place

sha() { if command -v sha256sum >/dev/null 2>&1; then sha256sum; else shasum -a 256; fi; }
hash="$( { printf '%s\n' "$tag" "${flags[*]}"; for f in "$src"/*; do printf '== %s\n' "${f##*/}"; cat "$f"; done; } \
    | sha | cut -c1-16)"
bin="${out:-$dir/build/rmlhost-$hash}"
if [ -n "$out" ] || [ ! -x "$bin" ]; then
    echo "building rmlhost" >&2
    g++ "${flags[@]}" -I"$dir/Include" "$src/rmlhost.cpp" "$dir"/build/obj/*.o -o "$bin.new.$$"
    mv "$bin.new.$$" "$bin"
fi
echo "$bin"
