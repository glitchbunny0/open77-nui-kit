// open77-nui-kit: rmlhost (see common.hpp for the modes and the case format)
#include "common.hpp"
#include "mode_parity.inc"
#include "mode_check.inc"
#include "mode_layout.inc"

int main(int argc, char** argv) {
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
