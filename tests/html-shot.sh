#!/usr/bin/env bash
# bin/html-shot: a shot only counts when the bindings ran (a page with no lrbind, a script that throws, a {{ }} left in
# the page, a missing report all FAIL); the server, the Chromium it starts (killed with its children on a timeout), its
# profile, the output names and the Chromium discovery. Two groups: "fake" checks use a stand-in for Chromium (always
# run), "real" checks use the real headless shell (when none is found: skipped, unless NUIKIT_REQUIRE_CHROME=1, which
# CI sets). Each check has a mutant: a copy of html-shot with ONE bug that must turn it red. Contract: tests/README.md.
set -uo pipefail
kit="${NUIKIT:?run through scripts/test.sh}"; tmp="${NUIKIT_TMP:?}"
cd "$kit"
fail=0
py=$(command -v python3)

real_chrome=$(bin/html-shot --find 2>/dev/null) || real_chrome=""
if [ -z "$real_chrome" ] && [ "${NUIKIT_REQUIRE_CHROME:-}" = 1 ]; then
    echo "FAIL: no Chromium found and NUIKIT_REQUIRE_CHROME=1 (set NUIKIT_CHROME, or npx playwright install chromium-headless-shell)"
    fail=1
fi

# ---- fixtures ----
site="$tmp/site"; mkdir -p "$site/web"
cp lrbind/lrbind.js "$site/web/lrbind.js"
page() {   # page NAME 'BODY': a page under site/web with a data-model root, plus whatever BODY adds
    printf '<!doctype html><html><head><meta charset="utf-8"></head><body data-model="menu"><p>{{title}}</p>%s</body></html>\n' "$2" > "$site/web/$1.html"
}
page good '<script src="lrbind.js"></script>'
page defer '<script defer src="lrbind.js"></script>'
page module '<script type="module" src="lrbind.js"></script>'
page none ''
page missing '<script src="no-such-lrbind.js"></script>'
page raw '<script src="lrbind.js"></script><div>{{ outside any model }}</div>'
page throws '<script src="lrbind.js"></script><script>throw new Error("page boom")</script>'
echo '[{"name":"one","model":{"title":"HELLO"}}]' > "$tmp/cases.json"

# a stand-in for Chromium: FAKE_MODE good | noreport | junk | nopng | hang; it fetches the page, as Chromium would
cat > "$tmp/fake-chrome" <<'EOF'
#!/usr/bin/env bash
for a in "$@"; do case "$a" in --screenshot=*) png="${a#--screenshot=}";; http://*) url="$a";; esac; done
echo "$url" >> "$FAKE_DIR/urls"
for a in "$@"; do case "$a" in --user-data-dir=*) echo "${a#--user-data-dir=}" >> "$FAKE_DIR/profiles";; esac; done
key=$(basename "$url" .html)
case "${FAKE_MODE:-good}" in
  hang)    sleep 300 >/dev/null 2>&1 & echo $! > "$FAKE_DIR/child.pid"; wait ;;
  nopng)   ;;
  junk)    echo "not a png" > "$png" ;;
  *)       printf '\x89PNG\r\n\x1a\n' > "$png"
           python3 - "$url" "$key" "${FAKE_MODE:-good}" "$FAKE_DIR" <<'PY'
import sys, urllib.request
url, key, mode, d = sys.argv[1:]
body = urllib.request.urlopen(url).read()
open(d + '/body-' + key + '.html', 'wb').write(body)
if mode != 'noreport':
    origin = url.split('/__html-shot__')[0]
    urllib.request.urlopen(urllib.request.Request(origin + '/__html-shot__/report/' + key, data=b'{"errors":[],"warnings":[],"raw":[]}', method='POST'))
PY
           ;;
esac
EOF
chmod +x "$tmp/fake-chrome"

# run TOOL ARGS... -> $out (stdout+stderr), $rc
run() { out=$("$@" 2>&1) && rc=0 || rc=$?; }

want() {   # want NAME COND... : a check line
    local name="$1"; shift
    if "$@"; then echo "ok   $name"; else echo "FAIL $name"; fi
}
has() { grep -qF -- "$2" <<<"$1"; }
hasnt() { ! grep -qF -- "$2" <<<"$1"; }

