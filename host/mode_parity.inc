// parity: the lrbind reference. Input: the cases of lrbind/tests/parity/cases.mjs on stdin; output: golden.json.
namespace parity {
// ---- serialising the tree the way the JS side does
static std::string collapse(const std::string& s) {
	std::string o;
	bool sp = false;
	for (char c : s) {
		if (c == ' ' || c == '\n' || c == '\t' || c == '\r') { sp = true; continue; }
		if (sp && !o.empty()) o += ' ';
		sp = false;
		o += c;
	}
	return o;
}

static void dump(Element* el, std::ostringstream& out) {
	if (auto* t = rmlui_dynamic_cast<ElementText*>(el)) {
		out << "{\"text\":" << q(collapse(t->GetText())) << "}";
		return;
	}
	out << "{\"tag\":" << q(el->GetTagName());
	std::map<std::string, std::string> attrs;
	for (auto& kv : el->GetAttributes()) {
		const String& k = kv.first;
		if (k.rfind("data-", 0) == 0 || k == "class" || k == "style" || k == "rmlui-inner-rml") continue;
		attrs[k] = kv.second.Get<String>();
	}
	out << ",\"attrs\":{";
	bool first = true;
	for (auto& kv : attrs) { out << (first ? "" : ",") << q(kv.first) << ":" << q(kv.second); first = false; }
	out << "}";
	StringList classes;
	StringUtilities::ExpandString(classes, el->GetClassNames(), ' ');
	std::sort(classes.begin(), classes.end());
	out << ",\"classes\":[";
	for (size_t i = 0; i < classes.size(); i++) out << (i ? "," : "") << q(classes[i]);
	out << "]";
	std::map<std::string, std::string> styles;
	for (auto& kv : el->GetLocalStyleProperties()) styles[StyleSheetSpecification::GetPropertyName(kv.first)] = kv.second.ToString();
	out << ",\"style\":{";
	first = true;
	for (auto& kv : styles) { out << (first ? "" : ",") << q(kv.first) << ":" << q(kv.second); first = false; }
	out << "},\"children\":[";
	first = true;
	for (int i = 0; i < el->GetNumChildren(); i++) {
		Element* c = el->GetChild(i);
		if (auto* t = rmlui_dynamic_cast<ElementText*>(c))
			if (collapse(t->GetText()).empty()) continue;
		if (!first) out << ",";
		dump(c, out);
		first = false;
	}
	out << "]}";
}

static J* walk(J* root, const std::string& path) {
	// "a.b[2].c" (0-based) inside the model object
	J* cur = root;
	std::string tok;
	size_t i = 0;
	auto member = [&](const std::string& name) { cur = cur ? cur->get(name) : nullptr; };
	while (i < path.size()) {
		char c = path[i];
		if (c == '.') { if (!tok.empty()) member(tok); tok.clear(); i++; }
		else if (c == '[') {
			if (!tok.empty()) member(tok);
			tok.clear();
			size_t close = path.find(']', i);
			int idx = std::stoi(path.substr(i + 1, close - i - 1));
			cur = (cur && cur->t == J::Arr && idx < (int)cur->a.size()) ? &cur->a[idx] : nullptr;
			i = close + 1;
		}
		else { tok += c; i++; }
	}
	if (!tok.empty()) member(tok);
	return cur;
}

int run() {
	std::string input((std::istreambuf_iterator<char>(std::cin)), std::istreambuf_iterator<char>());
	P parser{input.c_str()};
	J cases = parser.val();

	NullRender render;
	Sys sys;
	NullFont font;
	SetRenderInterface(&render);
	SetSystemInterface(&sys);
	SetFontEngineInterface(&font);
	Initialise();

	std::cout << "[";
	int n = 0;
	for (J& c : cases.a) {
		warnings.clear();
		std::string name = "c" + std::to_string(n);
		Context* context = CreateContext(name, {1920, 1080});
		J* model = c.get("model");
		std::vector<std::string> calls;
		DataModelConstructor ctor = context->CreateDataModel("m");
		for (auto& kv : model->o) ctor.BindCustomDataVariable(kv.first, DataVariable(&dyn_def, &kv.second));
		if (J* ev = c.get("events"))
			for (J& e : ev->a) {
				std::string en = e.s;
				ctor.BindEventCallback(en, [&calls, en](DataModelHandle, Event&, const VariantList& args) {
					std::string s = en + "(";
					for (size_t i = 0; i < args.size(); i++) s += (i ? "," : "") + args[i].Get<String>();
					calls.push_back(s + ")");
				});
			}
		DataModelHandle handle = ctor.GetModelHandle();
		std::string rml = "<rml><head></head>" + c.get("rml")->s + "</rml>";
		ElementDocument* doc = context->LoadDocumentFromMemory(rml);
		std::cout << (n ? "," : "") << "{\"name\":" << q(c.get("name")->s) << ",\"snapshots\":[";
		if (!doc) { std::cout << "],\"error\":\"load failed\"}"; n++; continue; }
		doc->Show();
		context->Update();
		auto snap = [&](bool comma) {
			std::ostringstream out;
			dump(doc, out);
			std::cout << (comma ? "," : "") << "{\"dom\":" << out.str() << ",\"calls\":[";
			for (size_t i = 0; i < calls.size(); i++) std::cout << (i ? "," : "") << q(calls[i]);
			std::cout << "],\"warnings\":[";
			for (size_t i = 0; i < warnings.size(); i++) std::cout << (i ? "," : "") << q(warnings[i]);
			std::cout << "]}";
			calls.clear();
			warnings.clear();
		};
		snap(false);
		if (J* steps = c.get("steps"))
			for (J& s : steps->a) {
				if (J* path = s.get("set")) {
					std::string root = path->s.substr(0, path->s.find_first_of(".["));
					if (J* target = walk(model, path->s)) *target = *s.get("value");
					handle.DirtyVariable(root);
				}
				if (J* id = s.get("event")) {
					Element* el = doc->GetElementById(id->s);
					Dictionary params;
					if (J* ps = s.get("params"))
						for (auto& kv : ps->o) params[kv.first] = kv.second.t == J::Str ? Variant(kv.second.s) : Variant(kv.second.t == J::Int ? (double)kv.second.i : kv.second.n);
					if (el) el->DispatchEvent(s.get("type")->s, params);
				}
				context->Update();
				snap(true);
			}
		std::cout << "]}";
		RemoveContext(name);
		n++;
	}
	std::cout << "]\n";
	Shutdown();
	return 0;
}
}  // namespace parity
