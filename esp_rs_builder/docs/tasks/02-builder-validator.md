# 02 — Builder validator

## Goal
In `builder-engine`: load schemas, parse a YAML device config, and validate it (schema + board/pin rules), reporting errors with YAML paths.

## Scope
- Schema loading: embed or read `schemas/` (boards + components) into typed structs (`serde`).
- YAML config model: `board`, `name`, top-level component sections (`wifi`, `mqtt`, `i2c`, `switch`, `binary_sensor`, `sensor`).
- Validation:
  1. Component config against its JSON Schema (`jsonschema` crate).
  2. Pin existence on the selected board and required capabilities (`output`, `i2c_sda`, …).
  3. Pin conflicts (same GPIO used twice); warn on `strapping`, error on `flash`/`reserved`/`usb` (unless allowed by schema).
  4. References: e.g. `bme280.i2c_id` must name a declared `i2c_bus`.
- CLI subcommand `builder-engine validate <config.yaml>` with non-zero exit on error.

## Constraints
- Host `std` crate; use `thiserror`/`miette`-style errors with YAML path (no panics on user input).
- No codegen in this task.

## Verification
- `cargo test -p builder-engine` with fixtures: one valid config (C6 + wifi + mqtt + bme280 on i2c) and invalid ones (pin conflict, bad capability, unknown bus ref, schema violation).
- `cargo check --workspace` passes.

## Definition of Done
- Tests pass; error output includes YAML paths; `00-index.md` + `HANDOFF.md` updated.
