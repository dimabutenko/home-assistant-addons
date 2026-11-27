# HANDOFF

## Status
- **Tasks 01–04 — DONE.** Task 05 spec written (`docs/tasks/05-firmware-net-and-ha.md`), not started.
- Verified this session (PowerShell, from `firmware/` and the add-on root):
  - `cargo check --features esp32c6` — passes, 0 warnings.
  - `cargo build --features esp32c6` — compiles and **links**.
  - `cargo test -p builder-engine` — passes (4 codegen + 8 validator tests); `cargo check --workspace` — passes (only the pre-existing unused-dependency warning in builder-server).
- **Not verified:** anything on real hardware or in the emulator (no board here); the BME280 compensation math was written from the datasheet and has no unit test; ESP32-S3 (needs `espup`) was not built.

## Completed artifacts (task 04)
- `firmware/Cargo.toml` (deps pinned, features `esp32c6`/`esp32s3`), `firmware/.cargo/config.toml` (target + linker flags), `firmware/build.rs`, `firmware/src/main.rs`.
- `firmware/src/generated.rs` = output of `builder-engine generate crates/builder-engine/tests/fixtures/valid_c6.yaml` (sample; contains the fixture's fake credentials only).
- `firmware/src/runtime/`: `entity.rs` (slot registry), `bus/i2c.rs`, `gpio/{switch,binary_sensor}.rs`, `drivers/bme280.rs`, `wifi.rs` + `mqtt.rs` (stubs).
- Earlier tasks: workspace, `schemas/`, `crates/builder-engine` (validator + codegen + CLI `validate` / `generate`), `crates/builder-server` stub.

## Decisions
- **Firmware dependencies (verified on crates.io 2026-11-27):** `esp-hal ~1.2` (feature `unstable`), `esp-rtos 0.4` (`embassy`), `esp-bootloader-esp-idf 0.6`, `esp-println 0.18` (`log-04`), `esp-backtrace 0.20` (`panic-handler`, `println`), `log 0.4`, `embassy-executor 0.10`, `embassy-time 0.5`, `embassy-sync 0.8`, `embassy-embedded-hal 0.6`, `embedded-hal-async 1.0`, `static_cell 2.1`. `esp-hal-embassy` is obsolete (replaced by `esp-rtos`); the task spec's "executor 0.9" became 0.10 — the generated `if let Ok(token) = task(..) { spawner.spawn(token); }` and `p.GPIOn.into()` compile unchanged, so **codegen and its golden file did not change**.
- Per-entity state/commands live in `runtime::entity::Registry` slots keyed `(id, aspect)`, not in generated statics (keeps the codegen contract unchanged). Task 05 needs an enumeration API there.
- `main.rs` takes second handles to `TIMG0` / `FROM_CPU_INTR0` with `clone_unchecked` (generated code never uses them).
- `i2c::init` resets the chip on an invalid bus config (contract returns `Bus`, not `Result`).
- `Restore` switch mode behaves as always-off (logged) until persistent storage exists.
- Earlier decisions (codegen deps `quote`/`proc-macro2`/`prettyplease`/`syn`, `generate` returns `Result`, secrets as plain literals in `generated.rs`, golden regeneration with `UPDATE_GOLDEN=1`, bus N maps to `I2C<N>` unchecked — a 2nd bus on C6 will not compile) still hold; see git history of this file if needed.
- **Concern:** `generated.rs` must not be committed with real credentials; consider env/secrets injection (task 05+).

## Environment notes / blockers
- Use PowerShell with `%USERPROFILE%\.cargo\bin` on PATH (`cargo` is not on the Git Bash PATH). The `riscv32imac-unknown-none-elf` target was installed with `rustup target add` this session.
- Board pin data is from memory and still needs a datasheet check.
- Task 04 work is committed locally (not pushed).

## Token / context assessment
- This session loaded the Rust embedded stack (dependency resolution, many compiler messages). Task 05 (Wi-Fi/MQTT/HA) is a different, heavier subsystem with new crates to research: start a **new chat** — re-reading `CLAUDE.md` + `ARCHITECTURE.md` + this file + the spec is cheaper than carrying this history.

## Prompt for next session
```
Work in esp_rs_builder/. Read esp_rs_builder/CLAUDE.md, ARCHITECTURE.md and HANDOFF.md. Tasks 01–04 are DONE. Execute docs/tasks/05-firmware-net-and-ha.md only (follow its Scope/Constraints/Verification; run cargo via PowerShell). When done, update 00-index.md, write docs/tasks/06-builder-server-ws.md, and refresh HANDOFF.md.
```
