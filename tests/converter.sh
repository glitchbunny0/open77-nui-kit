#!/usr/bin/env bash
# html2rml suite (contract: tests/README.md). Runs from the kit root with NUIKIT and NUIKIT_TMP set.
#  1. unit tests of the value layer and the fixtures (snapshot, rml-check, RmlUi layout where a fixture states it)
#  2. the mutants: one planted bug per check, each must turn its check red on its own
set -uo pipefail
cd "${NUIKIT:-$(cd "$(dirname "$0")/.." && pwd)}"
tmp="${NUIKIT_TMP:?NUIKIT_TMP: a fresh empty dir for this suite}"
fail=0
if out=$(NUIKIT_TMP="$tmp/fixtures" python3 converter/tests/run.py 2>&1); then
    echo "converter fixtures: $(echo "$out" | tail -1)"
else
    echo "$out"; echo "FAIL: converter fixtures"; fail=1
fi
if out=$(NUIKIT_TMP="$tmp/mutants" python3 converter/tests/mutants.py 2>&1); then
    echo "converter $(echo "$out" | tail -1)"
else
    echo "$out" | grep -v '^ok '; echo "FAIL: converter mutants"; fail=1
fi
exit $fail
