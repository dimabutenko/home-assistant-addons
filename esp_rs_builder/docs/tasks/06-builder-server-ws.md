# 06 — Builder server: REST API and `/ws` build log

## Goal
Turn the `builder-server` stub into an Axum server that exposes the builder-engine over HTTP: list schemas, validate a YAML config, generate `generated.rs`, run the firmware build as a background job and stream its log over a WebSocket (`/ws`). Serving the built `.bin` is included; the web UI itself is task 07.

## Scope
- `crates/builder-server`: Axum (+ `tokio`, `serde`, `serde_json`, `tower-http` for static files / CORS if needed). Bind address and port from env (`BUILDER_BIND`, default `0.0.0.0:8099`), schemas via the existing `BUILDER_SCHEMAS_DIR` / embedded registry.
- REST (JSON):
  - `GET /api/boards`, `GET /api/components` — the loaded schemas (as in `Registry`; add `Serialize` where needed).
  - `POST /api/validate` — body = YAML text; response = list of `Diagnostic` (with YAML paths), HTTP 200 even for invalid configs.
  - `POST /api/generate` — validate then return the generated Rust source (HTTP 422 with diagnostics when invalid).
  - `POST /api/build` — validate, write `firmware/src/generated.rs` into a **per-job work copy** (not the shared source tree), start `cargo build` for the board's `target`/`feature` as a background job; returns a job id. One job at a time (HTTP 409 while busy).
  - `GET /api/jobs/{id}` — status (`queued|running|succeeded|failed`) and the artifact name; `GET /api/jobs/{id}/firmware.bin` — the built image (ELF -> bin conversion step is part of this task: pick `espflash save-image` vs `esptool`-free option and record the decision in HANDOFF).
- `GET /ws` — WebSocket: a client subscribes to a job id and receives its stdout/stderr lines as text frames plus a final status frame; late subscribers get the buffered log first (bounded ring buffer, no unbounded memory).
- Engine calls stay in `builder-engine` (add a small `build` module there for the cargo invocation); the server only does HTTP, job state and streaming.

## Constraints
- Host-only `std` code; the firmware crate is untouched.
- The server never executes anything but the fixed `cargo` command line built from the board schema (no user-supplied arguments, no shell). Reject YAML larger than 256 KiB.
- Secrets (Wi-Fi/MQTT passwords) must not be written to the log stream or to the response of `/api/generate` for logging purposes; the generated file lives only in the job work directory and is deleted with the job (keep the last N jobs).
- Every new dependency is pinned and recorded in HANDOFF (verify versions on crates.io first). Remove the pre-existing unused-dependency warning of builder-server by actually using `builder-engine`.
- Only ESP32-C6 builds have to work.

## Verification
- From the add-on root (PowerShell or Bash with `~/.cargo/bin` on PATH): `cargo check --workspace`, `cargo test -p builder-engine`, `cargo test -p builder-server`.
- Server tests (`tower::ServiceExt::oneshot`): `/api/validate` with the valid and an invalid fixture, `/api/generate` golden-equals the engine output, 409 on a second concurrent build, 422 on invalid YAML. The real `cargo build` job may be replaced by a fake command in tests; run one real C6 build manually and say so in HANDOFF.
- WebSocket: a test that connects, receives the buffered lines and the final status frame.

## Definition of Done
- Server compiles, tests pass, a manual `curl` flow (validate -> build -> download `.bin`) is described in HANDOFF with what was and was not run; `00-index.md` + `HANDOFF.md` updated; task 07 (web UI: schema-driven forms, SVG pinout, Web Serial flasher) spec drafted.