# ---- the fake-Chromium group ----
fake_checks() {   # fake_checks TOOL
    local tool="$1" d="$tmp/fk$RANDOM"; mkdir -p "$d/out"
    export FAKE_DIR="$d" NUIKIT_CHROME="$tmp/fake-chrome" TMPDIR="$d/tmp"; mkdir -p "$TMPDIR"
    local cases="$tmp/cases.json"

    FAKE_MODE=good run "$tool" "$site/web/good.html" "$cases" --out "$d/out"
    want "fake: a shot with a report is ok and its PNG is written" test $rc = 0 -a -s "$d/out/one.png"
    want "fake: the page is served from 127.0.0.1 on a port of its own" grep -qE '^http://127\.0\.0\.1:[0-9]+/__html-shot__/one\.html$' "$d/urls"
    want "fake: the injected script carries the case's model and the report address" \
        bash -c 'grep -q "LrBind.init({\"models\": {\"menu\": {\"title\": \"HELLO\"}}" "$1" && grep -q "/__html-shot__/report/one" "$1"' _ "$d/body-one.html"
    want "fake: the profile directory is removed afterwards" bash -c '! test -d "$(head -1 "$1")"' _ "$d/profiles"
    want "fake: the profile is in TMPDIR" grep -q "^$TMPDIR/html-shot-" "$d/profiles"

    FAKE_MODE=noreport run "$tool" "$site/web/good.html" "$cases" --out "$d/out"
    want "fake: no report from the page is a FAIL, exit 1" bash -c '[ "$1" = 1 ] && grep -q "FAIL one: the page sent no report" <<<"$2"' _ "$rc" "$out"

    rm -f "$d/out/one.png"; FAKE_MODE=nopng run "$tool" "$site/web/good.html" "$cases" --out "$d/out"
    want "fake: no PNG is a FAIL" bash -c '[ "$1" = 1 ] && grep -q "FAIL one: Chromium wrote no PNG" <<<"$2"' _ "$rc" "$out"
    printf '\x89PNG\r\n\x1a\nSTALE' > "$d/out/one.png"; FAKE_MODE=nopng run "$tool" "$site/web/good.html" "$cases" --out "$d/out"
    want "fake: a PNG left from an earlier run does not pass for this run's" bash -c '[ "$1" = 1 ] && ! test -e "$2"' _ "$rc" "$d/out/one.png"

    FAKE_MODE=junk run "$tool" "$site/web/good.html" "$cases" --out "$d/out"
    want "fake: a file that is not a PNG is a FAIL" bash -c '[ "$1" = 1 ] && grep -q "FAIL one: Chromium wrote no PNG" <<<"$2"' _ "$rc" "$out"

    # names: no separators in the file, nothing outside --out, two names that collide are refused
    printf '[{"name":"../escaped","model":{"title":"x"}},{"name":"a/b","model":{"title":"x"}}]' > "$d/names.json"
    FAKE_MODE=good run "$tool" "$site/web/good.html" "$d/names.json" --out "$d/out/in"
    want "fake: a case name with separators is written inside --out, separators replaced" \
        bash -c '[ "$1" = 0 ] && test -s "$2/in/_.._escaped.png" && test -s "$2/in/a_b.png" && ! test -e "$2/escaped.png" && ! test -e "$2/../escaped.png"' _ "$rc" "$d/out"
    printf '[{"name":"a/b","model":{}},{"name":"a_b","model":{}}]' > "$d/dup.json"
    FAKE_MODE=good run "$tool" "$site/web/good.html" "$d/dup.json" --out "$d/out/dup"
    want "fake: two names that end up as one file are refused (exit 2)" bash -c '[ "$1" = 2 ] && grep -q "would both be written" <<<"$2"' _ "$rc" "$out"

    # a model string cannot end the injected script early
    printf '[{"name":"xss","model":{"title":"</script><b id=pwn>"}}]' > "$d/xss.json"
    FAKE_MODE=good run "$tool" "$site/web/good.html" "$d/xss.json" --out "$d/out"
    want "fake: a </script> in a model string stays inside the injected script" \
        bash -c '! grep -q "</script><b id=pwn>" "$1" && grep -q "<\\\\/script><b id=pwn>" "$1"' _ "$d/body-xss.html"

    run "$tool" --help
    want "fake: --help (exit 0) explains the options" bash -c '[ "$1" = 0 ] && grep -q -- "--serve-root  the folder served" <<<"$2"' _ "$rc" "$out"
    unset FAKE_DIR NUIKIT_CHROME TMPDIR
}

