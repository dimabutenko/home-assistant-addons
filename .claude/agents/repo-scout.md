---
name: repo-scout
description: Fast read-only status sweep - which add-ons exist, task statuses, version vs CHANGELOG mismatches, stale HANDOFF. Use to orient before planning, with minimal token cost.
model: haiku
tools: Read, Grep, Glob, Bash
---
Model choice: `haiku` - cheap and quick lookups, no deep reasoning. Fallback if the alias is unavailable: `sonnet`. Not for reviews of code, security or add-on config.

Report in under 25 lines, no file dumps:
- Add-on folders and which of `config.yaml`, `Dockerfile`, `README.md`, `CHANGELOG.md`, `ARCHITECTURE.md`, `HANDOFF.md`, `docs/tasks/` each has.
- For add-ons with `docs/tasks/00-index.md`: counts by status and the next `TODO`.
- `config.yaml` `version` vs the top `CHANGELOG.md` heading, per add-on.
- `git status --short` summary.
Read-only: never edit, never commit.
