# 12 — Secrets UI: secrets editor, `!secret` autocomplete and pickers

## Goal
The user manages secrets from the UI like in ESPHome. A **Secrets** button opens an editor for the secrets file (the raw `name: value` YAML); in the code editor typing `!secret ` offers a completion list of the existing secret names; secret fields in the visual forms (`x-secret`, e.g. the Wi-Fi password) have a picker "use secret…" that writes `!secret <name>`; the YAML preview and logs never show secret values.

## Scope
- **Secrets editor:** a dialog/panel (works in all three view modes of task 13) with a code editor for the secrets YAML (`GET/PUT /api/secrets/file` of task 12); values are masked by default with a "show" toggle; save validates (flat string map) and shows server errors; unsaved-changes warning. A helper to add one secret quickly (name + value) calls `PUT /api/secrets/{name}`.
- **Autocomplete:** in the device YAML editor, after `!secret ` (and on typing `!`) offer the names from `GET /api/secrets` (names only, refreshed after each save of the secrets editor); selecting inserts the name. Unknown secret names get a diagnostic marker (from `/api/validate`, task 12).
- **Forms:** for every `x-secret` field (and string fields, if task 12 allows `!secret` anywhere) show a small control to pick a secret from the list or to create a new one inline; the field then shows `!secret name` (read-only chip with "edit"/"clear"), and the YAML emitter writes the tag. Typing a literal password is still possible, with a hint to prefer a secret.
- **Preview/masking:** existing masking of `x-secret` literals stays; `!secret` references are shown as written (names are not sensitive).
- **First-run hint:** when a config has a literal secret value, show a one-click "move to secrets" action (creates `<component>_<field>` and rewrites the field to `!secret`).
- Docs: `ARCHITECTURE.md` (Web UI section), README (secrets workflow), CHANGELOG + minor version bump.
- **Out of scope:** encryption at rest, import/export of secrets files, multi-user permissions.

## Constraints
- Secret values only travel between the browser and the server over the API and are kept in memory only while the secrets editor is open; never in `localStorage`, URLs or logs.
- Relative URLs (ingress). No board/component facts hard-coded.
- Reuses the editor bundle from task 13; no new dependency unless recorded in HANDOFF.

## Verification
- `cd ui && node --test test/`: pure parts (extract names for completion, "move to secrets" rewrite, emitter writes `!secret x`, masking) and `node --check` on every `.js`.
- `cargo test --workspace` only if the server changes.
- Manual with a browser (say honestly if not run): create a secret in the dialog, complete it in the code editor, pick it in the Wi-Fi password field, build, confirm the log has no value. Edit the raw secrets file and save.

## Definition of Done
- Secrets editor, completion, form picker and "move to secrets" implemented, tests pass, docs/CHANGELOG/version updated, `00-index.md` + `HANDOFF.md` updated (next: none).
