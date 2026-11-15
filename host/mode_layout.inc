// layout: a font engine with real advances (bin/rml-preview measures the TTFs into fonts.json), boxes + text out.
namespace layout {
// ---- a font engine with real advances: tools/rml_preview.py measures the TTFs at 1000 units into fonts.json
// { "<family>|<weight>": { "ascent", "descent", "adv": { "<codepoint>": width }, "def": width } }
struct Face { std::string key; float ascent = 930, descent = 346, def = 500; std::map<unsigned, float> adv; };
static std::vector<Face> faces;
struct Handle { int face; int size; FontMetrics m; };
static std::vector<Handle> handles;
static int faceFor(const std::string& family, int weight) {
	std::string want = family + "|" + std::to_string(weight);
	for (size_t i = 0; i < faces.size(); i++) if (faces[i].key == want) return (int)i;
	for (size_t i = 0; i < faces.size(); i++) if (faces[i].key.rfind(family + "|", 0) == 0) return (int)i;
	return 0;
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
	FontFaceHandle GetFontFaceHandle(const String& family, Style::FontStyle, Style::FontWeight weight, int size) override {
		int w = (int)weight; if (w == 0) w = 400;
		int f = faceFor(family, w);
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
	int GetStringWidth(FontFaceHandle h, StringView s, const TextShapingContext& ctx, Character) override {
		Handle& hd = handles[h - 1];
		Face& f = faces[hd.face];
		float w = 0;
		auto cps = utf8(s);
		for (unsigned c : cps) { auto it = f.adv.find(c); w += (it != f.adv.end() ? it->second : f.def) * hd.size / 1000.f; }
		w += ctx.letter_spacing * cps.size();
		return (int)(w + 0.5f);
	}
	int GenerateString(RenderManager&, FontFaceHandle h, FontEffectsHandle, StringView s, Vector2f, ColourbPremultiplied, float, const TextShapingContext& ctx, TexturedMeshList&) override {
		return GetStringWidth(h, s, ctx, Character::Null);
	}
	int GetVersion(FontFaceHandle) override { return 1; }
};
static std::string fnum(float v) { char b[32]; snprintf(b, 32, "%.1f", v); return b; }
static std::string col(Colourb c) { char b[16]; snprintf(b, 16, "#%02x%02x%02x%02x", c.red, c.green, c.blue, c.alpha); return b; }
static std::string fop(float v) { char b[32]; snprintf(b, 32, "%.3f", v); return b; }
struct Clip { float x0 = -1e9f, y0 = -1e9f, x1 = 1e9f, y1 = 1e9f; };
static std::string clipStr(const Clip& c) {
	return "[" + fnum(c.x0 < -1e8f ? 0 : c.x0) + "," + fnum(c.y0 < -1e8f ? 0 : c.y0) + "," + fnum(c.x1 > 1e8f ? 1920 : c.x1) + "," + fnum(c.y1 > 1e8f ? 1080 : c.y1) + "]";
}
static std::string chainOf(Element* el) {
	std::vector<std::string> parts;
	for (Element* e = el; e; e = e->GetParentNode()) {
		std::string s = e->GetTagName();
		if (!e->GetId().empty()) s += "#" + e->GetId();
		std::string c = e->GetClassNames();
		if (!c.empty()) { for (auto& ch : c) if (ch == ' ') ch = '.'; s += "." + c; }
		parts.push_back(s);
	}
	std::string out = "[";
	for (size_t i = parts.size(); i-- > 0;) out += q(parts[i]) + (i ? "," : "");
	return out + "]";
}
static void emit(Element* el, std::ostringstream& out, bool& first, float, Clip clip) {
	if (auto* t = rmlui_dynamic_cast<ElementText*>(el)) {
		const auto& cv = t->GetComputedValues();
		Vector2f off = t->GetAbsoluteOffset(BoxArea::Border);
		for (auto& line : t->GetLines()) {
			if (line.text.empty()) continue;
			out << (first ? "" : ",") << "{\"text\":" << q(line.text) << ",\"x\":" << fnum(off.x + line.position.x) << ",\"y\":" << fnum(off.y + line.position.y)
			    << ",\"w\":" << line.width << ",\"size\":" << fnum(cv.font_size()) << ",\"weight\":" << (int)cv.font_weight()
			    << ",\"family\":" << q(cv.font_family()) << ",\"color\":\"" << col(cv.color()) << "\",\"op\":" << fop(cv.opacity())
			    << ",\"ls\":" << fnum(cv.letter_spacing()) << ",\"italic\":" << (cv.font_style() == Style::FontStyle::Italic ? "true" : "false")
			    << ",\"clip\":" << clipStr(clip)
			    << ",\"upper\":" << (cv.text_transform() == Style::TextTransform::Uppercase ? "true" : "false") << "}";
			first = false;
		}
		return;
	}
	const auto& cv = el->GetComputedValues();
	if (cv.display() == Style::Display::None) return;
	float op = cv.opacity();   // RmlUi's computed opacity already carries the ancestors'
	Vector2f off = el->GetAbsoluteOffset(BoxArea::Border);
	Vector2f sz = el->GetBox().GetSize(BoxArea::Border);
	if (cv.visibility() == Style::Visibility::Visible) {
		auto& box = el->GetBox();
		std::string mask, deco, back;
		if (auto* pm = el->GetProperty("mask-image")) mask = pm->ToString();
		if (auto* pd = el->GetLocalProperty("decorator")) deco = pd->ToString();
		else if (auto* pd2 = el->GetProperty("decorator")) deco = pd2->ToString();
		if (auto* pb = el->GetProperty("backdrop-filter")) back = pb->ToString();
		out << (first ? "" : ",") << "{\"tag\":" << q(el->GetTagName()) << ",\"id\":" << q(el->GetId()) << ",\"cls\":" << q(el->GetClassNames())
		    << ",\"x\":" << fnum(off.x) << ",\"y\":" << fnum(off.y) << ",\"w\":" << fnum(sz.x) << ",\"h\":" << fnum(sz.y)
		    << ",\"bg\":\"" << col(cv.background_color()) << "\",\"op\":" << fop(op) << ",\"color\":\"" << col(cv.color()) << "\""
		    << ",\"bt\":" << fnum(box.GetEdge(BoxArea::Border, BoxEdge::Top)) << ",\"br\":" << fnum(box.GetEdge(BoxArea::Border, BoxEdge::Right))
		    << ",\"bb\":" << fnum(box.GetEdge(BoxArea::Border, BoxEdge::Bottom)) << ",\"bl\":" << fnum(box.GetEdge(BoxArea::Border, BoxEdge::Left))
		    << ",\"btc\":\"" << col(cv.border_top_color()) << "\",\"brc\":\"" << col(cv.border_right_color()) << "\",\"bbc\":\"" << col(cv.border_bottom_color())
		    << "\",\"blc\":\"" << col(cv.border_left_color()) << "\",\"radius\":" << fnum(cv.border_top_left_radius())
		    << ",\"mask\":" << q(mask) << ",\"deco\":" << q(deco) << ",\"backdrop\":" << q(back) << ",\"clip\":" << clipStr(clip);
		if (el->GetTagName() == "path")
			out << ",\"d\":" << q(el->GetAttribute<String>("d", "")) << ",\"viewbox\":" << q(el->GetAttribute<String>("view-box", ""))
			    << ",\"chain\":" << chainOf(el);
		out << "}";
		first = false;
	}
	if (cv.overflow_x() != Style::Overflow::Visible || cv.overflow_y() != Style::Overflow::Visible) {
		clip.x0 = std::max(clip.x0, off.x); clip.y0 = std::max(clip.y0, off.y);
		clip.x1 = std::min(clip.x1, off.x + sz.x); clip.y1 = std::min(clip.y1, off.y + sz.y);
	}
	for (int i = 0; i < el->GetNumChildren(); i++) emit(el->GetChild(i), out, first, op, clip);
}
int run(const std::string& docPath, const std::string& modelName, const std::string& fontsPath) {
	{
		std::ifstream fj(fontsPath);
		std::string ftxt((std::istreambuf_iterator<char>(fj)), std::istreambuf_iterator<char>());
		P fp{ftxt.c_str()};
		J fonts = fp.val();
		for (auto& kv : fonts.o) {
			Face f; f.key = kv.first;
			if (J* a = kv.second.get("ascent")) f.ascent = a->t == J::Int ? a->i : a->n;
			if (J* d = kv.second.get("descent")) f.descent = d->t == J::Int ? d->i : d->n;
			if (J* d = kv.second.get("def")) f.def = d->t == J::Int ? d->i : d->n;
			if (J* adv = kv.second.get("adv")) for (auto& c : adv->o) f.adv[std::stoul(c.first)] = c.second.t == J::Int ? c.second.i : c.second.n;
			faces.push_back(f);
		}
	}
	std::string input((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
	P parser{input.c_str()};
	J cases = parser.val();
	NullRender render; Sys sys; MeasureFont font;
	SetRenderInterface(&render); SetSystemInterface(&sys); SetFontEngineInterface(&font);
	Initialise();
	int n = 0;
	std::cout << "[";
	for (J& c : cases.a) {
		std::string name = "c" + std::to_string(n);
		Context* context = CreateContext(name, sizeOf(c));
		context->SetDensityIndependentPixelRatio(1.0f);
		bindModels(context, c, modelName);
		ElementDocument* doc = context->LoadDocument(docPath);
		std::cout << (n ? "," : "") << "{\"name\":" << q(c.get("name")->s) << ",\"els\":[";
		n++;
		if (doc) {
			doc->Show();
			context->Update();
			if (J* place = c.get("place"))
				for (auto& kv : place->o) {
					ElementList list;
					doc->QuerySelectorAll(list, kv.first);
					for (Element* e : list) {
						e->SetProperty("left", fnum(kv.second.a[0].t == J::Int ? kv.second.a[0].i : kv.second.a[0].n) + "dp");
						e->SetProperty("top", fnum(kv.second.a[1].t == J::Int ? kv.second.a[1].i : kv.second.a[1].n) + "dp");
					}
				}
			context->Update();
			context->Update();
			std::ostringstream out;
			bool first = true;
			emit(doc, out, first, 1.0f, Clip());
			std::cout << out.str();
		}
		std::cout << "]}";
		RemoveContext(name);
	}
	std::cout << "]\n";
	Shutdown();
	return 0;
}
}  // namespace layout
