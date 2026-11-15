#!/usr/bin/env bash
# Suite: bin/rml-check. A fixture that must pass, then one mutant per check, each carrying ONE bug:
#   - input mutants: the fixture with a single thing broken (a binding, an event name, a click, a property, ...);
#     rml-check must fail with the matching line and the right exit code;
#   - tool mutants: a copy of bin/rml-check with a single line broken; the check that guards that line must go red
#     (and the fixture still passes everywhere else).
# Runs from the kit root; NUIKIT_TMP is a fresh empty directory.
set -uo pipefail
kit="${NUIKIT:-$(cd "$(dirname "$0")/.." && pwd)}"
tmp="${NUIKIT_TMP:-$(mktemp -d)}"
cd "$kit"
export NUIKIT_HOST; NUIKIT_HOST="$(bash scripts/build.sh)" || { echo "FAIL: scripts/build.sh"; exit 1; }
fx="$tmp/fx"; mkdir -p "$fx" "$tmp/tmpdir"
export TMPDIR="$tmp/tmpdir"
RC="$kit/bin/rml-check"        # the tool under test; a mutant run points it at a broken copy
out=""; code=0; verbose=1

# ---- the fixture: a document with bindings, a data-for, a hidden copy before a visible one, a bare event name
cat > "$fx/ui.rcss" <<'EOF'
body { width: 400dp; height: 300dp; }
.row { color: red; }
EOF
cat > "$fx/ui.rml" <<'EOF'
<rml>
<head><link type="text/rcss" href="ui.rcss"/></head>
<body data-model="m">
<div id="title">{{title}}</div>
<div id="list"><div class="row" data-for="r : rows" data-event-click="pick(r.id)">{{r.name}}</div></div>
<div id="hid" data-if="show"><div class="x" data-event-click="a()">A</div></div>
<div class="x" data-event-click="b(true, 2.5)">B</div>
<div class="btn" data-event-click="close">close</div>
</body>
</rml>
EOF
cat > "$fx/ok.json" <<'EOF'
[{"name":"state","model":{"title":"T","rows":[{"id":2,"name":"n"}],"show":false},
  "events":["pick","a","b","close"],
  "clicks":[{"sel":".row","event":"pick","args":["2"]},
            {"sel":".x","event":"b","args":["1","2.5"]},
            {"sel":".btn","event":"close","args":[]}]}]
EOF

rc() { out="$("$RC" "$@" 2>&1)"; code=$?; }
fail() { [ "$verbose" = 1 ] && { echo "   $1"; printf '%s\n' "$out" | head -8 | sed 's/^/   | /'; }; return 1; }
# want CODE REGEX...: the last rc run exited CODE and printed every REGEX; wantnot: printed none of them
want() { local c=$1; shift; [ "$code" = "$c" ] || { fail "exit $code, want $c"; return 1; }
         for p; do grep -Eq -- "$p" <<<"$out" || { fail "missing /$p/"; return 1; }; done; }
wantnot() { for p; do ! grep -Eq -- "$p" <<<"$out" || { fail "unexpected /$p/"; return 1; }; done; }
# variant FILE SED...: the fixture document (or rcss/cases, by extension) with one edit
variant() { local f=$1; shift; local src="$fx/ui.${f##*.}"; [ "${f##*.}" = json ] && src="$fx/ok.json"; sed "$@" "$src" > "$fx/$f"; }

