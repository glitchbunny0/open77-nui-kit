# The suite's mutants, sourced by tests/host.sh: mutant KIND FILE CHECK OLD NEW (see there). One bug each; the check
# named must go red on its own.

# scripts/build.py
mutant build scripts/build.py "build: two host sources sharing one cache dir get their own binaries" \
    "f'rmlhost-{host_hash(cc, src)}{exe}'" "f'rmlhost{exe}'"
mutant build scripts/build.py "build: a build waits while another holds the cache lock" \
    "    with Lock(d + '.lock'):" "    with open(d + '.lock', 'a'):"
mutant build scripts/build.py "build: a checkout at another tag is refused" \
    'if have != TAG:' 'if False:'
mutant build scripts/build.py "build: the compiler found is remembered, and probed again when it changed" \
    'entry = known.get(key) if isinstance(known, dict) else None' 'entry = None'
mutant build scripts/build.py "build: the compiler found is remembered, and probed again when it changed" \
    "if entry and entry['stamp'] and stamp(entry['cmd'][0]) == entry['stamp']:" 'if entry:'
mutant build scripts/build.py "build: the compiler found is remembered, and probed again when it changed" \
    '        os.replace(tmp, memo)' '        os.remove(tmp)'
mutant build scripts/build.py "build: a killed clone leaves no half checkout behind" \
    "URL, tmp], stdout=sys.stderr)
        if r.returncode:
            die(f'git clone of RmlUi {TAG} from {URL} failed', 1)
        rename(tmp, d)" "URL, d], stdout=sys.stderr)
        if r.returncode:
            die(f'git clone of RmlUi {TAG} from {URL} failed', 1)"

# files by UTF-8 path: only Windows has another narrow encoding, so only there can these turn their check red
if [ "$windows" = 1 ]; then
    mutant host host/rmlhost.cpp "files: a document, its sheet, an image and fonts.json under a non-ASCII folder" \
        'if (wargv) { argc = wargc; argv = ptrs.data(); }' 'if (false) { argc = wargc; argv = ptrs.data(); }'
    mutant host host/common.hpp "files: a document, its sheet, an image and fonts.json under a non-ASCII folder" \
        'return (FileHandle)_wfopen(u8(path).c_str(), L"rb");' 'return (FileHandle)fopen(path.c_str(), "rb");'
    mutant host host/common.hpp "files: a document, its sheet, an image and fonts.json under a non-ASCII folder" \
        'std::ifstream f(u8(path), std::ios::binary);' 'std::ifstream f(path, std::ios::binary);'
    mutant host host/mode_layout.inc "files: a document, its sheet, an image and fonts.json under a non-ASCII folder" \
        'std::ifstream fj(u8(fontsPath), std::ios::binary);' 'std::ifstream fj(fontsPath, std::ios::binary);'
    mutant host host/rmlhost.cpp "files: ../ in an image path climbs from the folder of a document given with native" \
        "if (args.size() > 2) std::replace(args[2].begin(), args[2].end(), '\\\\', '/');" ''
fi

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
mutant host host/mode_layout.inc "layout: overflow clips to the padding box of the clipping ancestor" \
    'ElementUtilities::GetClippingRegion(el, r)' 'ElementUtilities::GetClippingRegion(el, r, nullptr, true)'
mutant host host/mode_layout.inc "layout: the clip follows the offset-parent chain (an absolute child escapes; clip: none)" \
    'ElementUtilities::GetClippingRegion(el, r)' 'ElementUtilities::GetClippingRegion(el->GetParentNode() ? el->GetParentNode() : el, r, nullptr, el->GetParentNode() && el->GetParentNode()->GetParentNode())'
mutant host host/mode_layout.inc "layout: nothing clips an unclipped box, whatever the context size" \
    'if (!ElementUtilities::GetClippingRegion(el, r)) return "null";' 'if (!ElementUtilities::GetClippingRegion(el, r)) return "[0.0,0.0,1920.0,1080.0]";'
mutant host host/mode_layout.inc "layout: text comes as RmlUi draws it, text-transform applied, with no flag to apply it again" \
    '<< ",\"clip\":" << clipOf(t) << "}";' '<< ",\"clip\":" << clipOf(t) << ",\"upper\":" << (cv.text_transform() == Style::TextTransform::Uppercase ? "true" : "false") << "}";'
