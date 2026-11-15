#!/usr/bin/env bash
# rmlhost's own tests (host/ and scripts/build.sh). Suite contract: tests/README.md.
#   1. tests/host/checks.py on the real host: check, layout and parity mode against the probe documents in tests/host/
#   2. tests/host/build_checks.sh on the real scripts/build.sh (a fake RmlUi, so it takes seconds)
#   3. mutants: broken copies of a host/ file or of build.sh, one bug each, built into $NUIKIT_TMP; each must turn the
#      check it names red on its own
set -uo pipefail
kit="${NUIKIT:?run through scripts/test.sh}"; tmp="${NUIKIT_TMP:?}"
cd "$kit"
py="${PYTHON:-python3}"
fail=0
host=$(bash scripts/build.sh 2>/dev/null | tail -1)
[ -x "$host" ] || { echo "FAIL: scripts/build.sh did not build the host"; exit 1; }

summary() {   # summary LABEL OUTPUT RC
    [ -z "$2" ] || echo "$2" | grep -v '^ok ' || true
    echo "$1: $(echo "$2" | grep -c '^ok ' || true) checks ok"
    [ "$3" = 0 ] || { echo "FAIL: $1"; fail=1; }
}
out=$("$py" tests/host/checks.py "$host" 2>&1); summary "host checks" "$out" $?
out=$(bash tests/host/build_checks.sh scripts/build.sh "$tmp/build" 2>&1); summary "build.sh checks" "$out" $?

# mutant KIND FILE CHECK OLD NEW: replace OLD (it must occur exactly once) by NEW in a copy of FILE
#   KIND host: FILE is under host/, the mutant host is built and tests/host/checks.py runs on it
#   KIND build: FILE is scripts/build.sh, tests/host/build_checks.sh runs on the copy
n=0
declare -a kinds checks dirs
mutant() {
    local kind="$1" file="$2" check="$3" old="$4" new="$5"
    n=$((n + 1))
    local d="$tmp/mut$n"
    mkdir -p "$d"
    cp -r host "$d/host"; mkdir -p "$d/scripts"; cp scripts/build.sh "$d/scripts/build.sh"
    if ! SRC="$file" DST="$d/$file" OLD="$old" NEW="$new" "$py" - <<'PY'
import os, sys
s = open(os.environ['SRC'], encoding='utf-8').read()
k = s.count(os.environ['OLD'])
if k != 1:
    print('mutant site matches %d times: %r' % (k, os.environ['OLD'][:70])); sys.exit(1)
open(os.environ['DST'], 'w', encoding='utf-8').write(s.replace(os.environ['OLD'], os.environ['NEW']))
PY
    then echo "FAIL: mutant $n ($check): the site is gone"; fail=1; return; fi
    kinds[$n]="$kind"; checks[$n]="$check"; dirs[$n]="$d"
}
source tests/host/mutants.sh

# build the host mutants in parallel, then run each one's check
jobs=$(nproc 2>/dev/null || echo 4)
for i in $(seq 1 $n); do
    [ "${kinds[$i]:-}" = host ] || continue
    while [ "$(jobs -rp | wc -l)" -ge "$jobs" ]; do wait -n; done
    bash scripts/build.sh --host "${dirs[$i]}/host" --out "${dirs[$i]}/rmlhost" >"${dirs[$i]}/build.log" 2>&1 &
done
wait
red=0
for i in $(seq 1 $n); do
    [ -n "${kinds[$i]:-}" ] || continue
    d="${dirs[$i]}"; c="${checks[$i]}"
    if [ "${kinds[$i]}" = host ]; then
        if [ ! -x "$d/rmlhost" ]; then echo "FAIL: mutant $i ($c) did not build"; tail -3 "$d/build.log"; fail=1; continue; fi
        o=$("$py" tests/host/checks.py "$d/rmlhost" --only "$c" 2>&1)
    else
        o=$(bash tests/host/build_checks.sh "$d/scripts/build.sh" "$d/work" "$c" 2>&1)
    fi
    if echo "$o" | grep -qF -- "FAIL $c"; then red=$((red + 1))
    else echo "FAIL: mutant $i did not turn '$c' red"; echo "$o" | head -5; fail=1; fi
done
echo "mutants: $red of $(( ${#checks[@]} )) turned their check red"
exit $fail
