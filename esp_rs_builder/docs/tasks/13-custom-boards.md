# 13 — User-defined boards (pinout editor)

## Goal
The user can add their own board without changing the add-on: choose a base chip, name the board, list the broken-out pins with labels (and optional restrictions / on-board pins) and get it in the board list and the SVG pinout. Boards are stored under `/data` and survive updates.

## Scope
- **Storage and loading:** `BUILDER_BOARDS_DIR` (default `<data>/boards`, in the image `/data/boards`): `*.json` files using the board schema of task 09 (`chip_base` + pins/onboard/reserved). The registry loads them **in addition to** the embedded schemas; id collisions with shipped boards are rejected; invalid files are reported (not fatal) in `GET /api/boards` as a `problems` list or a separate endpoint.
- **API:** `PUT /api/boards/{id}` (body = board JSON, validated against the board schema and the base chip: every `gpio` exists on the chip, labels unique, `ui` coordinates sane), `DELETE /api/boards/{id}` (user boards only). Size limits.
- **UI:** a "Boards" dialog with a list (shipped = read-only, user = editable) and an editor: base chip select, id/label, a table of pins (GPIO from the chip's list, label, flags) and a simple layout helper that generates `ui` coordinates (two columns left/right, ordered by position) — drag-and-drop layout is optional. A JSON import/export is enough as a fallback. The XIAO ESP32-C6 board from task 09 must be reproducible with this editor (acceptance test).
- Docs: `ARCHITECTURE.md`, README (adding a board), CHANGELOG + minor version bump. `backup_exclude` does not list `/data/boards`.
- **Out of scope:** sharing boards between users, a board gallery, new chips (needs a firmware feature and toolchain).

## Constraints
- Schemas remain the single source of truth; user boards use exactly the shipped board schema (no UI-only fields).
- Files only under `/data`; board JSON never contains secrets; paths from the API are never used as file names without validating `[a-z0-9_]+` ids.
- No new dependencies unless recorded in HANDOFF.

## Verification
- `cargo test --workspace`: load user boards from a temp dir, collision rejected, invalid file reported, PUT/DELETE validation, a user board with `chip_base: esp32c6` validates and builds a plan like the chip board. `cargo clippy --workspace --all-targets`.
- `cd ui && node --test test/` for the pure parts (layout helper, board form model) and `node --check`.
- Manual with a browser (say if not run): recreate the XIAO board, use it in a config, validate.

## Definition of Done
- User boards stored, validated, listed and editable from the UI; tests pass; docs/CHANGELOG/version updated; `00-index.md` + `HANDOFF.md` updated; state that no further task is planned (or the next one).
