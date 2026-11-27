# 03 — Builder codegen

## Goal
In `builder-engine`: turn a *validated* device config into `firmware/src/generated.rs` using `quote` + `prettyplease` (no string templates), deterministically.

## Scope
- Add deps (record in HANDOFF): `quote`, `proc-macro2`, `prettyplease`, `syn` (with `full`, for `parse2` -> `syn::File`).
- Typed IR between validation and codegen: `DeviceModel { board, name, components: Vec<ComponentModel> }` built from the validated YAML (reuse `validate` internals; expose a `load_and_validate(reg, yaml) -> Result<DeviceModel, Report>`).
- `codegen::generate(&DeviceModel, &Registry) -> String`:
  - header comment "generated, do not edit" + the board id; stable ordering (by yaml key, then declaration order);
  - `pub async fn setup(spawner: Spawner, p: Peripherals)` that statically instantiates (via `StaticCell`) the wifi/mqtt config, each I2C bus, and each component, spawning one task per component;
  - GPIO numbers map to `peripherals.GPIOn` tokens; chip differences only via the board schema `feature`, never ad-hoc `cfg`.
  - Config strings emitted as `&'static str` constants; secrets (`x-secret`) are emitted like any value for now (note the concern in HANDOFF).
- CLI: `builder-engine generate <config.yaml> [-o firmware/src/generated.rs]` (refuses to run if validation has errors).
- Firmware runtime types referenced by the output (`runtime::...`) need NOT exist yet; the output is only parsed (`syn::parse_file`), not compiled, in this task.

## Constraints
- No raw string-concatenated Rust; all output through `quote!`, formatted by `prettyplease::unparse`.
- Deterministic output (snapshot-testable); no timestamps.
- Do not touch `firmware/` code other than writing the generated file; do not implement runtime modules.

## Verification
- `cargo test -p builder-engine`: golden test — `tests/fixtures/valid_c6.yaml` -> `tests/fixtures/valid_c6.generated.rs`; output re-parses with `syn::parse_file`; two runs are byte-identical; generation is refused for an invalid config.
- `cargo check --workspace` passes.

## Definition of Done
- Tests pass; CLI `generate` works; `00-index.md` + `HANDOFF.md` updated; task 04 spec drafted if the runtime API surface referenced by the generated code is now known.
