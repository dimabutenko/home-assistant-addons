# ARCHITECTURE

An ESPHome-equivalent with **no Python and no C++**: a YAML config is validated against JSON schemas, compiled to Rust source, built with Embassy for ESP32-C6 / ESP32-S3, and flashed — all driven from a web builder.

## Repository layout

```text
├── CLAUDE.md  ARCHITECTURE.md  HANDOFF.md
├── docs/tasks/                 # 00-index.md + NN-<slug>.md task specs
├── Cargo.toml                  # Host workspace: crates/builder-engine, crates/builder-server
├── schemas/
│   ├── boards/{esp32c6,esp32s3}.json
│   └── components/{wifi,mqtt,i2c_bus,gpio_switch,gpio_binary_sensor,bme280}.json
├── firmware/                   # Standalone no_std crate (NOT a workspace member)
│   ├── Cargo.toml  build.rs
│   └── src/{main.rs, runtime/, generated.rs}
├── crates/
│   ├── builder-engine/         # lib + CLI: parse, validate, codegen, build, flash
│   └── builder-server/         # Axum REST + /ws log streamer + .bin serving
└── ui/                         # SPA: schema-driven forms, SVG pinout, Web Serial flasher
```

## Layers

### 1. Schemas (`schemas/`) — single source of truth
- **Board schema:** `id`, `chip`, `arch`, Rust `target` triple, Cargo `feature`, pin list. Each pin: `gpio`, `caps` (`input`, `output`, `adc`, `i2c_sda`/`i2c_scl`, `spi`, `uart`, `pwm`, `touch`, …), `flags` (`strapping`, `usb`, `flash`, `reserved`), and `ui` coordinates for the SVG pinout.
- **Component schema:** `id`, `kind` (`platform` | `bus` | `sensor` | `switch` | `binary_sensor` | `network`), `config` (JSON Schema draft 2020-12 for the YAML block), `pins` (named pin roles + required caps), `requires` (e.g. a bus), `provides` (entity type, device class, unit), `firmware` (Rust path/driver crate used by codegen).
- Schemas are consumed by: validator (pin conflicts, capability checks, references), codegen (which Rust to emit), UI (form + pinout rendering).

### 2. Firmware runtime (`firmware/`) — `no_std`, Embassy
- `main.rs`: HAL init (esp-hal), spawner, calls `generated::setup(spawner, peripherals)`.
- `runtime/`: Wi-Fi connect/reconnect/fallback AP; MQTT with Home Assistant Auto-Discovery behind a `HomeAssistantLink` trait (so a native HA API or Matter backend can be added); OTA with two app partitions.
- `generated.rs`: produced by builder-engine; instantiates buses/components/tasks statically.
- State flows through typed channels: `Watch<T>` for latest-value state, `PubSubChannel` for events/commands.

### 3. Codegen / build engine (`crates/builder-engine`)
Pipeline: YAML → typed config → schema validation → board/pin validation → Rust token streams (`quote`) → `prettyplease` → `firmware/src/generated.rs` → `cargo build` (target from board schema) → `.bin` → `espflash`/serve to UI.

### 4. Web builder (`crates/builder-server` + `ui/`)
Axum REST (list schemas, validate, build, download artifacts), WebSocket `/ws` streaming build logs. SPA renders forms from component JSON Schema, draws the SVG pinout from board schema, flashes via Web Serial.

**Server (task 06).** `builder-engine::build` holds the fixed command lines (`plan`: `cargo build --release --target <board.target> --features <board.feature>` in a per-job copy of `firmware/` with the generated `src/generated.rs`, then `espflash save-image --chip <chip> --merge`; no shell, no user arguments), the work-copy preparation and secret redaction (`x-secret` values from the component schemas). `builder-server` only does HTTP, job state and streaming: REST `GET /api/boards|components` (raw schema files), `POST /api/validate|generate|build` (body = YAML, max 256 KiB), `GET /api/jobs/{id}`, `GET /api/jobs/{id}/firmware.bin`; `GET /ws?job=<id>` sends JSON text frames `{"type":"log","line":...}` / `{"type":"status","status":...}` (buffered lines first, ring buffer of 2000 lines, closed after a final status). One build at a time (409 otherwise), last 5 jobs kept, 30-minute timeout. The image is a merged 4 MiB flash image to be written at offset 0x0. Env: `BUILDER_BIND`, `BUILDER_SCHEMAS_DIR`, `BUILDER_WORK_DIR` (jobs + shared cargo target), `BUILDER_FIRMWARE_DIR`, `BUILDER_ESPFLASH`, `BUILDER_UI_DIR` (static UI, default `ui`).

**Web UI (task 07).** `ui/` is a build-less SPA: plain ES modules, no framework, one vendored library (`vendor/esptool-js.js`, esptool-js 0.7.1, Apache-2.0). The server serves it with a minimal static handler (`static_files.rs`, router fallback; no `tower-http`; paths with empty/hidden/`..`/`:`/backslash segments are 404). Pure logic is in `ui/lib/model.js` (schema -> field model, model -> YAML, diagnostic path -> field, secret masking, used pins) and `ui/lib/pinout.js` (board schema -> SVG), covered by `node --test`; DOM code is `ui/app.js`, server calls `ui/lib/api.js` (relative URLs, `ws:`/`wss:` derived from `location`), Web Serial flashing `ui/lib/flash.js`. Field kinds come only from the schema: `x-ref` = select of declared ids, `x-secret` = password input, component `pins` roles = pin inputs with the pinout assign-by-click, `enum`/`boolean`/numbers/strings by `type`; `const` properties (`platform`) are fixed. The model lives in memory only (no `localStorage`); the YAML preview masks `x-secret` values, the real YAML goes only to the API. Merged image is written at offset 0x0 with flash mode/frequency/size `keep`.

