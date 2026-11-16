#pragma once
// open77-nui-kit host: real RmlUi (pinned in scripts/build.py) with a dynamic, Lua-like data model fed from JSON.
// One binary, three modes:
//   rmlhost check  <doc.rml> <model>              < cases.json   element outline, warnings, real clicks per case
//   rmlhost layout <doc.rml> <model> <fonts.json> < cases.json   boxes + text runs + warnings as JSON, real advances
//   rmlhost parity                                 < cases.json   lrbind parity reference (tree after each step)
// Every case: { name, model: {...}, models?: { other: {...} }, events?: [..], clicks?: [{ sel, event, args }],
// place?: { selector: [left, top] }, size?: [w, h] }. See docs/cases.md. Every mode registers Open77's additions to
// RmlUi (registerOpen77). Bad input (malformed JSON, a field of the wrong shape) exits 2 with a message on stderr.
#include <algorithm>
#include <fstream>
#include <cerrno>
#include <cmath>
#include <cstdlib>
#include <cstring>
#include <stdexcept>
#include <RmlUi/Core.h>
#include <RmlUi/Core/DataVariable.h>
#include <RmlUi/Core/ElementText.h>
#include <RmlUi/Core/ElementUtilities.h>
#include <RmlUi/Core/Decorator.h>
#include <RmlUi/Core/Filter.h>
#include <RmlUi/Core/PropertyDefinition.h>
#include <RmlUi/Core/PropertyDictionary.h>
#include <RmlUi/Core/PropertyParser.h>
#include <RmlUi/Core/RenderManager.h>
#include <RmlUi/Core/StyleSheetSpecification.h>
#include <cstdio>
#include <filesystem>
#include <iostream>
#include <iterator>
#include <map>
#include <memory>
#include <sstream>
#include <string>
#include <vector>
#include <functional>

using namespace Rml;

// ---- a tiny JSON value
struct J {
	enum T { Null, Bool, Int, Num, Str, Arr, Obj } t = Null;
	bool b = false;
	long long i = 0;
	double n = 0;
	std::string s;
	std::vector<J> a;
	std::vector<std::pair<std::string, J>> o;
	J* get(const std::string& k) {
		for (auto& kv : o)
			if (kv.first == k)
				return &kv.second;
		return nullptr;
	}
};

// Bad input (malformed JSON, a case field of the wrong shape): main() prints the message and exits 2.
struct BadInput : std::runtime_error {
	using std::runtime_error::runtime_error;
};
[[noreturn]] static void badInput(const std::string& msg) { throw BadInput(msg); }

