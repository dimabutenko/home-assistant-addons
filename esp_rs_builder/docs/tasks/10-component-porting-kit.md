# 10 — Component porting kit (ESPHome component -> Rust component, mechanically)

## Goal
Adding a component becomes a small, repeatable job: **one schema file + one firmware module**, no engine, UI or codegen changes. The project is an ESPHome-like builder that emits Rust, so a porter must be able to take an ESPHome component, copy its YAML contract and write (or pull from crates.io) the Rust driver. After this task there is a documented component contract, shared sensor/switch options, a scaffold command, a porting guide, and one **new** component ported with it as proof: `pulse_counter` (the user has a water-flow Hall sensor, 0.5–6 L/min, 2 pcs, and an A3144 Hall module in stock).

## Scope
- **Component contract** (write it down in `ARCHITECTURE.md` and `docs/PORTING.md`): what a component schema must contain (`id`, `kind`, `config`, `pins`, `requires`, `provides`, `firmware`), what the firmware module must expose per kind (network / bus / sensor / switch / binary_sensor / new `output`?), how entities are registered in `runtime::entity::Registry`, naming rules (**use ESPHome key names and `platform:` style wherever the semantics match**, so existing ESPHome YAML is mostly reusable; document deliberate differences).
- **Shared options:** a common base for entities (`name`, `id`, `icon`, `device_class`, `unit_of_measurement`, `accuracy_decimals`, `update_interval`) defined once (e.g. `schemas/common/*.json` with `$ref`/merge support in the engine) instead of copied into every component schema. Refactor the existing six components to use it **without changing their YAML behaviour** (existing tests stay green). `filters` and automations are **out of scope** (task 15).
- **Scaffold:** `builder-engine new-component <id> --kind <sensor|binary_sensor|switch|bus>` writes `schemas/components/<id>.json` and `firmware/src/runtime/<...>/<id>.rs` skeletons from templates (use `quote`/plain JSON; keep the generated Rust to the codegen contract) and prints the remaining manual steps (registering the module and the schema file name in the embedded list).
- **Registration without engine edits:** replace the hand-maintained include list of component schemas (`schema.rs` `include_str!` table) with a build-time or macro-generated list (e.g. `build.rs` scanning `schemas/components/`), so a new schema file is picked up automatically. Same for the firmware module declaration if it can be done without proc-macros; otherwise document the one-line `mod` step.
- **Porting guide `docs/PORTING.md`:** step by step ESPHome -> ours (read the ESPHome component's `CONFIG_SCHEMA`, map keys to JSON Schema, choose a Rust driver: existing `embedded-hal-async` crate from crates.io vs own code, entity registration, update loop), a mapping table (ESPHome concept -> our concept), checklist, and the "driver crates considered" list for the most popular sensors (research, mark unverified items).
- **Proof component `pulse_counter`:** ESPHome `pulse_counter` semantics (pin, `count_mode`, `internal_filter`, `update_interval`, output in pulses/min, `unit_of_measurement` configurable, optional `total` sensor). Implement with the C6 PCNT peripheral through `esp-hal` if available and stable for the pinned version (verify), otherwise an edge-interrupt/`Input::wait_for_*` counter task; say which and why in HANDOFF. Add the schema, the firmware module, a fixture YAML and codegen/validation tests. Flow conversion (pulses -> L/min) stays a user-level setting (`unit_of_measurement`, later `filters: multiply`), do not hard-code the YF-type factor.
- **Out of scope:** `filters`, automations, `lambda` (task 15), importing ESPHome schemas (task 11), UI changes (forms come from schemas automatically; a smoke check only).

## Constraints
- Single source of truth = `schemas/`; `firmware/` stays strict `no_std` (no `unwrap`/panicking indexing in runtime loops, `StaticCell`, typed channels).
- Reuse the codegen contract from task 03/04; if the contract must change, change it in `ARCHITECTURE.md` in the same turn and update the existing components.
- A new dependency (driver crate, `build.rs` helper) is recorded in HANDOFF with the version verified on crates.io.
- Hardware note for the docs: the YF-style flow sensor runs on 5 V; its output must be level-shifted to 3.3 V for the ESP32 (the user has a BSS138 4-channel level shifter). Do not claim hardware verification.

## Verification
- `cargo test --workspace`, `cargo clippy --workspace --all-targets` (PATH with `~/.cargo/bin`).
- `cd firmware && cargo check --release --target riscv32imac-unknown-none-elf --features esp32c6` with a generated file containing `pulse_counter`; if the PCNT API does not fit, document it.
- `builder-engine new-component demo --kind sensor` in a temp copy yields files that compile after the documented manual step, and the schema is picked up with **no** edit in `crates/`.
- `cd ui && node --test test/` still passes (the new schema renders a form through the existing schema -> field model; add it to the all-components test).
- **Cannot run here:** the pulse counter on real hardware (needs the C6 board, the sensor, level shifting).

## Definition of Done
- Contract documented, shared options in use, scaffold and auto-registration working, `docs/PORTING.md` written, `pulse_counter` ported with tests, all green; `ARCHITECTURE.md`, README (component list), `CHANGELOG.md` + minor version bump; `00-index.md` + `HANDOFF.md` updated with the prompt for task 11.