# ---- a Chromium that hangs (its own group: it waits for the timeout) ----
hang_checks() {   # hang_checks TOOL
    local tool="$1" d="$tmp/hg$RANDOM"; mkdir -p "$d/out" "$d/tmp"
    export FAKE_DIR="$d" NUIKIT_CHROME="$tmp/fake-chrome" TMPDIR="$d/tmp"
    local cases="$tmp/cases.json"
    FAKE_MODE=hang run "$tool" "$site/web/good.html" "$cases" --out "$d/out" --timeout 2
    want "fake: a Chromium that hangs is a FAIL after --timeout" bash -c '[ "$1" = 1 ] && grep -q "FAIL one: Chromium did not finish in 2 s" <<<"$2"' _ "$rc" "$out"
    sleep 0.3
    local cpid; cpid=$(cat "$d/child.pid" 2>/dev/null || echo 0)
    want "fake: ... and what it started is killed with it" bash -c '! kill -0 "$1" 2>/dev/null' _ "$cpid"
    kill "$cpid" 2>/dev/null || true

}

# ---- Chromium discovery (no browser started) ----
find_checks() {   # find_checks TOOL
    local tool="$1" h="$tmp/find$RANDOM"
    local sh=chromium_headless_shell- sfx=chrome-headless-shell-linux64/chrome-headless-shell
    mkdir -p "$h/home/.cache/ms-playwright/${sh}999/$(dirname $sfx)" "$h/home/.cache/ms-playwright/${sh}1000/$(dirname $sfx)" \
             "$h/xdg/ms-playwright/${sh}5/$(dirname $sfx)" "$h/pw/${sh}7/$(dirname $sfx)" "$h/bin"
    for f in "$h/home/.cache/ms-playwright/${sh}999/$sfx" "$h/home/.cache/ms-playwright/${sh}1000/$sfx" \
             "$h/xdg/ms-playwright/${sh}5/$sfx" "$h/pw/${sh}7/$sfx"; do : > "$f"; chmod +x "$f"; done
    local env0=(env -i PATH="$h/bin" HOME="$h/home")
    run "${env0[@]}" "$py" "$tool" --find
    want "find: the highest revision wins (1000 over 999, a number not a string)" bash -c '[ "$1" = 0 ] && grep -q "ms-playwright/chromium_headless_shell-1000/" <<<"$2"' _ "$rc" "$out"
    run "${env0[@]}" XDG_CACHE_HOME="$h/xdg" "$py" "$tool" --find
    want "find: XDG_CACHE_HOME/ms-playwright comes before ~/.cache" bash -c 'grep -q "/xdg/ms-playwright/" <<<"$1"' _ "$out"
    run "${env0[@]}" XDG_CACHE_HOME="$h/xdg" PLAYWRIGHT_BROWSERS_PATH="$h/pw" "$py" "$tool" --find
    want "find: PLAYWRIGHT_BROWSERS_PATH comes first" bash -c 'grep -q "/pw/" <<<"$1"' _ "$out"
    run "${env0[@]}" XDG_CACHE_HOME="$h/empty-xdg" "$py" "$tool" --find
    want "find: an XDG_CACHE_HOME without a browser falls back to ~/.cache" bash -c '[ "$1" = 0 ] && grep -q "/home/.cache/" <<<"$2"' _ "$rc" "$out"
    run "${env0[@]}" NUIKIT_CHROME="$tmp/fake-chrome" PLAYWRIGHT_BROWSERS_PATH="$h/pw" "$py" "$tool" --find
    want "find: NUIKIT_CHROME wins over everything" bash -c 'grep -qx "$1" <<<"$2"' _ "$tmp/fake-chrome" "$out"
    run "${env0[@]}" NUIKIT_CHROME="$h/does-not-exist" "$py" "$tool" --find
    want "find: a NUIKIT_CHROME that does not exist is none (exit 2), not a silent fallback" test $rc = 2
    run env -i PATH="$h/bin" HOME="$h/nothing" "$py" "$tool" --find
    want "find: nothing anywhere is none, exit 2" bash -c '[ "$1" = 2 ] && [ "$2" = none ]' _ "$rc" "$out"
}

