# CLAUDE.md — Technical rules for the `esp_rs_builder` add-on

> Development flow (tasks, docs-first, handoff) is defined in the repo root `CLAUDE.md`. All paths below are relative to this folder.
> Layout: `crates/`, `firmware/`, `schemas/`, `ui/`, `docs/`, plus the add-on files `config.yaml`, `Dockerfile`, `README.md`, `CHANGELOG.md`.

Project: modular smart-home firmware framework + visual builder on **Rust + Embassy (`no_std`)** for **ESP32-C6** and **ESP32-S3**. See `ARCHITECTURE.md`.

## Embedded Rust & schema-driven invariants
- **Single source of truth = `schemas/`.** Board capabilities (`schemas/boards/*.json`) and component schemas (`schemas/components/*.json`) drive validation, codegen **and** the dynamic UI. Never hard-code component/board facts elsewhere.
- **Strict `no_std` in `firmware/`:** static allocation via `StaticCell`; no dynamic runtime component creation; no `unwrap()`/`expect()`/panicking indexing in runtime loops; typed state/event channels (`embassy_sync::watch::Watch`, `PubSubChannel`); shared I2C/SPI buses through `embassy-embedded-hal` (async bus sharing).
- **Clean codegen:** emit `src/generated.rs` with `quote` + `prettyplease`. No raw string-concatenation templates.
- `firmware/` is a standalone crate excluded from the host workspace; host crates (`crates/*`) use `std`.
- Verification here means `cargo check` / `cargo test` (host workspace) and, for `firmware/`, `cargo check` for the target from the board schema.
