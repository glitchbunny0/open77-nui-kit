#!/usr/bin/env bash
# lrbind suite: the parity golden regenerated through rmlhost parity and diffed, lrbind.js parity / page protocol,
# lrbind.lua, the licence headers, the example copy, lrbind-sync, data-rml in Chromium; then one mutant per check.
# The checks and the mutant table live in lrbind/tests/suite.py.
set -euo pipefail
cd "${NUIKIT:?run through scripts/test.sh}"
: "${NUIKIT_TMP:?}"
[ -d lrbind/tests/node_modules/jsdom ] || (cd lrbind/tests && npm ci --silent --no-audit --no-fund)
exec python3 lrbind/tests/suite.py
