#!/usr/bin/env bash
# scripts/build.sh checks, run against a tiny fake RmlUi (one core file, tag 6.3, cloned over file://) so they take
# seconds and never touch the real cache. Usage: build_checks.sh BUILD_SH WORKDIR [CHECK-PREFIX]
# Prints "ok <check>" or "FAIL <check>: why" per check; exits 1 when any failed.
set -uo pipefail
build="$1"; w="$2"; only="${3:-}"
mkdir -p "$w"; w="$(cd "$w" && pwd)"
fail=0
ok() { echo "ok $1"; }
bad() { echo "FAIL $1: $2"; fail=1; }
want() { [ -z "$only" ] || [ "${1#"$only"}" != "$1" ]; }

repo="$w/fake-rmlui"
if [ ! -d "$repo/.git" ]; then
    mkdir -p "$repo/Source/Core" "$repo/Include"
    echo 'int fake_core() { return 7; }' > "$repo/Source/Core/Core.cpp"
    git -C "$repo" init -q
    git -C "$repo" add -A
    git -C "$repo" -c user.name=kit -c user.email=kit@example.invalid commit -q -m fake
    git -C "$repo" tag 6.3
fi
mkhost() {   # mkhost DIR WORD: a host source dir whose binary prints WORD
    mkdir -p "$1"
    printf '#include <cstdio>\nint fake_core();\nint main() { std::puts("%s"); return fake_core() == 7 ? 0 : 1; }\n' "$2" > "$1/rmlhost.cpp"
}
mkhost "$w/hostA" A
mkhost "$w/hostB" B
run() { NUIKIT_RMLUI_URL="file://$repo" NUIKIT_RMLUI_TAG=6.3 NUIKIT_RMLUI_DIR="$1" bash "$build" "${@:2}"; }

c="build: two host sources sharing one cache dir get their own binaries"
if want "$c"; then
    d="$w/c1/rmlui"
    a=$(run "$d" --host "$w/hostA" 2>/dev/null | tail -1)
    b=$(run "$d" --host "$w/hostB" 2>/dev/null | tail -1)
    a2=$(run "$d" --host "$w/hostA" 2>/dev/null | tail -1)
    if [ -z "$a" ] || [ "$a" = "$b" ] || [ "$a" != "$a2" ]; then bad "$c" "paths A=$a B=$b A again=$a2"
    elif [ "$("$a")" != A ] || [ "$("$b")" != B ]; then bad "$c" "A runs '$("$a")', B runs '$("$b")'"
    else ok "$c"; fi
fi

c="build: a build waits while another holds the cache lock"
if want "$c" && command -v flock >/dev/null 2>&1; then
    d="$w/c2/rmlui"
    run "$d" --host "$w/hostA" >/dev/null 2>&1   # clone + core first, so the timed run only has the lock to wait for
    flock "$d.lock" sleep 4 &
    holder=$!
    sleep 0.5
    timeout 2 bash -c "$(declare -f run); repo='$repo'; build='$build'; run '$d' --host '$w/hostB'" >/dev/null 2>&1
    rc=$?
    wait "$holder"
    after=$(run "$d" --host "$w/hostB" 2>/dev/null | tail -1)
    if [ "$rc" != 124 ]; then bad "$c" "finished (rc $rc) while the lock was held"
    elif [ -z "$after" ] || [ "$("$after")" != B ]; then bad "$c" "no build after the lock was released"
    else ok "$c"; fi
fi

c="build: a checkout at another tag is refused"
if want "$c"; then
    d="$w/c3/rmlui"
    run "$d" --host "$w/hostA" >/dev/null 2>&1
    git -C "$d" tag 5.1 2>/dev/null; git -C "$d" tag -d 6.3 >/dev/null 2>&1
    msg=$(run "$d" --host "$w/hostA" 2>&1); rc=$?
    if [ "$rc" = 0 ]; then bad "$c" "a 5.1 checkout was used for tag 6.3"
    elif ! echo "$msg" | grep -q "not 6.3"; then bad "$c" "no message naming the tag: $msg"
    else ok "$c"; fi
fi

c="build: a killed clone leaves no half checkout behind"
if want "$c"; then
    d="$w/c4/rmlui"
    mkdir -p "$w/fakegit"
    # a git that dies after creating the destination's .git, as a clone killed half way does
    printf '#!/bin/sh\nfor a; do dest="$a"; done\nmkdir -p "$dest/.git"\nexit 137\n' > "$w/fakegit/git"
    chmod +x "$w/fakegit/git"
    PATH="$w/fakegit:$PATH" run "$d" --host "$w/hostA" >/dev/null 2>&1
    rc1=$?
    p=$(run "$d" --host "$w/hostA" 2>&1 | tail -1)
    if [ "$rc1" = 0 ]; then bad "$c" "the killed clone counted as a build"
    elif [ ! -x "$p" ] || [ "$("$p")" != A ]; then bad "$c" "the next build failed: $p"
    else ok "$c"; fi
fi
exit $fail