// A strict JSON parser: every read is bounds-checked, errors name the byte offset. \uXXXX surrogate pairs become one
// 4-byte UTF-8 sequence (json.dumps writes every astral character, an emoji, that way); a lone surrogate becomes U+FFFD.
// Integers outside int64 are kept as doubles, as Lua would hold them.
struct P {
	const char* b;
	const char* p;
	const char* e;
	std::string what;
	int depth = 0;
	P(const std::string& s, std::string what) : b(s.data()), p(s.data()), e(s.data() + s.size()), what(std::move(what)) {}
	[[noreturn]] void fail(const std::string& msg) { badInput(what + ": not valid JSON: " + msg + " at offset " + std::to_string(p - b)); }
	void ws() { while (p < e && (*p == ' ' || *p == '\n' || *p == '\t' || *p == '\r')) p++; }
	bool at(char c) const { return p < e && *p == c; }
	static void put(std::string& out, unsigned cp) {
		if (cp < 0x80) out += char(cp);
		else if (cp < 0x800) { out += char(0xC0 | (cp >> 6)); out += char(0x80 | (cp & 0x3F)); }
		else if (cp < 0x10000) { out += char(0xE0 | (cp >> 12)); out += char(0x80 | ((cp >> 6) & 0x3F)); out += char(0x80 | (cp & 0x3F)); }
		else { out += char(0xF0 | (cp >> 18)); out += char(0x80 | ((cp >> 12) & 0x3F)); out += char(0x80 | ((cp >> 6) & 0x3F)); out += char(0x80 | (cp & 0x3F)); }
	}
	unsigned hex4() {
		if (e - p < 4) fail("truncated \\u escape");
		unsigned v = 0;
		for (int i = 0; i < 4; i++) {
			char c = p[i];
			v <<= 4;
			if (c >= '0' && c <= '9') v |= unsigned(c - '0');
			else if (c >= 'a' && c <= 'f') v |= unsigned(c - 'a' + 10);
			else if (c >= 'A' && c <= 'F') v |= unsigned(c - 'A' + 10);
			else fail("bad \\u escape");
		}
		p += 4;
		return v;
	}
	std::string str() {
		if (!at('"')) fail("expected a string");
		p++;
		std::string out;
		for (;;) {
			if (p >= e) fail("unterminated string");
			char c = *p++;
			if (c == '"') return out;
			if (c != '\\') { out += c; continue; }
			if (p >= e) fail("unterminated string");
			switch (*p++) {
			case '"': out += '"'; break;
			case '\\': out += '\\'; break;
			case '/': out += '/'; break;
			case 'n': out += '\n'; break;
			case 't': out += '\t'; break;
			case 'r': out += '\r'; break;
			case 'b': out += '\b'; break;
			case 'f': out += '\f'; break;
			case 'u': {
				unsigned cp = hex4();
				if (cp >= 0xD800 && cp < 0xDC00) {
					const char* save = p;
					unsigned lo = 0;
					if (e - p >= 6 && p[0] == '\\' && p[1] == 'u') { p += 2; lo = hex4(); }
					if (lo >= 0xDC00 && lo < 0xE000) cp = 0x10000 + ((cp - 0xD800) << 10) + (lo - 0xDC00);
					else { p = save; cp = 0xFFFD; }
				}
				else if (cp >= 0xDC00 && cp < 0xE000) cp = 0xFFFD;
				put(out, cp);
				break;
			}
			default: p--; fail("bad escape");
			}
		}
	}
	void digits() {
		if (!(p < e && *p >= '0' && *p <= '9')) fail("bad number");
		while (p < e && *p >= '0' && *p <= '9') p++;
	}
	bool word(const char* w) {
		size_t n = strlen(w);
		if (size_t(e - p) >= n && !strncmp(p, w, n)) { p += n; return true; }
		return false;
	}
	J val() {
		ws();
		if (p >= e) fail("unexpected end");
		J j;
		if (*p == '{' || *p == '[') {
			if (++depth > 256) fail("nested deeper than 256");
			bool obj = *p == '{';
			char close = obj ? '}' : ']';
			j.t = obj ? J::Obj : J::Arr;
			p++;
			ws();
			if (at(close)) p++;
			else
				for (;;) {
					if (obj) {
						ws();
						std::string k = str();
						ws();
						if (!at(':')) fail("expected ':'");
						p++;
						j.o.emplace_back(k, val());
					}
					else j.a.push_back(val());
					ws();
					if (at(',')) { p++; continue; }
					if (at(close)) { p++; break; }
					fail(std::string("expected ',' or '") + close + "'");
				}
			depth--;
		}
		else if (*p == '"') { j.t = J::Str; j.s = str(); }
		else if (word("true")) { j.t = J::Bool; j.b = true; }
		else if (word("false")) { j.t = J::Bool; }
		else if (word("null")) {}
		else if (*p == '-' || (*p >= '0' && *p <= '9')) {
			const char* start = p;
			bool frac = false;
			if (at('-')) p++;
			digits();
			if (at('.')) { p++; digits(); frac = true; }
			if (at('e') || at('E')) { p++; if (at('+') || at('-')) p++; digits(); frac = true; }
			std::string num(start, p);
			errno = 0;
			long long v = frac ? 0 : strtoll(num.c_str(), nullptr, 10);
			if (frac || errno == ERANGE) { j.t = J::Num; j.n = strtod(num.c_str(), nullptr); }
			else { j.t = J::Int; j.i = v; }
		}
		else fail("unexpected character");
		return j;
	}
	J all() {
		J j = val();
		ws();
		if (p != e) fail("trailing characters");
		return j;
	}
};
static J parseJson(const std::string& text, const std::string& what) { return P(text, what).all(); }
// A JSON scalar as the Variant RmlUi would hold for it: Get<String>() then prints it as RmlUi prints a value
// (numbers with up to three decimals, trailing zeros cut, booleans 1/0).
static Variant toVariant(const J& j) {
	switch (j.t) {
	case J::Bool: return Variant(j.b);
	case J::Int: return Variant((int64_t)j.i);
	case J::Num: return Variant(j.n);
	case J::Str: return Variant(j.s);
	default: return Variant();
	}
}
static double num(const J& j) { return j.t == J::Int ? (double)j.i : j.n; }
static bool isNum(const J* j) { return j && (j->t == J::Int || j->t == J::Num); }