# ---- the checks (every one takes the tool from $RC)
chk_clean()        { rc "$fx/ui.rml" "$fx/ok.json"; want 0 'cases: 1  clicks ok: 3' 'model: m' 'rml-check: ok$'; }
chk_binding()      { variant b.rml 's/{{r.name}}/{{r.nam}}/'; rc "$fx/b.rml" "$fx/ok.json"; want 1 'WARN .*nam' 'rml-check: FAIL' && wantnot 'CLICK FAIL'; }
chk_event_name()   { variant e.rml 's/pick(r.id)/pik(r.id)/'; rc "$fx/e.rml" "$fx/ok.json"; want 1 'WARN +Could not find data event callback .pik.' 'CLICK FAIL state: \.row -> nothing'; }
chk_click_event()  { variant c.json '0,/"event":"pick"/s//"event":"close"/'; rc "$fx/ui.rml" "$fx/c.json"; want 1 'CLICK FAIL state: \.row -> pick\(2\) \(want close\(2\)\)'; }
chk_click_args()   { variant c.json 's/\["2"\]/["3"]/'; rc "$fx/ui.rml" "$fx/c.json"; want 1 'CLICK FAIL state: \.row -> pick\(2\) \(want pick\(3\)\)'; }
chk_click_hidden() { variant c.json 's/"sel":"\.x"/"sel":"#hid .x"/'; rc "$fx/ui.rml" "$fx/c.json"; want 1 'CLICK FAIL state: #hid \.x -> no element'; }
chk_click_nothing(){ variant c.json 's/"sel":"\.btn"/"sel":"#title"/'; rc "$fx/ui.rml" "$fx/c.json"; want 1 'CLICK FAIL state: #title -> nothing'; }
chk_exit_click()   { variant c.json 's/\["2"\]/["3"]/'; rc "$fx/ui.rml" "$fx/c.json" --quiet; want 1 'CLICK FAIL' && wantnot 'WARN'; }
chk_property()     { variant p.rcss 's/color/colr/'; cp "$fx/ui.rml" "$fx/p.rml"; sed -i 's/ui.rcss/p.rcss/' "$fx/p.rml"
                     rc "$fx/p.rml" "$fx/ok.json"; want 1 "WARN +Syntax error parsing property declaration 'colr: red;'" 'rml-check: FAIL'; }
# the Open77 allow-list: what Open77 adds passes, a typo next to it does not
open77='.row { fill: #FFFFFF; stroke: #000000; stroke-width: 2dp; filter: glow(2dp #FFFFFF 1); decorator: fx(border-flow 1 2); }'
scoped() { printf 'body { width: 400dp; }\n%s\n' "$1" > "$fx/s.rcss"; sed 's/ui.rcss/s.rcss/' "$fx/ui.rml" > "$fx/s.rml"; rc "$fx/s.rml" "$fx/ok.json"; }
chk_allow_open77() { scoped "$open77"; want 0 'rml-check: ok'; }
chk_allow_scope()  { local d; for d in '.row { strokes: 1; }' '.row { fill-rule: 1; }' '.row { filter: blurr(2dp); }' '.row { decorator: bogus(1); }'; do
                       scoped "$d"; want 1 'WARN' 'rml-check: FAIL' || { echo "   (for: $d)"; return 1; }; done; }
chk_allow_flag()   { scoped '.row { glowy: 1; }'; want 1 'WARN' || return 1; rc "$fx/s.rml" "$fx/ok.json" --allow 'glowy'; want 0 'rml-check: ok'; }

# the host protocol, with a scripted host
fake() { printf '#!/bin/sh\ncat >/dev/null\n%s\n' "$2" > "$tmp/fake-$1"; chmod +x "$tmp/fake-$1"; }
withhost() { local h=$1; shift; NUIKIT_HOST="$tmp/fake-$h" rc "$@"; }
chk_load_failed()  { fake load "printf '=== case 0\nLOAD FAILED\n'"; withhost load "$fx/ui.rml" "$fx/ok.json"; want 1 'LOAD FAILED state' 'rml-check: FAIL'; }
chk_no_header()    { fake none "exit 0"; withhost none "$fx/ui.rml" "$fx/ok.json"; want 2 'no "=== case 0" header'; }
chk_host_crash()   { fake crash "echo boom >&2; kill -SEGV \$\$"; withhost crash "$fx/ui.rml" "$fx/ok.json"; want 2 'host failed on case 0 \(state\)' 'boom'; }
chk_forged_lines() { fake forged "printf '=== case 0\nbody\nWARN x1: boom\n=== case 0\nCLICK ok   fake\nLOAD FAILED\n'"
                     withhost forged "$fx/ui.rml" "$fx/ok.json"; want 1 'WARN +boom' 'clicks ok: 0' && wantnot 'LOAD FAILED state'; }
chk_warn_lines()   { fake lines "printf '=== case 0\nbody\nWARN x1: one\n  two\nWARN x2: three\n'"
                     withhost lines "$fx/ui.rml" "$fx/ok.json"; want 1 'WARN +one' '^  two' 'WARN +three' || return 1
                     withhost lines "$fx/ui.rml" "$fx/ok.json" --allow 'two'; want 1 'WARN +three' && wantnot 'WARN +one'; }

