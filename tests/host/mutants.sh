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
mutant host host/mode_check.inc "click: an event an ancestor also fires makes the click fail" \
    'bool ok = fired.size() == 1 && fired[0] == want;' 'bool ok = !fired.empty() && fired[0] == want;'
mutant host host/mode_check.inc "click: a press on a child of the target reaches the target" \
    'while (up && up != el) up = up->GetParentNode();' 'if (up != el) up = nullptr;'
mutant host host/mode_check.inc "click: an element with pointer-events none is not hit" \
    'context->ProcessMouseMove(x, y, 0);
						Element* hit = context->GetHoverElement();' 'context->ProcessMouseMove(x, y, 0);
						Element* hit = el;'
mutant host host/mode_check.inc "click: an element under an overlay is not hit" \
    'Element* hit = context->GetHoverElement();' 'Element* hit = context->GetElementAtPoint(Vector2f((float)x, (float)y), nullptr, el);'
mutant host host/mode_check.inc "click: a zero-size element is not hit" \
    'if (sz.x <= 0 || sz.y <= 0)' 'if (sz.x < 0 || sz.y < 0)'
mutant host host/mode_check.inc "click: an element outside the context is not hit" \
    'x >= dim.x || y >= dim.y' 'false'
mutant host host/mode_check.inc "click: a box sized by its text alone can be clicked" \
    'NullRender render; Sys sys; MeasureFont font;' 'NullRender render; Sys sys; NullFont font;'
mutant host host/mode_check.inc "click: events the pointer calls on its way there are not the click" \
    'fired.clear();   // what moving there' '// what moving there'

# parity
mutant host host/mode_parity.inc "parity: boolean and string event params reach the expression as such" \
    ': toVariant(kv.second);' ': (kv.second.t == J::Str ? Variant(kv.second.s) : Variant(kv.second.n));'

# Open77's additions
mutant host host/common.hpp "open77: the paint properties parse their documented values" \
    '"miter, round, bevel"' '"miter, bevel"'
mutant host host/common.hpp "open77: a bad paint value is an error" \
    'if (!len->ParseValue(p, part, ParameterMap())) return false;' 'len->ParseValue(p, part, ParameterMap());'
mutant host host/common.hpp "open77: the filters take their documented arguments" \
    'glow("radius, color, strength", "length|color|number")' 'glow("radius, color, strength", "number|color|number")'
mutant host host/common.hpp "open77: a filter with bad arguments is an error" \
    'scanlines("strength, period, speed, grain", "number|number|number|number")' 'scanlines("strength, period, speed, grain", "number|length|number|number")'
mutant host host/common.hpp "open77: fx() takes an effect name, numbers and a colour" \
    "if (!(isalnum((unsigned char)c) || c == '_' || c == '-')) return false;" "if (!(isalnum((unsigned char)c) || c == '_')) return false;"
mutant host host/common.hpp "open77: fx() without an effect name or with units is an error" \
    'if (!effect || effect->Get<String>().empty()) {' 'if (!effect) {'

# layout mode
mutant host host/mode_layout.inc "layout: a hidden element drops its text and its whole subtree" \
    'if (!el->IsVisible()) return;' 'if (cv.display() == Style::Display::None) return;'