# ---- the real-Chromium group ----
real_checks() {   # real_checks TOOL
    local tool="$1" d="$tmp/rl$RANDOM"; mkdir -p "$d"
    export TMPDIR="$d"; unset NUIKIT_CHROME
    local cases="$tmp/cases.json"
    run "$tool" "$site/web/good.html" "$cases" --out "$d/good"
    want "real: a page with lrbind.js in a plain script is shot and bound (exit 0)" bash -c '[ "$1" = 0 ] && grep -q "^ok" <<<"$2" && test -s "$3/good/one.png"' _ "$rc" "$out" "$d"
    run "$tool" "$site/web/defer.html" "$cases" --out "$d/defer"
    want "real: lrbind.js in a deferred script works too" test $rc = 0
    run "$tool" "$site/web/module.html" "$cases" --out "$d/module"
    want "real: lrbind.js in a module script works too" test $rc = 0
    run "$tool" "$site/web/none.html" "$cases" --out "$d/none"
    want "real: a page without lrbind.js is a FAIL (LrBind is not defined), exit 1" bash -c '[ "$1" = 1 ] && grep -q "FAIL one: LrBind is not defined" <<<"$2"' _ "$rc" "$out"
    run "$tool" "$site/web/missing.html" "$cases" --out "$d/missing"
    want "real: an lrbind.js that does not load is a FAIL" bash -c '[ "$1" = 1 ] && grep -q "FAIL one: LrBind is not defined" <<<"$2"' _ "$rc" "$out"
    run "$tool" "$site/web/raw.html" "$cases" --out "$d/raw"
    want "real: a {{ }} left in the page is a FAIL" bash -c '[ "$1" = 1 ] && grep -q "FAIL one: unbound {{ }} left in the page: {{ outside any model }}" <<<"$2"' _ "$rc" "$out"
    run "$tool" "$site/web/throws.html" "$cases" --out "$d/throws"
    want "real: a script of the page that throws is a FAIL with its message" bash -c '[ "$1" = 1 ] && grep -q "FAIL one: script error: Uncaught Error: page boom" <<<"$2"' _ "$rc" "$out"
    want "real: ... and the shot of a failed case is kept" test -s "$d/throws/one.png"
    unset TMPDIR
}

# ---- the real file ----
out_f=$(fake_checks bin/html-shot); out_h=$(hang_checks bin/html-shot); out_n=$(find_checks bin/html-shot)
out_r=""
if [ -n "$real_chrome" ]; then out_r=$(real_checks bin/html-shot); else echo "html-shot: the real-Chromium checks are skipped (no Chromium; optional here, required in CI)"; fi
all="$out_f"$'\n'"$out_h"$'\n'"$out_n"$'\n'"$out_r"
all=$(grep -v '^$' <<<"$all")
grep -v '^ok ' <<<"$all" && fail=1
echo "html-shot: $(grep -c '^ok ' <<<"$all") checks ok on the real file"

# ---- mutants ----
i=0
mutant() {   # mutant GROUP NAME OLD NEW: group is fake | find | real
    local group="$1" name="$2" old="$3" new="$4"
    i=$((i + 1))
    local f="$tmp/mut$i/html-shot"
    mkdir -p "$tmp/mut$i"
    if ! SRC=bin/html-shot DST="$f" OLD="$old" NEW="$new" "$py" - <<'PY'
import os, sys
s = open(os.environ['SRC'], encoding='utf-8').read()
if s.count(os.environ['OLD']) != 1:
    print('mutant site matches %d times: %r' % (s.count(os.environ['OLD']), os.environ['OLD'][:70])); sys.exit(1)
open(os.environ['DST'], 'w', encoding='utf-8').write(s.replace(os.environ['OLD'], os.environ['NEW']))
PY
    then echo "FAIL: mutant $i ($name): the site is gone"; fail=1; return; fi
    chmod +x "$f"
    if [ "$group" = real ] && [ -z "$real_chrome" ]; then echo "skip mutant (no Chromium): $name"; return; fi
    # the checks of a mutant run in the background (each with directories of its own), results printed in order below
    while [ "$(jobs -r | wc -l)" -ge 8 ]; do sleep 0.2; done
    (
        o=$("${group}_checks" "$f")
        if grep -q "^FAIL $name" <<<"$o"; then echo "ok   mutant -> red: $name"
        else echo "FAIL: mutant $i did not turn '$name' red"; grep -v '^ok ' <<<"$o" | head -4; fi
    ) > "$tmp/mut$i/result" 2>&1 &
}