# the input
chk_no_cases()     { echo '[]' > "$fx/n.json"; rc "$fx/ui.rml" "$fx/n.json"; want 2 'no cases' && wantnot 'rml-check: ok'; }
chk_cases_shape()  { local j m
                     while IFS='|' read -r m j; do printf '%s' "$j" > "$fx/s.json"; rc "$fx/ui.rml" "$fx/s.json"; want 2 "$m" || { echo "   (for: $j)"; return 1; }; done <<'EOF'
"clicks"|[{"name":"a","model":{},"clicks":{"sel":"div","event":"b"}}]
"sel" and "event"|[{"name":"a","model":{},"events":["b"],"clicks":[{"sel":"div"}]}]
"sel" and "event"|[{"name":"a","model":{},"events":["b"],"clicks":[{"event":"b"}]}]
click args|[{"name":"a","model":{},"events":["b"],"clicks":[{"sel":"div","event":"b","args":[[1]]}]}]
"events"|[{"name":"a","model":{},"events":"b"}]
"size"|[{"name":"a","model":{},"size":[1]}]
"model" must|[{"name":"a","model":[1]}]
"models" must|[{"name":"a","model":{},"models":{"o":3}}]
did you mean 'clicks'|[{"name":"a","model":{},"click":[]}]
cases must be|{"name":"a"}
cases must be|[{"model":{}}]
not JSON|[{"name":"a","model":{"x":NaN}}]
not JSON|nope
EOF
                   }
chk_exit_codes()   { rc "$fx/missing.rml" "$fx/ok.json"; want 2 'document not found' || return 1
                     rc "$fx" "$fx/ok.json"; want 2 'document not found' || return 1
                     rc "$fx/ui.rml" "$fx/missing.json"; want 2 'cannot read cases file' || return 1
                     printf '[{"name":"caf\xe9"}]' > "$fx/latin.json"; rc "$fx/ui.rml" "$fx/latin.json"; want 2 'not UTF-8' || return 1
                     rc "$fx/ui.rml" "$fx/ok.json" --allow '('; want 2 '--allow is not a regular expression' || return 1
                     : > "$fx/empty.rml"; rc "$fx/empty.rml" "$fx/ok.json"; want 2 'document is empty' || return 1
                     rc "$fx/ui.rml" "$fx/ok.json" --outline "$fx/nodir/o.txt"; want 2 'cannot write the outline'; }

# emoji, odd characters, names that look like host output
chk_emoji()        { printf '<rml><body data-model="m"><div>{{t}}</div></body></rml>' > "$fx/em.rml"
                     python3 -c 'import json; print(json.dumps([{"name":"\U0001F600 case","model":{"t":"STREET \U0001F600 a\rb\fc\bd\\r"}}]))' > "$fx/em.json"
                     rc "$fx/em.rml" "$fx/em.json" --outline "$fx/em.txt"; want 0 'rml-check: ok' && grep -qF $'STREET 😀 a b\fc\bd\\r' "$fx/em.txt" \
                       && grep -qx '=== case 😀 case' "$fx/em.txt" || fail "the outline lost the text"; }
chk_name_inject()  { python3 -c 'import json; print(json.dumps([{"name":"a\nWARN x1: injected\n=== case ghost\nLOAD FAILED","model":{"t":"x"}},{"name":"b","model":{"t":"y"}}]))' > "$fx/inj.json"
                     printf '<rml><body data-model="m"><div>{{t}}</div></body></rml>' > "$fx/em.rml"
                     rc "$fx/em.rml" "$fx/inj.json" --outline "$fx/inj.txt"; want 0 'cases: 2' 'rml-check: ok' && wantnot 'injected|ghost|LOAD' \
                       && [ "$(grep -c '^=== case' "$fx/inj.txt")" = 2 ] || fail "forged lines got through"; }
chk_outline_path() { local a b; rc "$fx/ui.rml" "$fx/ok.json"; a=$(sed -n 's/.*outline: //p' <<<"$out"); rc "$fx/ui.rml" "$fx/ok.json"; b=$(sed -n 's/.*outline: //p' <<<"$out")
                     [ -n "$a" ] && [ "$a" != "$b" ] && [ -s "$a" ] && [ -s "$b" ] && [ "${a#"$TMPDIR"/}" != "$a" ] || fail "outline paths '$a' '$b'"; }

