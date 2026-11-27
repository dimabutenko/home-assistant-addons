# 01 — Workspace and schemas

## Goal
Create the repository skeleton, host Cargo workspace, and the initial board/component JSON schemas.

## Scope
- Directory structure per `ARCHITECTURE.md` (incl. `firmware/`, `ui/` placeholders).
- Root `Cargo.toml` (workspace: `crates/builder-engine`, `crates/builder-server`; `firmware` excluded).
- Minimal crate skeletons for both host crates; standalone `firmware/Cargo.toml` with features `esp32c6`, `esp32s3`.
- `schemas/boards/{esp32c6,esp32s3}.json`; `schemas/components/{wifi,mqtt,i2c_bus,gpio_switch,gpio_binary_sensor,bme280}.json`.
- Root `.gitignore` (`target/`).

## Constraints
- No real logic yet; no firmware dependencies pinned (done in task 04 once verified against crates.io).
- Schemas are JSON; component `config` is JSON Schema 2020-12.

## Verification
- `cargo check --workspace` passes.
- All schema files parse as JSON.

## Definition of Done
- All files above exist; verification passes; `00-index.md` and `HANDOFF.md` updated.