## `no_std` invariants (firmware)
1. No heap by default; all long-lived state in `StaticCell`/`static`. **Documented exception:** the Wi-Fi radio driver (`esp-radio`) needs a heap, so `main.rs` installs an 80 KiB `esp-alloc` heap for it; runtime and component code never allocate (heapless buffers only).
2. Component set is fixed at build time; **no dynamic creation at runtime**.
3. No `unwrap()`/`expect()`/panicking index or arithmetic in runtime loops; errors are handled, logged, retried.
4. Inter-task communication only through typed Embassy channels (`Watch`, `PubSubChannel`, `Signal`).
5. Shared I2C/SPI buses via `embassy-embedded-hal` shared-bus wrappers; drivers use `embedded-hal-async`.
6. Chip differences are isolated with cargo features `esp32c6` / `esp32s3` and the board schema, never ad-hoc `cfg`s in components.

## Codegen contract (generated.rs <-> runtime)
Defined in `crates/builder-engine/src/codegen.rs` (module doc); the component schema's `firmware` block drives it:
`module` (runtime module path), `peripherals` (fixed `Peripherals` fields, e.g. `WIFI`), `indexed_peripheral` (family allocated per instance, e.g. `I2C` -> `I2C0`, `I2C1`).
- `<module>::Config` struct; nested objects `<module>::<Prop>Config`; string enums `<module>::<Prop>::<Variant>`; optional properties without a default are `Option<_>`.
- network: `start(spawner, &CONFIG, peripherals..)`; bus: `init(&CONFIG, peripherals.., pins..) -> Bus`; other: generated task -> `run(&CONFIG, pins.., bus refs..).await`.
- Argument order: config, peripherals, pins (by role name, alphabetical), refs (by property name). Pins are passed as `p.GPIOn.into()` (`esp_hal::gpio::AnyPin<'static>`).

## Firmware runtime (as built in task 04)
- Stack: `esp-hal ~1.2` (`unstable`), `esp-rtos 0.4` (`embassy` feature; replaces the old `esp-hal-embassy`), `embassy-executor 0.10`, `embassy-sync 0.8`, `embassy-time 0.5`, `embassy-embedded-hal 0.6`. Chip via cargo features `esp32c6`/`esp32s3`; linker script via `.cargo/config.toml` rustflags.
- `main.rs` starts the RTOS with `TIMG0` + `FROM_CPU_INTR0` (second handle via `clone_unchecked`; no component uses them), then `generated::setup(spawner, p)`.
- `runtime::entity::Registry<T, N>`: fixed array of slots claimed by `(id, aspect)`; each slot has a `Watch` (state) and a `Signal` (command). Switches, binary sensors and BME280 channels publish there; the MQTT/HA link (task 05) consumes them. No per-instance statics are generated.
- **Network (task 05):** `runtime::wifi` = `esp-radio 1.0.0-beta.1` station + `embassy-net` DHCP, reconnect loop, optional fallback AP (station + AP after 3 failed attempts; AP has the static address 192.168.4.1/24 and **no DHCP server**). `runtime::mqtt` = `rust-mqtt 0.6` (MQTT **5** only, static `bump` buffer), QoS 0, retained `online`/`offline` availability (`<prefix>/<device>/status`, last will), state changes collected every 250 ms. `runtime::ha` is transport independent: `HomeAssistantLink` trait, topic layout, Auto-Discovery payloads, `StateTracker` (per-session receivers over the entity registries, so a reconnect republishes every state). Topics: state `<prefix>/<device>/<component>/<object_id>/state`, command `<prefix>/<device>/switch/<id>/set` (`ON`/`OFF`), discovery `<discovery_prefix>/<component>/<device>_<object_id>/config`; sensors use `<id>_<aspect>` as object id. `Slot::describe` carries name / device class / unit from the owning task to the link.
- `runtime::bus::i2c::Bus` = `Mutex<CriticalSectionRawMutex, I2c<Async>>`; devices wrap it with `I2cDevice`. A bus that cannot be created logs and resets the chip (fatal config error).

## Codegen invariants
- Output via `quote!` + `prettyplease::unparse`; no string templates.
- Generated code is deterministic (stable ordering) and contains a "generated, do not edit" header.
- Every validation error carries a YAML path (for UI highlighting).

## Planned (tasks 09�12, not built yet)
- **Boards vs chips (09, 13):** a board schema may inherit a chip-level schema (`chip_base`) and list only the broken-out pins with labels, on-board pins and reserved pins; `board:` in the YAML is a board id. First new board: Seeed XIAO ESP32-C6. New boards are added as schema files (no board-editor UI for now).
- **Secrets (10, 12):** ESPHome-style `!secret name` in the device YAML, resolved by `builder-engine` from a flat `secrets.yaml` in `/data` (managed through `/api/secrets*`, names-only listing, values never logged or put in responses except the raw-file endpoint used by the editor).
- **Editor (11):** the YAML text is the source of truth; `POST /api/parse` (serde_yaml) feeds the visual model; three view modes (Code / Split / Visual).
