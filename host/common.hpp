#pragma once
// open77-nui-kit host: real RmlUi (pinned in scripts/build.sh) with a dynamic, Lua-like data model fed from JSON.
// One binary, three modes:
//   rmlhost check  <doc.rml> <model>              < cases.json   element outline, warnings, real clicks per case
//   rmlhost layout <doc.rml> <model> <fonts.json> < cases.json   boxes + text runs as JSON, laid out with real advances
//   rmlhost parity                                 < cases.json   lrbind parity reference (tree after each step)
// Every case: { name, model: {...}, models?: { other: {...} }, events?: [..], clicks?: [{ sel, event, args }],
// place?: { selector: [left, top] }, size?: [w, h] }. See docs/cases.md.
#include <algorithm>
#include <fstream>
#include <cstring>
#include <RmlUi/Core.h>
#include <RmlUi/Core/DataVariable.h>
#include <RmlUi/Core/ElementText.h>
#include <RmlUi/Core/StyleSheetSpecification.h>
#include <cstdio>
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

struct P {
	const char* p;
	void ws() { while (*p == ' ' || *p == '\n' || *p == '\t' || *p == '\r') p++; }
	std::string str() {
		std::string out;
		p++;
		while (*p && *p != '"') {
			if (*p == '\\') {
				p++;
				switch (*p) {
				case 'n': out += '\n'; break;
				case 't': out += '\t'; break;
				case 'u': {
					unsigned cp = std::stoul(std::string(p + 1, 4), nullptr, 16);
					p += 4;
					if (cp < 0x80) out += char(cp);
					else if (cp < 0x800) { out += char(0xC0 | (cp >> 6)); out += char(0x80 | (cp & 0x3F)); }
					else { out += char(0xE0 | (cp >> 12)); out += char(0x80 | ((cp >> 6) & 0x3F)); out += char(0x80 | (cp & 0x3F)); }
				}
				break;
				default: out += *p;
				}
			}
			else
				out += *p;
			p++;
		}
		p++;
		return out;
	}
	J val() {
		ws();
		J j;
		if (*p == '{') {
			j.t = J::Obj;
			p++;
			ws();
			if (*p == '}') { p++; return j; }
			for (;;) {
				ws();
				std::string k = str();
				ws(); p++;   // :
				j.o.emplace_back(k, val());
				ws();
				if (*p == ',') { p++; continue; }
				p++;
				break;
			}
		}
		else if (*p == '[') {
			j.t = J::Arr;
			p++;
			ws();
			if (*p == ']') { p++; return j; }
			for (;;) {
				j.a.push_back(val());
				ws();
				if (*p == ',') { p++; continue; }
				p++;
				break;
			}
		}
		else if (*p == '"') { j.t = J::Str; j.s = str(); }
		else if (!strncmp(p, "true", 4)) { j.t = J::Bool; j.b = true; p += 4; }
		else if (!strncmp(p, "false", 5)) { j.t = J::Bool; p += 5; }
		else if (!strncmp(p, "null", 4)) { p += 4; }
		else {
			const char* start = p;
			bool frac = false;
			while (*p && strchr("+-0123456789.eE", *p)) { if (strchr(".eE", *p)) frac = true; p++; }
			std::string num(start, p);
			if (frac) { j.t = J::Num; j.n = atof(num.c_str()); }
			else { j.t = J::Int; j.i = atoll(num.c_str()); }
		}
		return j;
	}
};

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
		if (j->t == J::Arr || j->t == J::Obj) return false;
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
	if (j->t == J::Arr || (j->t == J::Obj && j->o.empty())) {
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

// ---- null backends
class NullRender : public RenderInterface {
public:
	CompiledGeometryHandle CompileGeometry(Span<const Vertex>, Span<const int>) override { return 1; }
	void RenderGeometry(CompiledGeometryHandle, Vector2f, TextureHandle) override {}
	void ReleaseGeometry(CompiledGeometryHandle) override {}
	TextureHandle LoadTexture(Vector2i& d, const String&) override { d = {1, 1}; return 1; }
	TextureHandle GenerateTexture(Span<const byte>, Vector2i) override { return 1; }
	void ReleaseTexture(TextureHandle) override {}
	void EnableScissorRegion(bool) override {}
	void SetScissorRegion(Rectanglei) override {}
};
static std::vector<std::string> warnings;
class Sys : public SystemInterface {
public:
	double GetElapsedTime() override { return 0; }
	bool LogMessage(Log::Type type, const String& message) override {
		if (type <= Log::LT_WARNING) warnings.push_back(message);
		return true;
	}
};
class NullFont : public FontEngineInterface {};

// ---- a case's models: "model" binds under the name given on the command line, "models" adds more by name
static void bindModels(Context* context, J& c, const std::string& defName,
                       const std::function<void(DataModelConstructor&)>& extra = nullptr) {
	auto bindOne = [&](const std::string& name, J* m) {
		DataModelConstructor ctor = context->CreateDataModel(name);
		if (m && m->t == J::Obj)
			for (auto& kv : m->o) ctor.BindCustomDataVariable(kv.first, DataVariable(&dyn_def, &kv.second));
		if (extra) extra(ctor);
	};
	if (J* m = c.get("model")) bindOne(defName, m);
	if (J* ms = c.get("models"))
		for (auto& kv : ms->o) bindOne(kv.first, &kv.second);
}
static Vector2i sizeOf(J& c) {
	if (J* s = c.get("size"))
		if (s->t == J::Arr && s->a.size() == 2) return {(int)(s->a[0].t == J::Int ? s->a[0].i : s->a[0].n), (int)(s->a[1].t == J::Int ? s->a[1].i : s->a[1].n)};
	return {1920, 1080};
}
