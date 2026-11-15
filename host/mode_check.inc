namespace check {
// check: load the document (its stylesheets too) with the case's data models and a stand-in font (every family, each
// glyph half an em), print the warnings and an outline of the element tree (tag#id.classes, [none] for display: none, @x,y WxH, inline style, text nodes). Each click is
// dispatched as the player's mouse would: on the first VISIBLE element the selector matches, the pointer moves to its
// centre and presses there. When something else is under the pointer (pointer-events: none on the element, an
// overlay on top) the line says "covered by <that element> at x,y"; a box with no width or height says "zero-size box",
// one whose centre is outside the context "off screen". The model event the click must call
// (name + arguments) is compared: "CLICK ok" / "CLICK FAIL". Arguments are compared as text, each side printed as RmlUi prints the value
// (a JSON 2 and the markup's pick(2) both print 2, true prints 1). A click that bubbles into an ancestor's
// data-event-click calls that event too, as in the game: the click passes only when the wanted event is the one call.
static std::string collapse(const std::string& s) {
	std::string o; bool sp = false;
	for (char c : s) { if (c == ' ' || c == '\n' || c == '\t' || c == '\r') { sp = true; continue; } if (sp && !o.empty()) o += ' '; sp = false; o += c; }
	return o;
}
static void outline(Element* el, int depth, bool hiddenParent) {
	if (auto* t = rmlui_dynamic_cast<ElementText*>(el)) {
		std::string s = collapse(t->GetText());
		if (!s.empty()) std::cout << std::string(depth * 2, ' ') << "\"" << s << "\"\n";
		return;
	}
	bool none = el->GetComputedValues().display() == Style::Display::None;
	std::cout << std::string(depth * 2, ' ') << el->GetTagName();
	if (!el->GetId().empty()) std::cout << "#" << el->GetId();
	std::string c = classesOf(el);
	if (!c.empty()) { std::string d = c; for (auto& ch : d) if (ch == ' ') ch = '.'; std::cout << "." << d; }
	if (none) std::cout << " [none]";
	auto box = el->GetBox();
	Vector2f off = el->GetAbsoluteOffset(BoxArea::Border);
	Vector2f sz = box.GetSize(BoxArea::Border);
	std::cout << " @" << (int)off.x << "," << (int)off.y << " " << (int)sz.x << "x" << (int)sz.y;
	for (auto& kv : el->GetLocalStyleProperties()) std::cout << " {" << StyleSheetSpecification::GetPropertyName(kv.first) << ":" << kv.second.ToString() << "}";
	std::cout << "\n";
	if (none) return;
	for (int i = 0; i < el->GetNumChildren(); i++) outline(el->GetChild(i), depth + 1, none);
}
static std::vector<std::string> fired;
int run(const std::string& docPath, const std::string& modelName) {
	J cases = readCases(Mode::Check);
	faces.assign(1, Face());
	faces[0].ascent = 800, faces[0].descent = 200, faces[0].def = 500;
	standIn = true;
	NullRender render; Sys sys; MeasureFont font;
	SetRenderInterface(&render); SetSystemInterface(&sys); SetFontEngineInterface(&font);
	Initialise();
	registerOpen77();
	int n = 0;
	for (J& c : cases.a) {
		warnings.clear();
		Factory::ClearStyleSheetCache();   // every case parses the sheets again, so their warnings land in each case
		std::string name = "c" + std::to_string(n++);
		Context* context = CreateContext(name, sizeOf(c));
		J* evs = c.get("events");
		bindModels(context, c, modelName, [evs](DataModelConstructor& ctor) {
			if (!evs) return;
			for (J& e : evs->a) {
				std::string en = e.s;
				ctor.BindEventCallback(en, [en](DataModelHandle, Event&, const VariantList& args) {
					std::string sig = en + "(";
					for (size_t i = 0; i < args.size(); i++) sig += (i ? "," : "") + args[i].Get<String>();
					fired.push_back(sig + ")");
				});
			}
		});
		ElementDocument* doc = context->LoadDocument(docPath);
		std::cout << "=== case " << c.get("name")->s << "\n";
		if (!doc) { std::cout << "LOAD FAILED\n"; }
		else {
			doc->Show(); context->Update(); context->Update(); outline(doc, 0, false);
			if (J* clicks = c.get("clicks"))
				for (J& k : clicks->a) {
					std::string want = k.get("event")->s + "(";
					J* args = k.get("args");
					for (size_t i = 0; args && i < args->a.size(); i++) want += (i ? "," : "") + toVariant(args->a[i]).Get<String>();
					want += ")";
					// the first match the player can see (data-if keeps hidden copies in the tree)
					ElementList list;
					doc->QuerySelectorAll(list, k.get("sel")->s);
					Element* el = nullptr;
					for (Element* e : list) if (e->IsVisible(true)) { el = e; break; }
					fired.clear();
					std::string got;
					if (el) {
						// the player's pointer at the element's centre: what is under it there gets the click
						// (pointer-events: none, a zero-size box and an overlay on top all keep it from the target)
						Vector2f off = el->GetAbsoluteOffset(BoxArea::Border);
						Vector2f sz = el->GetBox().GetSize(BoxArea::Border);
						int x = (int)std::floor(off.x + sz.x / 2), y = (int)std::floor(off.y + sz.y / 2);
						std::string at = " at " + std::to_string(x) + "," + std::to_string(y);
						Vector2i dim = context->GetDimensions();
						context->ProcessMouseMove(x, y, 0);
						Element* hit = context->GetHoverElement();
						Element* up = hit;
						while (up && up != el) up = up->GetParentNode();
						if (sz.x <= 0 || sz.y <= 0)
							got = "zero-size box (" + std::to_string((int)sz.x) + "x" + std::to_string((int)sz.y) + ")" + at;
						else if (x < 0 || y < 0 || x >= dim.x || y >= dim.y)
							got = "off screen" + at;
						else if (!up) {
							got = "covered by " + (hit && hit != context->GetRootElement() ? label(hit) : std::string("nothing")) + at;
						}
						else {
							fired.clear();   // what moving there called (mouseover, ...) is not the click's
							context->ProcessMouseButtonDown(0, 0);
							context->ProcessMouseButtonUp(0, 0);
							context->Update();
						}
					}
					// every event the click calls, in dispatch order: the target's first, then each ancestor's as it bubbles
					if (got.empty()) got = fired.empty() ? std::string(el ? "nothing" : "no element") : fired[0];
					for (size_t i = 1; i < fired.size(); i++) got += ", then " + fired[i];
					bool ok = fired.size() == 1 && fired[0] == want;
					std::cout << (ok ? "CLICK ok   " : "CLICK FAIL ") << k.get("sel")->s << " -> " << got << " (want " << want << ")\n";
				}
		}
		std::map<std::string, int> seen;
		for (auto& w : warnings) seen[w]++;
		for (auto& kv : seen) std::cout << "WARN x" << kv.second << ": " << kv.first << "\n";
		RemoveContext(name);
	}
	Shutdown();
	return 0;
}
}  // namespace check