mutant fake "fake: a shot with a report is ok" '    if ok != len(cases):' '    if ok != len(cases) + 1:'
mutant fake "fake: the page is served from 127.0.0.1" "'http://127.0.0.1:%d%s'" "'http://localhost:%d%s'"
mutant fake "fake: the injected script carries the case's model" "inject = INJECT.replace('@KEY@', key).replace('@SPEC@', spec)" "inject = INJECT.replace('@KEY@', key).replace('@SPEC@', '{}')"
mutant fake "fake: the profile directory is removed" 'shutil.rmtree(prof, ignore_errors=True)' 'pass'
mutant fake "fake: the profile is in TMPDIR" "prof = tempfile.mkdtemp(prefix='html-shot-')" "prof = tempfile.mkdtemp(prefix='html-shot-', dir='/tmp')"
mutant fake "fake: no report from the page" '    if rep is None:' '    if False:'
mutant fake "fake: no PNG is a FAIL" "if not os.path.exists(png) or open(png, 'rb').read(8) != b'\\x89PNG\\r\\n\\x1a\\n':" "if False:"
mutant fake "fake: a PNG left from an earlier run" '                os.remove(png)   # a stale shot must not pass for this run'"'"'s' '                pass'
mutant fake "fake: a file that is not a PNG" "if not os.path.exists(png) or open(png, 'rb').read(8) != b'\\x89PNG\\r\\n\\x1a\\n':" "if not os.path.exists(png):"
mutant hang "fake: a Chromium that hangs" 'return None, f'"'"'Chromium did not finish in {timeout} s and was killed'"'" 'return 0, f'"'"'Chromium did not finish in {timeout} s and was killed'"'"
mutant hang "fake: ... and what it started is killed" '        os.killpg(proc.pid, signal.SIGKILL)
        proc.communicate()' '        proc.kill()
        proc.communicate()'
mutant fake "fake: a case name with separators" "    return '_' + s if s.startswith('.') or not s else s" "    return name"
mutant fake "fake: two names that end up as one file" '        if other != c['"'"'name'"'"']:' '        if False:'
mutant fake "fake: a </script> in a model string" "replace('</', '<\\\\/')" "replace('</', '</')"
mutant fake "fake: --help" "description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter" "description=__doc__.split('\\n')[0]"
mutant find "find: the highest revision wins" "key=revision)" "key=lambda p: p)"
mutant find "find: XDG_CACHE_HOME/ms-playwright comes before" "    if os.environ.get('XDG_CACHE_HOME'):
        roots.append(os.path.join(os.environ['XDG_CACHE_HOME'], 'ms-playwright'))
" ""
mutant find "find: PLAYWRIGHT_BROWSERS_PATH comes first" "        roots.append(os.path.expanduser(os.environ['PLAYWRIGHT_BROWSERS_PATH']))" "        pass"
mutant find "find: an XDG_CACHE_HOME without a browser falls back" "    roots.append(os.path.expanduser('~/.cache/ms-playwright'))
" ""
mutant find "find: NUIKIT_CHROME wins" "        return env if os.path.exists(env) else None" "        return None"
mutant find "find: a NUIKIT_CHROME that does not exist is none" "        return env if os.path.exists(env) else None" "        return env"
mutant find "find: nothing anywhere is none" "        if p:
            return p
    return None" "        if p:
            return p
    return '/bin/sh'"
mutant real "real: a page with lrbind.js in a plain script" "LrBind.init(@SPEC@)" "LrBind.inti(@SPEC@)"
mutant real "real: a page without lrbind.js is a FAIL" "    if rep.get('errors'):" "    if False:"
mutant real "real: an lrbind.js that does not load" "    if rep.get('errors'):" "    if False:"
mutant real "real: a {{ }} left in the page" "    if rep.get('raw'):" "    if False:"
mutant real "real: lrbind.js in a deferred script" "if (typeof LrBind === 'undefined' && document.readyState === 'loading') document.addEventListener('DOMContentLoaded', go);
  else go();" "go();"
mutant real "real: a script of the page that throws" "window.addEventListener('error', function (e) {" "window.addEventListener('errorx', function (e) {"
mutant real "real: ... and the shot of a failed case is kept" "                print(f'FAIL {c[\"name\"]}: {why} (shot kept: {png})')" "                os.remove(png); print(f'FAIL {c[\"name\"]}: {why} (shot kept: {png})')"

wait
for r in $(ls "$tmp"/mut*/result 2>/dev/null | sort -V); do cat "$r"; done
grep -q '^FAIL' "$tmp"/mut*/result 2>/dev/null && fail=1

exit $fail
