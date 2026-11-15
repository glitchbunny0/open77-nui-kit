# The suite's mutants, sourced by tests/host.sh: mutant KIND FILE CHECK OLD NEW (see there). One bug each; the check
# named must go red on its own.

# scripts/build.sh
mutant build scripts/build.sh "build: two host sources sharing one cache dir get their own binaries" \
    'bin="${out:-$dir/build/rmlhost-$hash}"' 'bin="${out:-$dir/build/rmlhost}"'
mutant build scripts/build.sh "build: a build waits while another holds the cache lock" \
    '    flock 9' '    :'
mutant build scripts/build.sh "build: a checkout at another tag is refused" \
    'if [ "$have" != "$tag" ]; then' 'if false; then'
mutant build scripts/build.sh "build: a killed clone leaves no half checkout behind" \
    '"$url" "$dir.tmp.$$"
    mv "$dir.tmp.$$" "$dir"' '"$url" "$dir"'

# host/common.hpp: the JSON reader
mutant host host/common.hpp "json: an emoji (a surrogate pair) arrives as one 4-byte UTF-8 character" \
    'if (lo >= 0xDC00 && lo < 0xE000) cp =' 'if (false) cp ='
mutant host host/common.hpp "json: the escapes r, b, f and slash decode" \
    "case 'r': out += '\r'; break;" "case 'r': out += 'r'; break;"
mutant host host/common.hpp "json: an unterminated string is an error" \
    'if (p >= e) fail("unterminated string");
			char c' 'if (p >= e) return out;
			char c'
mutant host host/common.hpp "json: a truncated or bad u-escape is an error" \
    'if (e - p < 4) fail("truncated \\u escape");' ''
mutant host host/common.hpp "json: a missing comma or colon is an error" \
    "fail(std::string(\"expected ',' or '\") + close + \"'\");" 'break;'
mutant host host/common.hpp "json: deep nesting is an error, not a stack overflow" \
    'if (++depth > 256) fail("nested deeper than 256");' '++depth;'
mutant host host/common.hpp "json: a bare word is an error" \
    'else fail("unexpected character");' 'else p++;'
mutant host host/common.hpp "json: an integer past int64 is kept as a double" \
    'if (frac || errno == ERANGE)' 'if (frac)'

# case shapes
mutant host host/common.hpp "input: a click without sel or event is an error" \
    'if (!sel || sel->t != J::Str) badInput(kw + ".sel must be a string");' ''
mutant host host/common.hpp "input: a parity step without its fields is an error" \
    '(set->t != J::Str || !st.get("value"))' '(set->t != J::Str)'
mutant host host/common.hpp "input: a parity case without a model is an error" \
    'need("model", J::Obj, "an object", mode == Mode::Parity);' 'need("model", J::Obj, "an object", false);'
mutant host host/common.hpp "input: a place that is not [left, top] is an error" \
    'if (kv.second.t != J::Arr || kv.second.a.size() != 2 || !isNum(&kv.second.a[0]) || !isNum(&kv.second.a[1]))' \
    'if (kv.second.t != J::Arr)'
mutant host host/mode_parity.inc "input: a bad set path is an error, not a hang or a crash" \
    'if (close == std::string::npos) badInput' 'if (false) badInput'
mutant host host/common.hpp "input: a model bound twice is an error" \
    'if (!ctor) badInput(' 'if (false) badInput('
mutant host host/mode_layout.inc "input: a fonts.json without faces is an error" \
    'if (faces.empty()) badInput(' 'if (false) badInput('

# the dynamic data model
mutant host host/common.hpp "model: assigning to an array warns as RmlUi does" \
    'Log::Message(Log::LT_WARNING, "Values can only be assigned to scalar data types.");' ''
mutant host host/common.hpp "model: a member of an empty table reads as a missing struct member" \
    '(j->t == J::Obj && j->o.empty() && (e.index >= 0 || e.name == "size"))' '(j->t == J::Obj && j->o.empty())'

# clicks
mutant host host/mode_check.inc "click: number and boolean args compare as RmlUi prints them" \
    'toVariant(args->a[i]).Get<String>()' 'args->a[i].s'
mutant host host/common.hpp "input: click args that are not scalars are an error" \
    'if (a.t == J::Arr || a.t == J::Obj || a.t == J::Null) badInput' 'if (false) badInput'
