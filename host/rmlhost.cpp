// open77-nui-kit: rmlhost (see common.hpp for the modes and the case format)
#include "common.hpp"
#include "mode_parity.inc"
#include "mode_check.inc"
#include "mode_layout.inc"
#ifdef _WIN32
// last: windows.h defines macros (min, max, ...) that RmlUi's names must never meet
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#include <windows.h>
#include <shellapi.h>
#include <fcntl.h>
#include <io.h>
static std::string utf8(const wchar_t* w) {
	int n = WideCharToMultiByte(CP_UTF8, 0, w, -1, nullptr, 0, nullptr, nullptr);
	std::string s(n > 1 ? n - 1 : 0, '\0');
	if (n > 1) WideCharToMultiByte(CP_UTF8, 0, w, -1, &s[0], n, nullptr, nullptr);
	return s;
}
#endif

int main(int argc, char** argv) {
#ifdef _WIN32
	// a crash ends the process at once, with its code, instead of waiting on Windows Error Reporting (a tool running
	// the host would wait with it)
	SetErrorMode(SEM_FAILCRITICALERRORS | SEM_NOGPFAULTERRORBOX | SEM_NOOPENFILEERRORBOX);
#ifdef _MSC_VER
	_set_abort_behavior(0, _CALL_REPORTFAULT);
#endif
	// the same bytes in and out as on every other OS: no \r\n for \n and no ^Z as the end of the input; and the
	// arguments as UTF-8 (main's argv is in the ANSI code page, which cannot hold every path)
	_setmode(_fileno(stdin), _O_BINARY);
	_setmode(_fileno(stdout), _O_BINARY);
	_setmode(_fileno(stderr), _O_BINARY);
	int wargc = 0;
	wchar_t** wargv = CommandLineToArgvW(GetCommandLineW(), &wargc);
	std::vector<std::string> args;
	for (int i = 0; wargv && i < wargc; i++) args.push_back(utf8(wargv[i]));
	// the document path with / only: RmlUi splits a document's path from its name at the last '/' (a \ after it
	// would hide the folders it names, and ../ in an image path would climb from the wrong one)
	if (args.size() > 2) std::replace(args[2].begin(), args[2].end(), '\\', '/');
	std::vector<char*> ptrs;
	for (auto& s : args) ptrs.push_back(&s[0]);
	if (wargv) { argc = wargc; argv = ptrs.data(); }
#endif
	std::string mode = argc > 1 ? argv[1] : "";
	try {
		if (mode == "parity") return parity::run();
		if (mode == "check" && argc == 4) return check::run(argv[2], argv[3]);
		if (mode == "layout" && argc == 5) return layout::run(argv[2], argv[3], argv[4]);
	} catch (const BadInput& e) {
		std::cout.flush();
		std::cerr << "rmlhost: " << e.what() << "\n";
		return 2;
	}
	std::cerr << "usage: rmlhost check <doc.rml> <model> < cases.json\n"
	             "       rmlhost layout <doc.rml> <model> <fonts.json> < cases.json\n"
	             "       rmlhost parity < cases.json\n";
	return 2;
}
