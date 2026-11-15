// layout: a font engine with real advances (bin/rml-preview measures the TTFs into fonts.json), boxes + text out.
// Per case: { name, els: [box or text run, ...], warnings: [what RmlUi and the font engine warned about] }.
namespace layout {
static std::string fnum(float v) { char b[32]; snprintf(b, 32, "%.1f", v); return b; }
static std::string col(Colourb c) { char b[16]; snprintf(b, 16, "#%02x%02x%02x%02x", c.red, c.green, c.blue, c.alpha); return b; }
static std::string fop(float v) { char b[32]; snprintf(b, 32, "%.3f", v); return b; }
// the scissor region RmlUi draws the element with (ElementUtilities::GetClippingRegion: the padding boxes of the
// ancestors in its offset-parent chain that clip content which overflows them, honouring clip: none/always/N), as
// [x0, y0, x1, y1]; null when nothing clips it
static std::string clipOf(Element* el) {
	Rectanglei r;
	if (!ElementUtilities::GetClippingRegion(el, r)) return "null";
	return "[" + fnum((float)r.Left()) + "," + fnum((float)r.Top()) + "," + fnum((float)r.Right()) + "," + fnum((float)r.Bottom()) + "]";
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
static void emit(Element* el, std::ostringstream& out, bool& first) {
	if (auto* t = rmlui_dynamic_cast<ElementText*>(el)) {
		const auto& cv = t->GetComputedValues();
		Vector2f off = t->GetAbsoluteOffset(BoxArea::Border);
		// each line as RmlUi laid it out and draws it: text-transform is already applied (ASCII only, as in RmlUi)
		for (auto& line : t->GetLines()) {
			if (line.text.empty()) continue;
			out << (first ? "" : ",") << "{\"text\":" << q(line.text) << ",\"x\":" << fnum(off.x + line.position.x) << ",\"y\":" << fnum(off.y + line.position.y)
			    << ",\"w\":" << line.width << ",\"size\":" << fnum(cv.font_size()) << ",\"weight\":" << (int)cv.font_weight()
			    << ",\"family\":" << q(cv.font_family()) << ",\"color\":\"" << col(cv.color()) << "\",\"op\":" << fop(cv.opacity())
			    << ",\"ls\":" << fnum(cv.letter_spacing()) << ",\"italic\":" << (cv.font_style() == Style::FontStyle::Italic ? "true" : "false")
			    << ",\"clip\":" << clipOf(t) << "}";
			first = false;
		}
		return;
	}
	const auto& cv = el->GetComputedValues();
	// RmlUi drops an element that is not visible (display: none or visibility: hidden) from the stacking context with
	// its whole subtree (Element::AddToStackingContext): neither it, its text nor any descendant is drawn, even one
	// that sets visibility: visible again
	if (!el->IsVisible()) return;
	float op = cv.opacity();   // opacity is inherited (not multiplied), and RmlUi draws with the computed value
	Vector2f off = el->GetAbsoluteOffset(BoxArea::Border);
	Vector2f sz = el->GetBox().GetSize(BoxArea::Border);
	{
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
		    << ",\"mask\":" << q(mask) << ",\"deco\":" << q(deco) << ",\"backdrop\":" << q(back) << ",\"clip\":" << clipOf(el);
		if (el->GetTagName() == "path")
			out << ",\"d\":" << q(el->GetAttribute<String>("d", "")) << ",\"viewbox\":" << q(el->GetAttribute<String>("view-box", ""))
			    << ",\"chain\":" << chainOf(el);
		out << "}";
		first = false;
	}
	for (int i = 0; i < el->GetNumChildren(); i++) emit(el->GetChild(i), out, first);
}
int run(const std::string& docPath, const std::string& modelName, const std::string& fontsPath) {
	{
		std::ifstream fj(fontsPath);
		if (!fj) badInput("cannot read " + fontsPath);
		std::string ftxt((std::istreambuf_iterator<char>(fj)), std::istreambuf_iterator<char>());
		J fonts = parseJson(ftxt, fontsPath);
		if (fonts.t != J::Obj) badInput(fontsPath + ": must be an object of faces");
		for (auto& kv : fonts.o) {
			Face f; f.key = kv.first;
			if (kv.second.t != J::Obj) badInput(fontsPath + ": face \"" + kv.first + "\" must be an object");
			if (J* a = kv.second.get("ascent"); isNum(a)) f.ascent = num(*a);
			if (J* d = kv.second.get("descent"); isNum(d)) f.descent = num(*d);
			if (J* d = kv.second.get("def"); isNum(d)) f.def = num(*d);
			if (J* adv = kv.second.get("adv"))
				for (auto& c : adv->o) {
					char* end = nullptr;
					unsigned long cp = strtoul(c.first.c_str(), &end, 10);
					if (c.first.empty() || *end || !isNum(&c.second)) badInput(fontsPath + ": face \"" + kv.first + "\": bad advance \"" + c.first + "\"");
					f.adv[(unsigned)cp] = num(c.second);
				}
			faces.push_back(f);
		}
		if (faces.empty()) badInput(fontsPath + ": no font faces (rml-preview writes one per --font that is not italic)");
	}
	J cases = readCases(Mode::Layout);
	NullRender render; Sys sys; MeasureFont font;
	SetRenderInterface(&render); SetSystemInterface(&sys); SetFontEngineInterface(&font);
	Initialise();
	registerOpen77();
	int n = 0;
	std::cout << "[";
	for (J& c : cases.a) {
		warnings.clear();
		Factory::ClearStyleSheetCache();   // every case parses the sheets again, so their warnings show in each case
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
						e->SetProperty("left", fnum(num(kv.second.a[0])) + "dp");
						e->SetProperty("top", fnum(num(kv.second.a[1])) + "dp");
					}
				}
			context->Update();
			context->Update();
			std::ostringstream out;
			bool first = true;
			emit(doc, out, first);
			std::cout << out.str();
		}
		// what RmlUi (and the font engine) warned about in this case, each message once, in the order first seen
		std::cout << "],\"warnings\":[";
		std::vector<std::string> seen;
		for (auto& w : warnings)
			if (std::find(seen.begin(), seen.end(), w) == seen.end()) {
				std::cout << (seen.empty() ? "" : ",") << q(w);
				seen.push_back(w);
			}
		std::cout << "]}";
		RemoveContext(name);
	}
	std::cout << "]\n";
	Shutdown();
	return 0;
}
}  // namespace layout
