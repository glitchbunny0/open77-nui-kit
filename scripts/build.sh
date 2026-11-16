#!/usr/bin/env bash
# The host build is scripts/build.py (Linux, macOS, Windows; its header lists the settings). This wrapper keeps
# `scripts/build.sh [--host DIR] [--out FILE]` working: it runs build.py with the first Python 3.8+ it finds ($PYTHON,
# python3, python).
for py in "${PYTHON:-}" python3 python; do
    if [ -n "$py" ] && "$py" -c 'import sys; sys.exit(sys.version_info < (3, 8))' >/dev/null 2>&1; then
        exec "$py" "$(dirname "$0")/build.py" "$@"
    fi
done
echo "build.sh: no Python 3.8+ found (tried \$PYTHON, python3, python)" >&2
exit 2
