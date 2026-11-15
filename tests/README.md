# Suites

`scripts/test.sh` runs every `tests/*.sh` after its built-in steps. One file per area, owned by whoever owns that
area's code: `host.sh`, `rml-check.sh`, `rml-preview.sh`, `lrbind.sh`, `converter.sh`, `fake-nui.sh`, ... Each suite:

- runs from the kit root; `NUIKIT` is the kit root, `NUIKIT_TMP` a fresh empty directory for it alone (never write
  into `$TMPDIR` directly: a stale file from an earlier run must not make a check pass);
- prints one line per check and exits non-zero on any failure;
- proves each check can fail: a mutant (a broken copy in `$NUIKIT_TMP`) per check, each carrying ONE bug, expected
  to turn that check red on its own.