# the model name
chk_model_comment(){ printf '<rml><body>\n<!-- <div data-model="old"> -->\n<div my-data-model="nope"></div><div data-model='"'"'m'"'"'>{{t}}</div></body></rml>' > "$fx/mc.rml"
                     echo '[{"name":"a","model":{"t":"1"}}]' > "$fx/mc.json"
                     rc "$fx/mc.rml" "$fx/mc.json"; want 0 'model: m' 'rml-check: ok'; }
chk_model_many()   { printf '<rml><body><div data-model="m">{{t}}</div><div data-model="n">{{u}}</div></body></rml>' > "$fx/mm.rml"
                     echo '[{"name":"a","model":{"t":"1"},"models":{"n":{"u":"2"}}}]' > "$fx/mm.json"
                     rc "$fx/mm.rml" "$fx/mm.json"; want 0 'note: .*several data-model roots \(m, n\).* to m ' 'model: m' || return 1
                     rc "$fx/mm.rml" "$fx/mm.json" --model m; wantnot 'note:'; }
chk_model_none()   { printf '<rml><body>x</body></rml>' > "$fx/nm.rml"; rc "$fx/nm.rml" "$fx/ok.json"; want 2 'no --model given'; }

# warnings are attributed to every case that sees them (RmlUi caches a parsed stylesheet within one process)
chk_warn_each_case(){ variant p.rcss 's/color/colr/'; sed 's/ui.rcss/p.rcss/' "$fx/ui.rml" > "$fx/p.rml"
                      echo '[{"name":"one","model":{"title":"T","rows":[],"show":false}},{"name":"two","model":{"title":"T","rows":[],"show":false}}]' > "$fx/two.json"
                      rc "$fx/p.rml" "$fx/two.json"; want 1 "colr: red;'.*\[one, two\]"; }

CHECKS=(chk_clean chk_binding chk_event_name chk_click_event chk_click_args chk_click_hidden chk_click_nothing chk_exit_click
        chk_property chk_allow_open77 chk_allow_scope chk_allow_flag
        chk_load_failed chk_no_header chk_host_crash chk_forged_lines chk_warn_lines
        chk_no_cases chk_cases_shape chk_exit_codes chk_emoji chk_name_inject chk_outline_path
        chk_model_comment chk_model_many chk_model_none chk_warn_each_case)

failed=()
run_checks() { failed=(); local c; for c in "${CHECKS[@]}"; do
                 if "$c" >"$tmp/check.log" 2>&1; then [ "$verbose" = 1 ] && echo "ok:   ${c#chk_}"
                 else failed+=("$c"); [ "$verbose" = 1 ] && { echo "FAIL: ${c#chk_}"; sed 's/^/      /' "$tmp/check.log"; }; fi; done; }

