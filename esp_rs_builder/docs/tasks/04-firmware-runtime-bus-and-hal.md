# 04 — Firmware runtime: bus and HAL

## Goal
Make `firmware/` a real `no_std` Embassy crate for ESP32-C6 that **compiles** together with `src/generated.rs` produced from `crates/builder-engine/tests/fixtures/valid_c6.yaml`: runtime modules for the I2C bus, GPIO switch / binary sensor and BME280, with Wi-Fi/MQTT as compiling stubs.

## Scope
- Pin and record in HANDOFF the firmware dependencies: `esp-hal` (1.x), `esp-rtos`/`esp-hal-embassy` (whichever is current for it), `embassy-executor` (0.9: `spawner.spawn(token)`, tasks return `Result<SpawnToken, _>`), `embassy-time`, `embassy-sync`, `embassy-embedded-hal`, `embedded-hal-async`, `static_cell`, a logging crate (`defmt` or `esp-println`), a panic handler. Verify versions and the `AnyPin: From<GPIOn>` API against the real crates first.
- `firmware/Cargo.toml` features `esp32c6` / `esp32s3` (names from the board schema `feature`), `build.rs`, `.cargo/config.toml` with the target from the board schema. Only C6 must build now; S3 needs `espup` (document, do not require).
- `firmware/src/main.rs`: HAL init, Embassy start, `generated::setup(spawner, peripherals).await`.
- Copy the codegen output to `firmware/src/generated.rs` with `builder-engine generate crates/builder-engine/tests/fixtures/valid_c6.yaml` (committed as a sample so the crate builds standalone).
- `firmware/src/runtime/` — implement exactly the surface the generated code calls (see ARCHITECTURE "Codegen contract"):
  - `bus::i2c`: `Config { id, frequency_hz }`, `Bus` = shared-bus mutex over async I2C (`embassy-embedded-hal`), `init(&Config, I2C0, scl: AnyPin, sda: AnyPin) -> Bus` (note: **scl before sda**, alphabetical role order).
  - `gpio::switch`: `Config`, `RestoreMode`, `run(&Config, AnyPin)`; state in a `Watch<bool>`, commands via a `Signal`/`PubSubChannel`.
  - `gpio::binary_sensor`: `Config`, `Pull`, `DeviceClass`, `run(&Config, AnyPin)` with debounce; publishes to a `Watch<bool>`.
  - `drivers::bme280`: `Config`, `TemperatureConfig`/`HumidityConfig`/`PressureConfig`, `run(&Config, &'static Bus)`; async driver over `embedded-hal-async`; publishes to `Watch<f32>`s.
  - `wifi` / `mqtt`: `Config` (+ `FallbackApConfig`), `start(...)` as **stubs** (log and return); real implementation is task 05.
- If the generated signatures turn out wrong for the HAL (e.g. peripheral lifetimes, `start` needing more peripherals), fix the codegen + its golden file in the same task, not the runtime workaround.

## Constraints
- Strict `no_std`, no heap, `StaticCell`/`static` only; no `unwrap()`/`expect()`/panicking indexing in runtime loops; typed channels only (CLAUDE.md §4).
- Chip differences only via cargo features / board schema; no ad-hoc `cfg` in components.
- Do not add dependencies beyond the list above without recording them in HANDOFF.

## Verification
- `cd firmware && cargo check --target riscv32imac-unknown-none-elf --features esp32c6` passes (state plainly in HANDOFF if the toolchain/target is missing and what was not verified).
- `cargo test -p builder-engine` and `cargo check --workspace` still pass (golden file updated if codegen changed).

## Definition of Done
- Firmware crate checks for C6 with the sample `generated.rs`; `00-index.md` + `HANDOFF.md` updated; task 05 (Wi-Fi + MQTT + HA discovery) spec drafted.
