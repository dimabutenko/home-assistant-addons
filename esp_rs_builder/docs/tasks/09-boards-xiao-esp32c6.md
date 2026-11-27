# 09 — Boards: separate chip from board, add Seeed XIAO ESP32-C6

## Goal
The editor offers real development boards, not only bare chips. After this task the board list contains the existing `esp32c6` / `esp32s3` entries **and** `xiao_esp32c6` (Seeed Studio XIAO ESP32-C6, small 14-pin board) with its own pin labels (`D0`..`D10`), on-board facts (user LED, BOOT button, antenna switch pins) and a pinout drawing that matches the physical board. A config with `board: xiao_esp32c6` validates, generates and builds exactly like a C6 chip config, with the board's pin restrictions applied.

## Scope
- **Schema model:** a board schema gets an optional `chip_base` (id of a chip-level schema, e.g. `esp32c6`) from which `chip`, `arch`, `target`, `feature`, `toolchain`, `flash_tool`, `wifi` and the per-GPIO `caps`/`flags` are inherited; the board file lists only what differs: `label`, `pins[]` (only the GPIOs that are broken out: `gpio`, `label` such as `D4`, optional `aliases`, extra `flags`, `ui` coordinates of *this* board), `onboard[]` (named on-board things, e.g. `{ "id": "user_led", "gpio": 15, "active_low": true }`, `{ "id": "boot_button", "gpio": 9 }`), and `reserved[]` (GPIOs used by the board itself, e.g. RF switch). Decide the exact JSON shape in this task, keep it small, and record it in `ARCHITECTURE.md`.
- `builder-engine`: load/merge in `schema.rs` (`Board` keeps `id`, `chip`, `target`, `feature`, resolved `pins`), the validator accepts a pin only if it is broken out on the board; reserved/on-board pins produce a warning (or error for RF switch pins) via the existing flag mechanism; `board:` in YAML refers to the board id. Existing `esp32c6` / `esp32s3` keep working unchanged (they are chip-level boards).
- `schemas/boards/xiao_esp32c6.json`. Pin facts (Seeed XIAO ESP32-C6, from the Seeed wiki/datasheet — **verify before writing**, e.g. with the `hobby-kit:researcher` agent; do not rely on memory): D0=GPIO0, D1=GPIO1, D2=GPIO2, D3=GPIO21, D4=GPIO22 (SDA), D5=GPIO23 (SCL), D6=GPIO16 (TX), D7=GPIO17 (RX), D8=GPIO19 (SCK), D9=GPIO20 (MISO), D10=GPIO18 (MOSI), user LED GPIO15 (active low), BOOT GPIO9, RF switch GPIO3/GPIO14. Record the source URL in the schema `description` field.
- `ui/`: board `<select>` shows `label`; the pinout draws the board's own pins (`ui` coordinates) with their `label` next to the GPIO number; pin fields accept/show the label (`D4`) — YAML stores the GPIO number (or the label if the validator supports `aliases`; pick one and keep it consistent). Update `ui/lib/pinout.js` and its tests; do not hard-code any XIAO fact in `ui/`.
- Docs: `ARCHITECTURE.md` (board schema section), add-on `README.md` (supported boards).
- **Out of scope:** user-defined boards (task 13), ESP32-S3 boards beyond the existing entry (it already matches the user's S3 DevKit), new components.

## Constraints
- Single source of truth = `schemas/` (add-on `CLAUDE.md`); no board facts in code.
- The firmware crate does not change: board = chip target + pin restrictions only.
- No new dependencies. Everything in English.
- Keep `POST /api/validate|generate|build` request format unchanged (`board:` string).

## Verification
- `cargo test --workspace` (PowerShell or Git Bash with `~/.cargo/bin` on PATH): add tests — XIAO board loads and resolves to the C6 target/feature; a pin that is not broken out (e.g. GPIO12) is an error; `D`-labelled pins map to the right GPIOs; chip-level boards behave as before.
- `cargo clippy --workspace --all-targets` clean.
- `cd ui && node --test test/` and `node --check` on changed `.js`.
- Run `builder-server` locally, `GET /api/boards` lists `xiao_esp32c6`; a YAML with `board: xiao_esp32c6` and a switch on GPIO22 validates and generates.
- **Cannot run here:** browser check of the new pinout drawing; a real flash on a XIAO board. Say so in HANDOFF.

## Definition of Done
- Board schema model implemented and documented; `xiao_esp32c6.json` with verified pins and a source; engine + UI updated; tests pass; `ARCHITECTURE.md`, `README.md`, `CHANGELOG.md` (+ version bump in `config.yaml`, minor) updated; `00-index.md` + `HANDOFF.md` updated; next prompt (task 10) in HANDOFF.