echo "== the fixture and every input mutant"
run_checks
status=0; [ ${#failed[@]} = 0 ] || status=1

# ---- tool mutants: one line of a copy of bin/rml-check broken; $2 names the check(s) that must go red
mname=(); mold=(); mnew=(); mexp=()
mut() { mname+=("$1"); mold+=("$2"); mnew+=("$3"); mexp+=("$4"); }
mut emoji_escaped    'ensure_ascii=False' 'ensure_ascii=True' "chk_emoji"
mut load_failed_lost "elif line == 'LOAD FAILED':" "elif line == 'LOAD FAILED!':" "chk_load_failed"
mut warnings_dropped 'if not any(p.search(msg) for p in allowed):' 'if False:' "chk_allow_flag chk_allow_scope chk_binding chk_property chk_warn_each_case chk_warn_lines chk_forged_lines chk_event_name"
mut click_fail_lost  "fails += [f'{name}: {f}' for f in res['fails']]" 'pass' "chk_click_args chk_click_event chk_click_hidden chk_click_nothing chk_event_name chk_exit_click"
mut click_exit_lost  'if bad or fails or loadfail:' 'if bad or loadfail:' "chk_click_args chk_click_event chk_click_hidden chk_click_nothing chk_exit_click"
mut allow_everything "ALLOWED_BASE = [r'^No font face defined']" "ALLOWED_BASE = [r'']" "chk_allow_flag chk_allow_scope chk_binding chk_property chk_warn_each_case chk_warn_lines chk_forged_lines chk_event_name"
mut allow_too_wide   "property declaration '(fill|stroke|stroke-width" "property declaration '([a-z]+|fill|stroke|stroke-width" "chk_allow_flag chk_allow_scope chk_property chk_warn_each_case"
mut allow_filter_gone '\b(glow|chromatic|scanlines)\(' '\b(chromatic|scanlines)\(' "chk_allow_open77"
mut allow_flag_lost  '[re.compile(p) for p in ALLOWED_BASE + ALLOWED_OPEN77 + a.allow]' '[re.compile(p) for p in ALLOWED_BASE + ALLOWED_OPEN77]' "chk_allow_flag chk_exit_codes chk_warn_lines"
mut empty_cases_ok   'if not cases:' 'if False:' "chk_no_cases"
mut clicks_unchecked "if not isinstance(c['clicks'], list):" 'if False:' "chk_cases_shape"
mut size_unchecked   "if 'size' in c and not" "if False and not" "chk_cases_shape"
mut name_unescaped   "name = esc(c['name'])" "name = c['name']" "chk_name_inject"
mut crlf_unescaped   "{'r': '\\\\u000d', 'f': '\\\\u000c', 'b': '\\\\u0008'}.get(m.group(1), m.group())" 'm.group()' "chk_emoji"
mut forged_lines_in  "        if r['warns']:" "        if False:" "chk_forged_lines chk_warn_lines"
mut warn_lines_split "r['warns'][-1] += '\n' + line" 'pass' "chk_warn_lines"
mut no_header_ok     "if not lines or lines[0] != f'=== case {idx}':" 'if False:' "chk_no_header"
mut exit_is_1        'def die(msg, code=2):' 'def die(msg, code=1):' "chk_cases_shape chk_exit_codes chk_host_crash chk_model_none chk_no_cases chk_no_header"
mut model_comments   '    txt = mask(txt)
    for m in TAG' '    for m in TAG' "chk_model_comment"
mut model_last       'model = a.model or (names[0] if names else None)' 'model = a.model or (names[-1] if names else None)' "chk_model_many"
mut note_lost        'if not a.model and len(names) > 1:' 'if False:' "chk_model_many"
mut outline_fixed    "fd, out = tempfile.mkstemp(prefix='rml-check-', suffix='.outline.txt')" "out = os.path.join(tempfile.gettempdir(), 'rml-check-outline.txt'); fd = os.open(out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC)" "chk_outline_path"
mut one_process      "for msg in res['warns']:" "for msg in (res['warns'] if idx == 0 else []):" "chk_warn_each_case"
mut allow_regex_die  'except re.error as e:' 'except KeyError as e:' "chk_exit_codes"
mut doc_empty_ok     'if not doc_txt.strip():' 'if False:' "chk_exit_codes"

for n in "${!mname[@]}"; do
    name="${mname[n]}"; old="${mold[n]}"; new="${mnew[n]}"; expect="${mexp[n]}"
    mkdir -p "$tmp/mut"
    NUIKIT="$kit" python3 - "$name" "$old" "$new" "$tmp/mut/$name" <<'EOF' || { echo "FAIL: mutant $name does not apply"; status=1; continue; }
import os, sys
name, old, new, dst = sys.argv[1:5]
src = open(os.path.join(os.environ['NUIKIT'], 'bin', 'rml-check'), encoding='utf-8').read()
if src.count(old) != 1:
    sys.exit(f'mutant {name}: the pattern occurs {src.count(old)} times, want exactly 1')
open(dst, 'w', encoding='utf-8').write(src.replace(old, new))
os.chmod(dst, 0o755)
EOF
    RC="$tmp/mut/$name"; verbose=0; run_checks; RC="$kit/bin/rml-check"; verbose=1
    # red ON ITS OWN: exactly the named checks fail, nothing else
    got=$(printf '%s\n' "${failed[@]}" | sort | tr '\n' ' '); want_set=$(printf '%s\n' $expect | sort | tr '\n' ' ')
    if [ "$got" != "$want_set" ]; then echo "FAIL: mutant $name: red in [${got}], expected [${want_set}]"; status=1
    else echo "ok:   mutant $name -> red: ${got//chk_/}"; fi
done
[ $status = 0 ] && echo "rml-check suite: ALL OK" || echo "rml-check suite: FAILED"
exit $status
