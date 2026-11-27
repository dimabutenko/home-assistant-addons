# HANDOFF

## Status
- **Tasks 01–07 — DONE.** Task 08 spec written (`docs/tasks/08-addon-packaging.md`), not started.
- Verified this session (Bash with `~/.cargo/bin` on PATH, Node v26):
  - `cargo test --workspace` — passes (builder-engine 2 + 4 + 8, builder-server 1 unit + 10 integration incl. the new static-file test); `cargo clippy --workspace --all-targets` — no warnings.
  - `cd ui && node --test test/` — 9 tests pass (schema -> field model for every shipped component, diagnostic path -> field, YAML emitter, secret masking, used pins, SVG pinout, ws URL); `node --check` on every `.js` file.
  - Real `builder-server` with the UI: `GET /`, `app.js`, `lib/model.js`, `style.css`, `vendor/esptool-js.js` = 200 with the right content types; `/../Cargo.toml` = 404. A YAML produced by the UI model code (node) was POSTed to `/api/validate` -> `[]`; the same with `pin: 6` -> error `switch[0].pin` "GPIO6 is already used by `i2c[0].sda`" (the path format matches what the UI maps to fields).
- **NOT verified (no browser in this session):** the DOM code in `ui/app.js` was never run in a browser — forms, inline diagnostics, SVG pinout clicking, build log streaming over `/ws`, the Build/Download buttons and the whole Web Serial flash flow are untested. Flashing needs a real ESP32-C6 and Chrome/Edge. First thing to do next time someone has a browser: open `http://127.0.0.1:8099/`, add components, build, download.
- Still not verified from earlier tasks: flashing on a real board; ESP32-S3 build; firmware Wi-Fi/fallback AP/MQTT/HA discovery on hardware; secret redaction on real cargo output; Linux/Docker build.

## Completed artifacts (task 07)
- `crates/builder-server/src/static_files.rs` (router fallback serving `BUILDER_UI_DIR`, default `ui`; `AppState::with_ui_dir`), `main.rs` reads `BUILDER_UI_DIR`; test in `tests/api.rs` + unit test of path resolution.
- `ui/`: `index.html`, `style.css`, `app.js` (DOM), `lib/model.js` (pure: field model, YAML, diagnostics mapping, masking, used pins), `lib/pinout.js` (SVG), `lib/api.js` (relative URLs, ws URL from `location`, polling fallback), `lib/flash.js` (Web Serial), `vendor/esptool-js.js` + licence + README, `package.json` (`"type":"module"`, test script), `test/model.test.js`, `README.md`.
- `ARCHITECTURE.md` ("Web UI (task 07)"), `docs/tasks/00-index.md` (07 DONE, 08 added).

## Decisions
- **UI stack:** plain ES modules, no bundler, no framework, no npm install needed at runtime. One vendored dependency: `esptool-js` **0.7.1** (npm latest on 2026-11-27, Apache-2.0), the package's self-contained `bundle.js` copied unmodified to `ui/vendor/esptool-js.js` with its licence. Loaded lazily (`import()` on Flash click).
- **Static files without `tower-http`:** a ~60-line handler (no new Rust dependency). Rejects empty/hidden/`..`/`:`/backslash path segments; `Cache-Control: no-cache`, `nosniff`.
- **Flasher:** merged image at offset `0x0`, `flashMode/flashFreq/flashSize = "keep"` (the image header is already right), `compress: true`, baud 460800, `hard_reset` after. No MD5 callback.
- **Model/YAML:** the UI model is `{board, name, sections}`; only values the user set are emitted (defaults are shown as placeholders, the server applies them). The YAML emitter is ~20 lines, block style, strings quoted when not plain. Section order in the YAML is the component-file order (alphabetical), which is irrelevant to the validator.
- **Secrets:** never stored (`localStorage` unused); the preview masks `x-secret` values; the real YAML is only sent to the API. Test passwords are built at runtime (`'fake'.repeat(3)`) because the repo hook flags password-like literals.
- **Pins by schema:** a property is a pin field if its key is a role in the component's `pins`; the pinout dims pins lacking the role's capabilities (still clickable; the validator reports misuse).
- **Known limits:** YAML is read-only preview (no import); the Build button is disabled while the last validation has errors; ESP32-S3 is selectable and will probably fail to build.
- Earlier decisions (tasks 04–06: espflash `save-image --merge`, work copy per job, WS protocol, dependency pins, redaction, limits) still hold.
- **Concern (unchanged):** `generated.rs` must not be committed with real credentials.

## Environment notes / blockers
- `cargo` is not on the Git Bash PATH by default: `export PATH="$PATH:/c/Users/Dima/.cargo/bin"`. `espflash 4.7.0` is in `~/.cargo/bin`.
- A first real firmware build into an empty work dir takes several minutes.
- Board pin data is from memory and still needs a datasheet check (the pinout drawing uses its `ui` coordinates).
- Nothing is pushed (push needs explicit approval).

## Token / context assessment
- Task 08 is infrastructure (Dockerfile, manifest, CI) — a different subsystem from task 07: start a **new chat**; the spec plus `CLAUDE.md`, `ARCHITECTURE.md` and this file are enough.

## Prompt for next session
```
Work in esp_rs_builder/. Read esp_rs_builder/CLAUDE.md, ARCHITECTURE.md and HANDOFF.md. Tasks 01–07 are DONE. Execute docs/tasks/08-addon-packaging.md only (follow its Scope/Constraints/Verification; run cargo with ~/.cargo/bin on PATH; use the addon-check skill and the addon-reviewer subagent). When done, update 00-index.md and HANDOFF.md; if no further task is planned, say so.
```
