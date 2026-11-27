# HANDOFF

## Status
- **Tasks 01–05 — DONE.** Task 06 spec written (`docs/tasks/06-builder-server-ws.md`), not started.
- Verified this session (Bash with `~/.cargo/bin` on PATH; the PowerShell tool was disabled):
  - `cargo check --features esp32c6` (in `firmware/`) — passes, 0 warnings.
  - `cargo build --features esp32c6` — compiles and **links** (needed `esp-rtos` feature `esp-radio`).
  - `cargo test -p builder-engine` — passes (4 codegen + 8 validator tests); `cargo check --workspace` — passes (only the pre-existing unused-dependency warning in builder-server).
- **Not verified:** anything on real hardware or in the emulator (no board here): joining Wi-Fi, the fallback AP, the MQTT session, Home Assistant discovery and command handling are untested at runtime. `ha.rs` (topic layout, discovery JSON, `ON`/`OFF` parsing) has **no unit tests** (the firmware crate is a `no_std` binary; consider moving the pure parts to a host-testable crate). The BME280 math still has no unit test. ESP32-S3 (needs `espup`) was not built. Heap size (80 KiB) and RAM use were not measured.

## Completed artifacts (task 05)
- `firmware/src/runtime/wifi.rs`: `esp-radio` station + `embassy-net` DHCP stack, reconnect loop (`reconnect_interval_s`), fallback AP (station + AP after 3 failed attempts, static 192.168.4.1/24, no DHCP server), `wifi::stack()` for other tasks.
- `firmware/src/runtime/mqtt.rs`: `rust-mqtt` client task: DNS or IPv4 broker, retained `online`/`offline` (last will) on `<prefix>/<device>/status`, discovery, command subscription, state publishing, ping, reconnect after 5 s.
- `firmware/src/runtime/ha.rs`: `HomeAssistantLink` trait, `Topics`, discovery JSON (`switch`, `binary_sensor` + `device_class`, `sensor` + unit), `StateTracker`, command parsing (`ON`/`OFF`).
- `firmware/src/runtime/entity.rs`: `Slot::{key, meta, describe}`, `Registry::iter`; switch / binary sensor / BME280 call `describe`. `DeviceClass::ha_name` added.
- `main.rs`: `esp_alloc::heap_allocator!(size: 80 * 1024)`.
- Codegen and `generated.rs` / golden file **unchanged** (the existing `start(spawner, &CONFIG[, WIFI])` signatures were enough).
- `ARCHITECTURE.md` updated (heap exception, network layer). `00-index.md`: 05 DONE, 06 spec written.
- Earlier: workspace, `schemas/`, `crates/builder-engine` (validator + codegen + CLI), `crates/builder-server` stub, firmware runtime (task 04).

## Decisions
- **New firmware dependencies (verified on crates.io 2026-11-27):** `esp-radio =1.0.0-beta.1` (features `wifi`, `unstable`, `log-04`; pairs with `esp-hal ~1.2` / `esp-rtos 0.4`; pinned exactly because it is a beta), `esp-alloc 0.11`, `embassy-net 0.9` (`tcp udp dns dhcpv4 medium-ethernet proto-ipv4`), `rust-mqtt 0.6` (`v5 bump log`, no `alloc`), `heapless 0.9`, `embassy-futures 0.1`; `esp-rtos` now also has feature `esp-radio`. Cargo features `esp32c6`/`esp32s3` forward to `esp-radio` and `esp-alloc`.
- **Heap exception:** the Wi-Fi driver needs a heap; `esp-alloc` 80 KiB is installed in `main.rs` and used by the radio only (recorded in ARCHITECTURE).
- **MQTT client:** `rust-mqtt 0.6` supports **only MQTT 5** (its `v3` feature is unused, and building without `v5` fails). Mosquitto 2.x (the HA add-on) supports v5. All publishes are QoS 0; state and discovery are retained.
- **State delivery:** `StateTracker` polls `Watch` receivers every 250 ms (no dynamic multi-future select without a heap); a new session creates new receivers so a reconnect republishes all states.
- `wifi::STA_STACK` is a `static` with `unsafe impl Sync` (embassy-net `Stack` is `!Sync`; sound because the firmware runs one single-core thread-mode executor).
- Fallback AP limitation: no DHCP server and no provisioning page yet (clients need a static IP); the AP stays up until reboot once raised.
- Secrets are not logged (only the SSID / broker host are).
- Earlier decisions still hold (see task 04 notes in git history): per-entity registries instead of generated statics; `clone_unchecked` for `TIMG0` / `FROM_CPU_INTR0`; `Restore` switch mode = off; codegen deps; secrets as plain literals in `generated.rs`; `UPDATE_GOLDEN=1` for the golden file; bus N maps to `I2C<N>` unchecked.
- **Concern (unchanged):** `generated.rs` must not be committed with real credentials; consider env/secrets injection later. The committed sample contains only the fixture's fake credentials.

## Environment notes / blockers
- `cargo` is not on the Git Bash PATH by default: `export PATH="$PATH:/c/Users/Dima/.cargo/bin"` (the PowerShell tool was disabled in the last session). Target `riscv32imac-unknown-none-elf` is installed.
- Board pin data is from memory and still needs a datasheet check.
- The root `CLAUDE.md` shows as modified in `git status` (not by this task); it was left unstaged.
- Task 05 work is committed locally; nothing is pushed (push needs explicit approval).

## Token / context assessment
- Task 06 is a different subsystem (host-side Axum server, no embedded stack): start a **new chat**; re-reading `CLAUDE.md` + `ARCHITECTURE.md` + this file + the spec is cheaper than carrying the Wi-Fi/MQTT research.

## Prompt for next session
```
Work in esp_rs_builder/. Read esp_rs_builder/CLAUDE.md, ARCHITECTURE.md and HANDOFF.md. Tasks 01–05 are DONE. Execute docs/tasks/06-builder-server-ws.md only (follow its Scope/Constraints/Verification; run cargo with ~/.cargo/bin on PATH). When done, update 00-index.md, write docs/tasks/07-web-ui-schemas-and-serial.md, and refresh HANDOFF.md.
```