// The case fields every mode reads, checked before anything runs: a wrong shape is an error naming the case and the
// field (exit 2), never a crash or a silently skipped click. parity: the cases of lrbind/tests/parity/cases.mjs.
enum class Mode { Check, Layout, Parity };
static void validateCases(J& cases, Mode mode) {
	for (size_t ci = 0; ci < cases.a.size(); ci++) {
		J& c = cases.a[ci];
		std::string where = "case " + std::to_string(ci);
		if (c.t != J::Obj) badInput(where + " is not an object");
		J* name = c.get("name");
		if (!name || name->t != J::Str) badInput(where + ": \"name\" must be a string");
		where += " (\"" + name->s + "\")";
		auto need = [&](const char* key, J::T type, const char* what, bool required) -> J* {
			J* f = c.get(key);
			if (!f) { if (required) badInput(where + ": \"" + key + "\" is missing"); return nullptr; }
			if (f->t != type) badInput(where + ": \"" + key + "\" must be " + what);
			return f;
		};
		need("model", J::Obj, "an object", mode == Mode::Parity);
		if (J* ms = need("models", J::Obj, "an object of models", false))
			for (auto& kv : ms->o)
				if (kv.second.t != J::Obj) badInput(where + ": models." + kv.first + " must be an object");
		if (J* evs = need("events", J::Arr, "an array of names", false))
			for (J& e : evs->a)
				if (e.t != J::Str) badInput(where + ": \"events\" must hold strings");
		if (J* size = need("size", J::Arr, "[width, height]", false))
			if (size->a.size() != 2 || !isNum(&size->a[0]) || !isNum(&size->a[1]) || num(size->a[0]) < 1 || num(size->a[1]) < 1)
				badInput(where + ": \"size\" must be [width, height], both positive");
		if (mode == Mode::Check)
			if (J* clicks = need("clicks", J::Arr, "an array", false))
				for (size_t i = 0; i < clicks->a.size(); i++) {
					J& k = clicks->a[i];
					std::string kw = where + ": clicks[" + std::to_string(i) + "]";
					if (k.t != J::Obj) badInput(kw + " must be an object");
					J* sel = k.get("sel");
					J* ev = k.get("event");
					J* args = k.get("args");
					if (!sel || sel->t != J::Str) badInput(kw + ".sel must be a string");
					if (!ev || ev->t != J::Str) badInput(kw + ".event must be a string");
					if (args && args->t != J::Arr) badInput(kw + ".args must be an array");
					if (args)
						for (J& a : args->a)
							if (a.t == J::Arr || a.t == J::Obj || a.t == J::Null) badInput(kw + ".args must hold strings, numbers or booleans");
				}
		if (mode == Mode::Layout)
			if (J* place = need("place", J::Obj, "an object", false))
				for (auto& kv : place->o)
					if (kv.second.t != J::Arr || kv.second.a.size() != 2 || !isNum(&kv.second.a[0]) || !isNum(&kv.second.a[1]))
						badInput(where + ": place[\"" + kv.first + "\"] must be [left, top]");
		if (mode == Mode::Parity) {
			need("rml", J::Str, "a string", true);
			if (J* steps = need("steps", J::Arr, "an array", false))
				for (size_t i = 0; i < steps->a.size(); i++) {
					J& st = steps->a[i];
					std::string sw = where + ": steps[" + std::to_string(i) + "]";
					if (st.t != J::Obj) badInput(sw + " must be an object");
					J* set = st.get("set");
					J* ev = st.get("event");
					if (!set && !ev) badInput(sw + " needs \"set\" or \"event\"");
					if (set && (set->t != J::Str || !st.get("value"))) badInput(sw + ": \"set\" needs a path string and a \"value\"");
					if (ev) {
						J* type = st.get("type");
						J* params = st.get("params");
						if (ev->t != J::Str || !type || type->t != J::Str) badInput(sw + ": \"event\" needs an element id and a \"type\" string");
						if (params && params->t != J::Obj) badInput(sw + ": \"params\" must be an object");
					}
				}
		}
	}
}
static J readCases(Mode mode) {
	std::string input((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
	J cases = parseJson(input, "the cases");
	if (cases.t != J::Arr) badInput("the cases must be a JSON array");
	validateCases(cases, mode);
	return cases;
}

static std::string q(const std::string& s) {
	std::string o = "\"";
	for (unsigned char c : s) {
		if (c == '"' || c == '\\') { o += '\\'; o += c; }
		else if (c == '\n') o += "\\n";
		else if (c < 0x20) { char b[8]; snprintf(b, 8, "\\u%04x", c); o += b; }
		else o += c;
	}
	return o + "\"";
}

// ---- the dynamic definition: one class for every node kind, chosen by the node at access time
class DynDef final : public VariableDefinition {
public:
	DynDef() : VariableDefinition(DataVariableType::Scalar) {}
	bool Get(void* ptr, Variant& v) override {
		J* j = (J*)ptr;
		switch (j->t) {
		case J::Bool: v = j->b; return true;
		case J::Int: v = (int64_t)j->i; return true;
		case J::Num: v = j->n; return true;
		case J::Str: v = j->s; return true;
		default: Log::Message(Log::LT_WARNING, "Values can only be retrieved from scalar data types."); return false;
		}
	}
	bool Set(void* ptr, const Variant& v) override {
		J* j = (J*)ptr;
		if (j->t == J::Arr || j->t == J::Obj) {
			Log::Message(Log::LT_WARNING, "Values can only be assigned to scalar data types.");
			return false;
		}
		switch (v.GetType()) {
		case Variant::BOOL: j->t = J::Bool; j->b = v.Get<bool>(); return true;
		case Variant::INT: case Variant::INT64: j->t = J::Int; j->i = v.Get<int64_t>(); return true;
		case Variant::FLOAT: case Variant::DOUBLE: j->t = J::Num; j->n = v.Get<double>(); return true;
		case Variant::STRING: j->t = J::Str; j->s = v.Get<String>(); return true;
		default: return false;
		}
	}
	int Size(void* ptr) override {
		J* j = (J*)ptr;
		if (j->t == J::Arr) return (int)j->a.size();
		if (j->t == J::Obj && j->o.empty()) return 0;
		Log::Message(Log::LT_WARNING, "Tried to get the size from a non-array data type.");
		return 0;
	}
	DataVariable Child(void* ptr, const DataAddressEntry& e) override;
};
static DynDef dyn_def;

DataVariable DynDef::Child(void* ptr, const DataAddressEntry& e) {
	J* j = (J*)ptr;
	// an empty Lua table is an empty array (NativeUI maps it so), but read as a struct when a member name is asked for
	if (j->t == J::Arr || (j->t == J::Obj && j->o.empty() && (e.index >= 0 || e.name == "size"))) {
		int size = j->t == J::Arr ? (int)j->a.size() : 0;
		if (e.index < 0 || e.index >= size) {
			if (e.name == "size") return MakeLiteralIntVariable(size);
			Log::Message(Log::LT_WARNING, "Data array index out of bounds.");
			return DataVariable();
		}
		return DataVariable(&dyn_def, &j->a[e.index]);
	}
	if (j->t == J::Obj) {
		if (J* m = j->get(e.name)) return DataVariable(&dyn_def, m);
		Log::Message(Log::LT_WARNING, "Member %s not found in data struct.", e.name.c_str());
		return DataVariable();
	}
	Log::Message(Log::LT_WARNING, "Tried to get the child of a scalar type.");
	return DataVariable();
}

// ---- files by UTF-8 path: RmlUi and the modes pass paths around as UTF-8. Windows opens a narrow path in the ANSI
// code page, which cannot hold every name (a home folder in Cyrillic, say), so there a path goes through the wide API;
// elsewhere a narrow path is UTF-8 already.
static std::filesystem::path u8(const std::string& s) { return std::filesystem::u8path(s); }
class U8Files : public FileInterface {
public:
	FileHandle Open(const String& path) override {
#ifdef _WIN32
		return (FileHandle)_wfopen(u8(path).c_str(), L"rb");
#else
		return (FileHandle)fopen(path.c_str(), "rb");
#endif
	}
	void Close(FileHandle f) override { fclose((FILE*)f); }
	size_t Read(void* buffer, size_t size, FileHandle f) override { return fread(buffer, 1, size, (FILE*)f); }
	bool Seek(FileHandle f, long offset, int origin) override { return fseek((FILE*)f, offset, origin) == 0; }
	size_t Tell(FileHandle f) override { return (size_t)ftell((FILE*)f); }
};
static U8Files u8files;   // every mode: SetFileInterface(&u8files) before Initialise()

// ---- images: RmlUi hands LoadTexture the path joined with the document's (or sheet's) folder, a game-absolute
// "/ui/img/x.png" with its slash stripped. Found relative to the working directory or to any folder above the document
// (the resource root, where the game resolves it); a URL ("nui://...") is taken on trust. Missing: LoadTexture fails
// and RmlUi warns "Could not load texture: <path>", as the game would show nothing.
static std::string docPath;   // the document being checked, set by each mode
static std::string findImage(const std::string& source) {
	namespace fs = std::filesystem;
	std::error_code ec;
	if (fs::is_regular_file(u8(source), ec)) return source;
	if (u8(source).is_absolute()) return "";
	for (fs::path dir = fs::absolute(u8(docPath), ec).parent_path(); !dir.empty(); dir = dir.parent_path()) {
		if (fs::is_regular_file(dir / u8(source), ec)) return (dir / u8(source)).u8string();
		if (dir == dir.parent_path()) break;
	}
	return "";
}
// the natural size from the file's header: PNG, JPEG, TGA; anything else counts as 1x1
static Vector2i imageSize(const std::string& path) {
	std::ifstream f(u8(path), std::ios::binary);
	std::vector<unsigned char> b((std::istreambuf_iterator<char>(f)), std::istreambuf_iterator<char>());
	auto be16 = [&](size_t i) { return int(b[i] << 8 | b[i + 1]); };
	auto be32 = [&](size_t i) { return int(unsigned(b[i]) << 24 | b[i + 1] << 16 | b[i + 2] << 8 | b[i + 3]); };
	if (b.size() >= 24 && !memcmp(b.data(), "\x89PNG", 4)) return {be32(16), be32(20)};
	if (b.size() >= 4 && b[0] == 0xFF && b[1] == 0xD8)
		for (size_t i = 2; i + 9 < b.size() && b[i] == 0xFF;) {
			unsigned char m = b[i + 1];
			if (m >= 0xC0 && m <= 0xCF && m != 0xC4 && m != 0xC8 && m != 0xCC) return {be16(i + 7), be16(i + 5)};
			i += 2 + be16(i + 2);
		}
	std::string ext = path.size() > 4 ? StringUtilities::ToLower(path.substr(path.size() - 4)) : "";
	if (ext == ".tga" && b.size() >= 18) return {b[12] | b[13] << 8, b[14] | b[15] << 8};
	return {1, 1};
}

// ---- null backends
class NullRender : public RenderInterface {
public:
	CompiledGeometryHandle CompileGeometry(Span<const Vertex>, Span<const int>) override { return 1; }
	void RenderGeometry(CompiledGeometryHandle, Vector2f, TextureHandle) override {}
	void ReleaseGeometry(CompiledGeometryHandle) override {}
	TextureHandle LoadTexture(Vector2i& d, const String& source) override {
		if (source.find("://") != String::npos || source.rfind("data:", 0) == 0) { d = {1, 1}; return 1; }
		std::string path = findImage(source);
		if (path.empty()) return 0;
		d = imageSize(path);
		return 1;
	}
	TextureHandle GenerateTexture(Span<const byte>, Vector2i) override { return 1; }
	void ReleaseTexture(TextureHandle) override {}
	void EnableScissorRegion(bool) override {}
	void SetScissorRegion(Rectanglei) override {}
	// layers, filters, shaders, clip masks: accepted and dropped, so drawing gradients, filters and masks raises no
	// "could not compile" noise; what RmlUi itself rejects (an unknown filter, a bad value) is still logged
	void EnableClipMask(bool) override {}
	void RenderToClipMask(ClipMaskOperation, CompiledGeometryHandle, Vector2f) override {}
	void SetTransform(const Matrix4f*) override {}
	LayerHandle PushLayer() override { return ++layers; }
	void CompositeLayers(LayerHandle, LayerHandle, BlendMode, Span<const CompiledFilterHandle>) override {}
	void PopLayer() override { if (layers) layers--; }
	TextureHandle SaveLayerAsTexture() override { return 1; }
	CompiledFilterHandle SaveLayerAsMaskImage() override { return 1; }
	CompiledFilterHandle CompileFilter(const String&, const Dictionary&) override { return 1; }
	void ReleaseFilter(CompiledFilterHandle) override {}
	CompiledShaderHandle CompileShader(const String&, const Dictionary&) override { return 1; }
	void RenderShader(CompiledShaderHandle, CompiledGeometryHandle, Vector2f, TextureHandle) override {}
	void ReleaseShader(CompiledShaderHandle) override {}

private:
	LayerHandle layers = 0;
};
static std::vector<std::string> warnings;
// Render() runs only so decorators and masks load their images. RmlUi's debug asserts on that path concern RmlUi's own
// bookkeeping (box-shadow textures trip one), not the document, and a release build like the game's has none.
static bool rendering = false;
class Sys : public SystemInterface {
public:
	double GetElapsedTime() override { return 0; }
	bool LogMessage(Log::Type type, const String& message) override {
		if (type == Log::LT_ASSERT && rendering) return true;
		if (type <= Log::LT_WARNING) warnings.push_back(message);
		return true;
	}
};
static void renderOnce(Context* context) {
	rendering = true;
	context->Render();
	rendering = false;
}
class NullFont : public FontEngineInterface {};

// ---- a font engine with real advances (layout mode): bin/rml-preview measures the TTFs at 1000 units into fonts.json
// { "<family>|<weight>[|i]": { "ascent", "descent", "def": width, "adv": { "<codepoint>": width or null },
//                              "kern": { "<codepoint>,<codepoint>": adjustment } } }   |i: italic; null: no such glyph
// A face is chosen as RmlUi's own font engine chooses it (FontProvider, FontFamily::GetFaceHandle): the family must be
// loaded and the style (italic or not) must match, else there is no face and RmlUi draws no text ("No font face
// defined"); of those, the nearest weight. A weight other than the one asked for adds a "font face substituted" warning.
// Check mode runs it with one stand-in face for every family (every glyph half an em wide), so text gives its boxes a
// size and a click can hit-test them as in the game.
struct Face {
	std::string key, family;
	int weight = 400;
	bool italic = false;
	float ascent = 930, descent = 346, def = 500;
	std::map<unsigned, float> adv;                       // a negative advance: the font has no such glyph
	std::map<std::pair<unsigned, unsigned>, float> kern;  // legacy kern-table pairs, what FreeType's FT_Get_Kerning reads
};
static std::vector<Face> faces;
struct Handle { int face; int size; FontMetrics m; };
static std::vector<Handle> handles;
static bool standIn = false;
static int faceFor(const std::string& family, int weight, bool italic) {
	if (standIn) return 0;
	int best = -1;
	for (size_t i = 0; i < faces.size(); i++) {
		const Face& f = faces[i];
		if (f.family != family || f.italic != italic) continue;
		if (best < 0 || std::abs(f.weight - weight) < std::abs(faces[best].weight - weight)) best = (int)i;
	}
	if (best >= 0 && faces[best].weight != weight)
		Log::Message(Log::LT_WARNING, "Font face substituted: '%s' %s weight %d is drawn with weight %d, the nearest loaded face.",
		             family.c_str(), italic ? "italic" : "regular", weight, faces[best].weight);
	return best;
}
static std::vector<unsigned> utf8(StringView s) {
	std::vector<unsigned> out;
	const unsigned char* p = (const unsigned char*)s.begin();
	const unsigned char* e = (const unsigned char*)s.end();
	while (p < e) {
		unsigned c = *p++;
		if (c >= 0xF0 && p + 2 < e) { c = ((c & 7) << 18) | ((p[0] & 63) << 12) | ((p[1] & 63) << 6) | (p[2] & 63); p += 3; }
		else if (c >= 0xE0 && p + 1 < e) { c = ((c & 15) << 12) | ((p[0] & 63) << 6) | (p[1] & 63); p += 2; }
		else if (c >= 0xC0 && p < e) { c = ((c & 31) << 6) | (p[0] & 63); p += 1; }
		out.push_back(c);
	}
	return out;
}
class MeasureFont : public FontEngineInterface {
public:
	FontFaceHandle GetFontFaceHandle(const String& family, Style::FontStyle style, Style::FontWeight weight, int size) override {
		int w = (int)weight; if (w == 0) w = 400;
		int f = faceFor(family, w, style == Style::FontStyle::Italic);
		if (f < 0) return 0;
		Handle h{f, size, {}};
		h.m.size = size;
		h.m.ascent = faces[f].ascent * size / 1000.f;
		h.m.descent = faces[f].descent * size / 1000.f;
		h.m.line_spacing = h.m.ascent + h.m.descent;
		h.m.x_height = 0.5f * size;
		h.m.underline_position = 0.1f * size; h.m.underline_thickness = 1;
		h.m.has_ellipsis = false;
		handles.push_back(h);
		return (FontFaceHandle)handles.size();
	}
	FontEffectsHandle PrepareFontEffects(FontFaceHandle, const FontEffectList&) override { return 0; }
	const FontMetrics& GetFontMetrics(FontFaceHandle h) override { return handles[h - 1].m; }
	// RmlUi's sum (FontFaceHandleDefault::GetStringWidth): per glyph its whole-pixel advance (FreeType hints them to the
	// pixel grid), the kerning to the glyph before it, and letter-spacing truncated to whole pixels. Control characters
	// and glyphs the font lacks add nothing. A code point fonts.json did not measure takes the face's default advance.
	int GetStringWidth(FontFaceHandle h, StringView s, const TextShapingContext& ctx, Character prior_character) override {
		Handle& hd = handles[h - 1];
		Face& f = faces[hd.face];
		bool kerning = ctx.font_kerning != Style::FontKerning::None && !f.kern.empty();
		unsigned prior = (unsigned)prior_character;
		int width = 0;
		for (unsigned c : utf8(s)) {
			if (c < 0x20) continue;
			auto it = f.adv.find(c);
			if (it != f.adv.end() && it->second < 0) continue;
			if (kerning) {
				auto k = f.kern.find({prior, c});
				if (k != f.kern.end()) width += (int)std::lround(k->second * hd.size / 1000.f);
			}
			width += (int)std::lround((it != f.adv.end() ? it->second : f.def) * hd.size / 1000.f);
			width += (int)ctx.letter_spacing;
			prior = c;
		}
		return std::max(width, 0);
	}
	int GenerateString(RenderManager&, FontFaceHandle h, FontEffectsHandle, StringView s, Vector2f, ColourbPremultiplied, float, const TextShapingContext& ctx, TexturedMeshList&) override {
		return GetStringWidth(h, s, ctx, Character::Null);
	}
	int GetVersion(FontFaceHandle) override { return 1; }
};

// an element's classes sorted, space-separated: RmlUi's own order follows the order data-class-* bindings were applied
// in, which differs between builds
static std::string classesOf(Element* e) {
	StringList classes;
	StringUtilities::ExpandString(classes, e->GetClassNames(), ' ');
	std::sort(classes.begin(), classes.end());
	std::string out;
	for (auto& c : classes) out += (out.empty() ? "" : " ") + c;
	return out;
}
// tag#id.class1.class2 of an element, as the outline and the click lines name it
static std::string label(Element* e) {
	std::string s = e->GetTagName();
	if (!e->GetId().empty()) s += "#" + e->GetId();
	std::string c = classesOf(e);
	if (!c.empty()) { for (auto& ch : c) if (ch == ' ') ch = '.'; s += "." + c; }
	return s;
}

// ---- what Open77's NativeUI adds to RmlUi 6.3 (the Open77 docs, "NativeUI effects, shapes and themes"), registered so
// RmlUi parses and checks it like its own: the <path>/<shape> paint properties with real parsers, the filters glow,
// chromatic, scanlines, distort and pixelate, and the fx() decorator. They are parsed and then drawn as nothing.
//   fill, stroke                 a colour (or none / currentColor)
//   stroke-width, -dashoffset    a length or number
//   stroke-linejoin / -linecap   miter round bevel / butt round square
//   stroke-dasharray             none, or lengths/numbers separated by spaces or commas ("8 4")
//   trim-start, -end, -offset    a number (0..1)
//   glow(radius color strength)  a length, a colour, a number: glow(6dp #22d8e2 1.2)
//   chromatic(offset angle)  scanlines(strength period speed grain)  distort(amount frequency speed)  pixelate(cell)
//                                plain numbers ("not 3dp", the docs say); the trailing ones may be left out
//   fx(effect a b c d color)     an effect name (built in or Lua-registered), four numbers, a colour
// As in RmlUi's own filters, a later argument may be left out (it takes its default) but never reordered.
class IdentParser : public PropertyParser {   // a CSS identifier: the fx() effect name
public:
	bool ParseValue(Property& property, const String& value, const ParameterMap&) const override {
		if (value.empty() || !(isalpha((unsigned char)value[0]) || value[0] == '_')) return false;
		for (char c : value)
			if (!(isalnum((unsigned char)c) || c == '_' || c == '-')) return false;
		property = Property(value, Unit::STRING);
		return true;
	}
};
class DashArrayParser : public PropertyParser {   // stroke-dasharray: none | <length-or-number>[[,| ]...]
public:
	bool ParseValue(Property& property, const String& value, const ParameterMap&) const override {
		String v = StringUtilities::StripWhitespace(value);
		if (v != "none") {
			StringList parts;
			StringUtilities::ExpandString(parts, StringUtilities::Replace(v, ',', ' '), ' ');
			PropertyParser* len = StyleSheetSpecification::GetParser("number_length_percent");
			int n = 0;
			for (const String& part : parts) {
				if (part.empty()) continue;
				Property p;
				if (!len->ParseValue(p, part, ParameterMap())) return false;
				n++;
			}
			if (n == 0) return false;
		}
		property = Property(v, Unit::STRING);
		return true;
	}
};
class StubFilter : public Filter {
public:
	explicit StubFilter(String name) : name(std::move(name)) {}
	CompiledFilter CompileFilter(Element* element) const override { return element->GetRenderManager()->CompileFilter(name, Dictionary()); }
	String name;
};
class StubFilterInstancer : public FilterInstancer {
public:
	StubFilterInstancer(const char* properties, const char* parsers) {   // "a, b, c" and their parsers, "length|color|number"
		StringList names, kinds;
		StringUtilities::ExpandString(names, properties, ',');
		StringUtilities::ExpandString(kinds, parsers, '|');
		for (size_t i = 0; i < names.size(); i++)
			RegisterProperty(names[i], kinds[i] == "color" ? "white" : "0").AddParser(kinds[i]);
		RegisterShorthand("filter", properties, ShorthandType::FallThrough);
	}
	SharedPtr<Filter> InstanceFilter(const String& name, const PropertyDictionary&) override { return MakeShared<StubFilter>(name); }
};
class StubDecorator : public Decorator {
public:
	DecoratorDataHandle GenerateElementData(Element*, BoxArea) const override { return 1; }
	void ReleaseElementData(DecoratorDataHandle) const override {}
	void RenderElement(Element*, DecoratorDataHandle) const override {}
};
class FxInstancer : public DecoratorInstancer {
public:
	FxInstancer() {
		effect_id = RegisterProperty("effect", "").AddParser("open77_ident").GetId();
		for (const char* n : {"a", "b", "c", "d"}) RegisterProperty(n, "0").AddParser("number");
		RegisterProperty("color", "white").AddParser("color");
		RegisterShorthand("decorator", "effect, a, b, c, d, color", ShorthandType::FallThrough);
	}
	SharedPtr<Decorator> InstanceDecorator(const String&, const PropertyDictionary& properties, const DecoratorInstancerInterface&) override {
		const Property* effect = properties.GetProperty(effect_id);
		if (!effect || effect->Get<String>().empty()) {
			Log::Message(Log::LT_WARNING, "fx() needs the effect name first: fx(effect a b c d color)");
			return nullptr;
		}
		return MakeShared<StubDecorator>();
	}
	PropertyId effect_id;
};
static void registerOpen77() {
	static IdentParser ident;
	static DashArrayParser dashes;
	StyleSheetSpecification::RegisterParser("open77_ident", &ident);
	StyleSheetSpecification::RegisterParser("open77_dasharray", &dashes);
	for (const char* p : {"fill", "stroke"})
		StyleSheetSpecification::RegisterProperty(p, "none", true).AddParser("keyword", "none, currentcolor").AddParser("color");
	StyleSheetSpecification::RegisterProperty("stroke-width", "1dp", true).AddParser("number_length_percent");
	StyleSheetSpecification::RegisterProperty("stroke-dashoffset", "0", true).AddParser("number_length_percent");
	StyleSheetSpecification::RegisterProperty("stroke-linejoin", "miter", true).AddParser("keyword", "miter, round, bevel");
	StyleSheetSpecification::RegisterProperty("stroke-linecap", "butt", true).AddParser("keyword", "butt, round, square");
	StyleSheetSpecification::RegisterProperty("stroke-dasharray", "none", true).AddParser("open77_dasharray");
	StyleSheetSpecification::RegisterProperty("trim-start", "0", false).AddParser("number");
	StyleSheetSpecification::RegisterProperty("trim-end", "1", false).AddParser("number");
	StyleSheetSpecification::RegisterProperty("trim-offset", "0", false).AddParser("number");
	static StubFilterInstancer glow("radius, color, strength", "length|color|number");
	static StubFilterInstancer chromatic("offset, angle", "number|number");
	static StubFilterInstancer scanlines("strength, period, speed, grain", "number|number|number|number");
	static StubFilterInstancer distort("amount, frequency, speed", "number|number|number");
	static StubFilterInstancer pixelate("cell", "number");
	Factory::RegisterFilterInstancer("glow", &glow);
	Factory::RegisterFilterInstancer("chromatic", &chromatic);
	Factory::RegisterFilterInstancer("scanlines", &scanlines);
	Factory::RegisterFilterInstancer("distort", &distort);
	Factory::RegisterFilterInstancer("pixelate", &pixelate);
	static FxInstancer fx;
	Factory::RegisterDecoratorInstancer("fx", &fx);
}

// ---- a case's models: "model" binds under the name given on the command line, "models" adds more by name
static void bindModels(Context* context, J& c, const std::string& defName,
                       const std::function<void(DataModelConstructor&)>& extra = nullptr) {
	auto bindOne = [&](const std::string& name, J* m) {
		DataModelConstructor ctor = context->CreateDataModel(name);
		if (!ctor) badInput("case \"" + c.get("name")->s + "\": the data model '" + name + "' is bound twice (\"model\" binds it under that name too)");
		if (m && m->t == J::Obj)
			for (auto& kv : m->o) ctor.BindCustomDataVariable(kv.first, DataVariable(&dyn_def, &kv.second));
		if (extra) extra(ctor);
	};
	if (J* m = c.get("model")) bindOne(defName, m);
	if (J* ms = c.get("models"))
		for (auto& kv : ms->o) bindOne(kv.first, &kv.second);
}
static Vector2i sizeOf(J& c) {
	if (J* s = c.get("size")) return {(int)num(s->a[0]), (int)num(s->a[1])};
	return {1920, 1080};
}
