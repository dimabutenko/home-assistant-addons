# 05 — Firmware: Wi-Fi, MQTT and Home Assistant discovery

## Goal
Replace the `wifi` and `mqtt` stubs in `firmware/src/runtime/` with working implementations: the device joins Wi-Fi (reconnects, optional fallback AP), connects to the MQTT broker, publishes Home Assistant MQTT Auto-Discovery for every entity in the `runtime::entity` registries, publishes state changes and applies switch commands.

## Scope
- `runtime/wifi.rs`: `start(spawner, &Config, WIFI)` spawns a connection task: `esp-radio` Wi-Fi (check the crate that pairs with `esp-hal ~1.2` / `esp-rtos 0.4` first), `embassy-net` DHCP stack, reconnect every `reconnect_interval_s`, optional fallback AP from `fallback_ap` when the station cannot connect.
- `runtime/mqtt.rs`: `start(spawner, &Config)` spawns a client task (pick a `no_std` async MQTT client and record it in HANDOFF); LWT availability topic `<topic_prefix>/<device>/status`.
- `runtime/ha.rs` behind a `HomeAssistantLink` trait (ARCHITECTURE): discovery payloads for `switch`, `binary_sensor` (+ `device_class`), `sensor` (temperature / humidity / pressure units), state topics from `Watch`, command topic -> `SWITCHES` slot `command` signal. Build payloads without heap (fixed `heapless`/`core::fmt` buffers).
- Entity names/ids come from the component configs; the registries need a way to enumerate registered entries (`Registry::iter` or a name table) — add it in `entity.rs` if missing.
- If the generated `start(...)` signatures need more peripherals/arguments, fix codegen + golden file in this task.

## Constraints
- Strict `no_std`, no heap (CLAUDE.md); no `unwrap()`/`expect()`/panicking indexing in runtime loops; typed channels only.
- Secrets (Wi-Fi/MQTT passwords) stay out of logs.
- Every new dependency is pinned and recorded in HANDOFF (verify versions on crates.io first).
- Only ESP32-C6 must build.

## Verification
- From PowerShell in `firmware/`: `cargo check --features esp32c6`; ideally `cargo build --features esp32c6` (links).
- `cargo test -p builder-engine` and `cargo check --workspace` from the add-on root.
- Real-device behaviour (join Wi-Fi, appear in HA) cannot be verified without hardware: state it plainly in HANDOFF if not tested.

## Definition of Done
- Firmware crate checks (and links) for C6 with real Wi-Fi/MQTT/HA code; `00-index.md` + `HANDOFF.md` updated; task 06 spec (builder-server REST + `/ws`) drafted.
