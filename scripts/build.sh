#!/usr/bin/env bash
# Build the kit's RmlUi host (host/rmlhost.cpp) against a pinned RmlUi release. Needs git and g++ (C++17); no CMake,
# no FreeType: the host brings its own null renderer and font engines.
# The RmlUi checkout and its objects live in a cache dir, never in the repo:
#   NUIKIT_RMLUI_DIR   default ${XDG_CACHE_HOME:-~/.cache}/open77-nui-kit/rmlui-<tag>
# Prints the path of the built binary on its last line. Rebuilds the host only when a host/ file is newer.
set -euo pipefail
tag="${NUIKIT_RMLUI_TAG:-6.3}"     # Open77's NativeUI is RmlUi 6.3; move this pin when Open77 moves
kit="$(cd "$(dirname "$0")/.." && pwd)"
dir="${NUIKIT_RMLUI_DIR:-${XDG_CACHE_HOME:-$HOME/.cache}/open77-nui-kit/rmlui-$tag}"
if [ ! -d "$dir/Source/Core" ]; then
    mkdir -p "$(dirname "$dir")"
    git clone -q --depth 1 --branch "$tag" https://github.com/mikke89/RmlUi.git "$dir"
fi
mkdir -p "$dir/build/obj"
if [ ! -f "$dir/build/.core-built" ]; then
    echo "building RmlUi $tag core (once, about a minute)" >&2
    (cd "$dir" && find Source/Core -name '*.cpp' -not -path '*FontEngineDefault*' | sort \
        | xargs -P "$(nproc 2>/dev/null || echo 4)" -I{} sh -c 'g++ -std=c++17 -O1 -w -DRMLUI_STATIC_LIB -IInclude -c "$1" -o "build/obj/$(echo "$1" | tr / _).o"' _ {})
    touch "$dir/build/.core-built"
fi
bin="$dir/build/rmlhost"
if [ ! -x "$bin" ] || [ -n "$(find "$kit/host" -newer "$bin" -type f | head -1)" ]; then
    echo "building rmlhost" >&2
    g++ -std=c++17 -O1 -w -DRMLUI_STATIC_LIB -I"$dir/Include" "$kit/host/rmlhost.cpp" "$dir"/build/obj/*.o -o "$bin.new"
    mv "$bin.new" "$bin"
fi
echo "$bin"