mutant host host/mode_layout.inc "layout: each case lists its own warnings" \
    '	for (J& c : cases.a) {
		warnings.clear();' '	for (J& c : cases.a) {'
mutant host host/mode_check.inc "check: a stylesheet warning shows in every case" \
    'Factory::ClearStyleSheetCache();' ''

# fonts
mutant host host/common.hpp "font: an unknown family gets no face and no text, as in RmlUi" \
    '		if (f < 0) return 0;
		Handle h{f' '		if (f < 0) f = 0;
		Handle h{f'
mutant host host/common.hpp "font: a missing weight takes the nearest loaded face, with a warning" \
    'if (best < 0 || std::abs(f.weight - weight) < std::abs(faces[best].weight - weight)) best = (int)i;' 'if (best < 0) best = (int)i;'
mutant host host/common.hpp "font: a missing weight takes the nearest loaded face, with a warning" \
    'Log::Message(Log::LT_WARNING, "Font face substituted:' 'if (false) Log::Message(Log::LT_WARNING, "Font face substituted:'
mutant host host/common.hpp "font: italic text needs an italic face" \
    'if (f.family != family || f.italic != italic) continue;' 'if (f.family != family) continue;'

# text widths
mutant host host/common.hpp "width: each glyph adds its whole-pixel advance" \
    'width += (int)std::lround((it != f.adv.end() ? it->second : f.def) * hd.size / 1000.f);' 'width += (int)((it != f.adv.end() ? it->second : f.def) * hd.size / 1000.f);'
mutant host host/common.hpp "width: letter-spacing adds its whole pixels per glyph" \
    'width += (int)ctx.letter_spacing;' 'width += (int)std::lround(ctx.letter_spacing);'
mutant host host/common.hpp "width: a glyph the font lacks adds nothing" \
    'if (it != f.adv.end() && it->second < 0) continue;' 'if (it != f.adv.end() && it->second < 0) it = f.adv.end();'
mutant host host/common.hpp "width: a control character adds nothing" \
    'if (c < 0x20) continue;' ''
mutant host host/common.hpp "width: kerning pairs from fonts.json apply unless font-kerning is none" \
    'bool kerning = ctx.font_kerning != Style::FontKerning::None && !f.kern.empty();' 'bool kerning = !f.kern.empty();'
mutant host host/common.hpp "width: an emoji counts as one glyph" \
    'if (c >= 0xF0 && p + 2 < e)' 'if (false)'
mutant host host/mode_layout.inc "layout: a text run carries its measured width" \
    '<< widthOf(t, line.text) <<' '<< 0 <<'

# classes
mutant host host/mode_check.inc "classes: the check outline sorts them" \
    'std::string c = classesOf(el);' 'std::string c = el->GetClassNames();'
mutant host host/mode_layout.inc "classes: layout sorts them" \
    'q(classesOf(el))' 'q(el->GetClassNames())'

# layout numbers
mutant host host/common.hpp "layout: a probe document lays out to known numbers" \
    'h.m.ascent = faces[f].ascent * size / 1000.f;' 'h.m.ascent = faces[f].descent * size / 1000.f;'
mutant host host/mode_layout.inc "layout: a probe document lays out to known numbers" \
    'Vector2f sz = el->GetBox().GetSize(BoxArea::Border);' 'Vector2f sz = el->GetBox().GetSize(BoxArea::Content);'

# images
mutant host host/common.hpp "image: a missing img src is reported" \
    'if (path.empty()) return 0;' 'if (path.empty()) { d = {1, 1}; return 1; }'
mutant host host/mode_check.inc "image: a missing decorator image is reported" \
    'renderOnce(context);   // decorators' '// decorators'
mutant host host/common.hpp "image: an image next to the document or under the resource root is found" \
    'if (fs::is_regular_file(dir / u8(source), ec)) return (dir / u8(source)).u8string();' ''
mutant host host/common.hpp "image: an img takes the PNG natural size" \
    'd = imageSize(path);' 'd = {1, 1};'
mutant host host/common.hpp "image: drawing raises no noise of its own" \
    'if (type == Log::LT_ASSERT && rendering) return true;' ''
mutant host host/common.hpp "image: drawing raises no noise of its own" \
    'CompileShader(const String&, const Dictionary&) override { return 1; }' 'CompileShader(const String&, const Dictionary&) override { return 0; }'
mutant host host/mode_layout.inc "image: layout lists a missing image in the case warnings" \
    'renderOnce(context);   // decorators' '// decorators'

# check output
mutant host host/mode_check.inc "check: a newline in a case name cannot start a line of its own" \
    '<< oneLine(c.get("name")->s) <<' '<< c.get("name")->s <<'
mutant host host/mode_check.inc "check: warnings keep the order RmlUi logged them in" \
    'if (it == seen.end()) seen.emplace_back(w, 1);
			else it->second++;
		}' 'if (it == seen.end()) seen.emplace_back(w, 1);
			else it->second++;
		}
		std::sort(seen.begin(), seen.end());'
