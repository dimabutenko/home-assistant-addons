# HANDOFF

## Status
- **Tasks 01–06 — DONE.** Task 07 spec written (`docs/tasks/07-web-ui-schemas-and-serial.md`), not started.
- Verified this session (Bash with `~/.cargo/bin` on PATH):
  - `cargo check --workspace` — passes, **0 warnings** (the old unused-dependency warning is gone).
  - `cargo test --workspace` — passes: builder-engine 2 unit + 4 codegen + 8 validator; builder-server 9 integration tests.
  - **One real C6 build through the server:** `builder-server` started with `BUILDER_BIND=127.0.0.1:8099`, `BUILDER_WORK_DIR` in a temp folder, then `curl` -> `POST /api/validate` (`[]`) -> `POST /api/build` (`{"id":"1"}`) -> polled `GET /api/jobs/1` until `succeeded` -> `GET /api/jobs/1/firmware.bin` = HTTP 200, 4 194 304 bytes (first byte `0xE9`), using the fixture `valid_c6.yaml`. The build log over `/ws` was **not** watched during that real run (covered only by the fake-runner test).
- **Not verified:** flashing that image on a real ESP32-C6 (no board); ESP32-S3 build (needs `espup`); the redaction of secrets in real cargo/rustc output was only tested with a fake command; the build was run on Windows only (Linux/Docker not tried). Firmware items from task 05 are still untested on hardware (Wi-Fi, fallback AP, MQTT, HA discovery); `ha.rs` and the BME280 math have no unit tests.

## Completed artifacts (task 06)
- `crates/builder-engine/src/build.rs`: `plan()` (cargo + espflash steps, fixed argument lists), `prepare_work_copy()` (copies `firmware/` without `target/`, writes `src/generated.rs`), `secrets()` / `redact()` (values of `x-secret` properties), 2 unit tests.
- `schema.rs`: `Board.raw` / `Component.raw` keep the schema file as written (the UI needs fields like pin `ui` coordinates); `Diagnostic` / `Severity` are `Serialize`.
- `crates/builder-server`: `lib.rs` (router + handlers + WebSocket), `jobs.rs` (job store, ring buffer, broadcast), `runner.rs` (`Runner` trait, `CargoRunner`, `run_steps`), `main.rs` (env config), `tests/api.rs`.
- API as in `ARCHITECTURE.md` ("Server (task 06)"). `/api/validate` always 200 with a diagnostic array (unparsable YAML = one error with empty path); `/api/generate` and `/api/build` give 422 with the diagnostic array; build returns 202 `{"id"}`, 409 while busy; YAML > 256 KiB = 413. WebSocket is `GET /ws?job=<id>` (unknown job = 404 before upgrade), JSON text frames.
- `ARCHITECTURE.md` updated; `00-index.md`: 06 DONE, 07 spec written.

## Decisions
- **ELF -> image:** `espflash save-image --chip esp32c6 --merge <elf> <bin>` (an installed `espflash` binary, path via `BUILDER_ESPFLASH`; installed here with `cargo install espflash --version 4.7.0 --locked`). `--merge` gives a full 4 MiB flash image (bootloader + partition table + app) that the browser flasher writes at offset `0x0`. The Docker image of the add-on will have to install `espflash` (packaging task).
- **New dependencies (crates.io checked 2026-11-27):** builder-server: `axum 0.8.9` (features `http1 tokio ws json query`, no defaults), `tokio 1.54.1` (`rt-multi-thread macros process sync io-util net time fs`), `serde 1.0.229`, `serde_json 1.0.154`. Dev only: `tower 0.5.3` (`util`), `http-body-util 0.1.5`, `tokio-tungstenite 0.29.0` (same version axum uses), `futures-util 0.3.34`. No `tower-http` (static files are task 07). builder-engine: no new dependencies. The `Cargo.toml` versions are caret requirements; `Cargo.lock` pins them.
- **Per-job work copy + shared target dir:** every job gets a copy of `firmware/` under `<BUILDER_WORK_DIR>/jobs/<id>`; the cargo target dir `<BUILDER_WORK_DIR>/target` is shared between jobs (build cache), safe because only one build runs at a time. Job directories are removed when more than 5 jobs exist and at server start.
- **WebSocket protocol:** subscription by query `?job=<id>`; every frame is JSON text (`log` / `status`); the client receives buffered lines, then the current status, then live events; the socket closes after a final status. Tests use a fake `Runner` (the trait is the seam), plus `run_steps` with `cargo --version`.
- **Secrets:** `generated.rs` exists only in the job directory; build output lines (and the echoed command line) are passed through `redact()` which replaces every `x-secret` value with `***`. Nothing logs the YAML or the generated source. The `/api/generate` response does contain the credentials the caller sent (it is the caller's own data).
- **Limits:** log ring buffer 2000 lines (lines cut at 4 KiB), broadcast lag shows "N lines skipped", build timeout 30 min (process is killed on drop).
- Earlier decisions still hold (task 04/05 notes: `esp-radio` beta pin, MQTT 5 only, heap exception, polling `StateTracker`, no DHCP server on the fallback AP, `Restore` switch mode = off, secrets as plain literals in `generated.rs`, `UPDATE_GOLDEN=1` for the golden file).
- **Concern (unchanged):** `generated.rs` must not be committed with real credentials; the committed sample has only the fixture's fake ones.

## Environment notes / blockers
- `cargo` is not on the Git Bash PATH by default: `export PATH="$PATH:/c/Users/Dima/.cargo/bin"`. Target `riscv32imac-unknown-none-elf` is installed; `espflash 4.7.0` is now in `~/.cargo/bin`.
- A first real build into an empty work dir compiles all firmware dependencies (several minutes); later builds reuse the shared target dir.
- Board pin data is from memory and still needs a datasheet check.
- `twinkly_garland/app/live.py` shows as modified in `git status` (not by this task); it was left alone.
- Task 06 work is **not committed yet** and nothing is pushed (push needs explicit approval).

## Token / context assessment
- Task 07 is a different subsystem (browser UI, JavaScript, no Rust): start a **new chat**; the spec plus `CLAUDE.md`, `ARCHITECTURE.md` and this file are enough context.

## Prompt for next session
```
Work in esp_rs_builder/. Read esp_rs_builder/CLAUDE.md, ARCHITECTURE.md and HANDOFF.md. Tasks 01–06 are DONE. Execute docs/tasks/07-web-ui-schemas-and-serial.md only (follow its Scope/Constraints/Verification; run cargo with ~/.cargo/bin on PATH for the server side). When done, update 00-index.md, write the next task spec (add-on packaging: config.yaml, Dockerfile, ingress), and refresh HANDOFF.md.
```
