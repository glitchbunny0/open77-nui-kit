#!/usr/bin/env bash
# rmlhost's own tests (host/ and scripts/build.py). Suite contract: tests/README.md.
#   1. tests/host/checks.py on the real host: check, layout and parity mode against the probe documents in tests/host/
#   2. tests/host/build_checks.py on the real scripts/build.py (a fake RmlUi, so it takes seconds)
#   3. mutants: broken copies of a host/ file or of build.py, one bug each, built into $NUIKIT_TMP; each must turn the
#      check it names red on its own
set -uo pipefail
kit="${NUIKIT:?run through scripts/test.sh}"; tmp="${NUIKIT_TMP:?}"
cd "$kit"
source tests/lib/os.sh   # py, plant, shim, upath, windows
py="${PYTHON:-python3}"
fail=0
host=$("$py" scripts/build.py 2>/dev/null | tail -1)
[ -x "$host" ] || { echo "FAIL: scripts/build.py did not build the host"; exit 1; }

summary() {   # summary LABEL OUTPUT RC
    [ -z "$2" ] || echo "$2" | grep -v '^ok ' || true
    echo "$1: $(echo "$2" | grep -c '^ok ' || true) checks ok"
    [ "$3" = 0 ] || { echo "FAIL: $1"; fail=1; }
}
out=$("$py" tests/host/checks.py "$host" 2>&1); summary "host checks" "$out" $?
out=$("$py" tests/host/build_checks.py scripts/build.py "$tmp/build" 2>&1); summary "build checks" "$out" $?

# mutant KIND FILE CHECK OLD NEW: replace OLD (it must occur exactly once) by NEW in a copy of FILE
#   KIND host: FILE is under host/, the mutant host is built and tests/host/checks.py runs on it
#   KIND build: FILE is scripts/build.py, tests/host/build_checks.py runs on the copy
n=0
declare -a kinds checks dirs
mutant() {
    local kind="$1" file="$2" check="$3" old="$4" new="$5"
    n=$((n + 1))
    local d="$tmp/mut$n"
    mkdir -p "$d"
    cp -r host "$d/host"; mkdir -p "$d/scripts"; cp scripts/build.py "$d/scripts/build.py"
    if ! plant "$file" "$d/$file" "$old" "$new"
    then echo "FAIL: mutant $n ($check): the site is gone"; fail=1; return; fi
    kinds[$n]="$kind"; checks[$n]="$check"; dirs[$n]="$d"
}
source tests/host/mutants.sh

# build the host mutants in parallel (a build.py each, as many at once as there are CPUs), then run each one's check;
# the folders go as arguments, which Git Bash turns into Windows paths (a file's content it would leave alone)
hostdirs=()
for i in $(seq 1 $n); do [ "${kinds[$i]:-}" = host ] && hostdirs+=("${dirs[$i]}"); done
"$py" - ${hostdirs[@]+"${hostdirs[@]}"} <<'PY'
import concurrent.futures, os, subprocess, sys
dirs = sys.argv[1:]
def build(d):
    with open(os.path.join(d, 'build.log'), 'wb') as log:
        subprocess.run([sys.executable, 'scripts/build.py', '--host', os.path.join(d, 'host'),
                        '--out', os.path.join(d, 'rmlhost')], stdout=log, stderr=log)
with concurrent.futures.ThreadPoolExecutor(os.cpu_count() or 4) as pool:
    list(pool.map(build, dirs))
PY
red=0
for i in $(seq 1 $n); do
    [ -n "${kinds[$i]:-}" ] || continue
    d="${dirs[$i]}"; c="${checks[$i]}"
    if [ "${kinds[$i]}" = host ]; then
        if [ ! -x "$d/rmlhost" ]; then echo "FAIL: mutant $i ($c) did not build"; tail -3 "$d/build.log"; fail=1; continue; fi
        o=$("$py" tests/host/checks.py "$d/rmlhost" --only "$c" 2>&1)
    else
        o=$("$py" tests/host/build_checks.py "$d/scripts/build.py" "$d/work" "$c" 2>&1)
    fi
    if echo "$o" | grep -qF -- "FAIL $c"; then red=$((red + 1))
    else echo "FAIL: mutant $i did not turn '$c' red"; echo "$o" | head -5; fail=1; fi
done
echo "mutants: $red of $(( ${#checks[@]} )) turned their check red"
exit $fail
