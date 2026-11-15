namespace check {
// check: load the document (its stylesheets too) with the case's data models, print the warnings and an outline of the
// element tree (tag#id.classes, [none] for display: none, @x,y WxH, inline style, text nodes). Each click is
// dispatched on the first VISIBLE element the selector matches; the model event it must call (name + arguments as text) is
// compared: "CLICK ok" / "CLICK FAIL".
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
	std::string c = el->GetClassNames();
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
	NullRender render; Sys sys; NullFont font;
	SetRenderInterface(&render); SetSystemInterface(&sys); SetFontEngineInterface(&font);
	Initialise();
	int n = 0;
	for (J& c : cases.a) {
		warnings.clear();
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
					for (size_t i = 0; args && i < args->a.size(); i++) want += (i ? "," : "") + args->a[i].s;
					want += ")";
					// the first match the player can see (data-if keeps hidden copies in the tree)
					ElementList list;
					doc->QuerySelectorAll(list, k.get("sel")->s);
					Element* el = nullptr;
					for (Element* e : list) if (e->IsVisible(true)) { el = e; break; }
					fired.clear();
					if (el) { el->Click(); context->Update(); }
					std::string got = fired.empty() ? std::string(el ? "nothing" : "no element") : fired.back();
					std::cout << (got == want ? "CLICK ok   " : "CLICK FAIL ") << k.get("sel")->s << " -> " << got << " (want " << want << ")\n";
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
