---
paths:
  - "twinkly_garland/**"
---
# twinkly_garland (Python 3.12, FastAPI, numpy; image built by `build-twinkly.yml`, aarch64)
- Code in `app/`, tests in `tests/` (plain scripts, no pytest). Run from `twinkly_garland/`: `python tests/test_channels.py`, `test_golden.py`, `test_live.py`, `test_theme.py`, `edge_cases.py`. They need neither Home Assistant nor a garland; `DATA_DIR` is a temp dir.
- Golden frames (`tests/golden/`) must stay byte-identical unless a change is meant to alter frames; say so in the changelog if they change.
- The formula engine is numpy-only; the engine/language/live loop know nothing about channels (`channels.expand` is the single place).
- Persistent files in `/data` (`settings.json`, `formulas.json`, `channels.json`) need a migration that is safe to repeat and keeps a backup.
- This add-on has a long CHANGELOG but no `ARCHITECTURE.md`/`HANDOFF.md` yet; do not invent them unless the task asks.
