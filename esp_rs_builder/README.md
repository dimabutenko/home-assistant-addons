# ESP-RS Builder

A Home Assistant add-on: a visual builder for smart-home firmware on **ESP32-C6 / ESP32-S3**, written in Rust + Embassy (`no_std`). Describe the device in the web UI (components, pins), the YAML is validated against the JSON schemas, compiled to Rust, built, and flashed from your browser.

## Usage
1. Install and start the add-on, open **ESP-RS Builder** from the sidebar (ingress).
2. Choose a board, add components (Wi-Fi, MQTT, I2C bus, GPIO switch/sensor, BME280), assign pins on the pinout.
3. Press **Build**; the log streams live. When it finishes, either **Flash** (Web Serial) or **Download .bin** (a merged image to write at offset `0x0`, e.g. with `espflash write-bin 0x0 firmware.bin`).

## First run
- The first build downloads the firmware's Rust crates (the add-on needs internet access then) and compiles them: **several minutes**. The cargo registry and the build cache live in `/data` (`/data/cargo`, `/data/work`), so later builds are much faster and survive restarts.
- Only one build runs at a time; the last 5 jobs are kept.

## Flashing
- Flashing runs in **your browser** over Web Serial: use Chrome/Edge and open Home Assistant over **HTTPS** (or `localhost`) — Web Serial needs a secure context. Otherwise use **Download .bin** and flash it from a PC.
- The add-on has no access to USB devices and requests no extra privileges.

## Limits
- Only **ESP32-C6** is a verified target. ESP32-S3 needs the Xtensa toolchain (`espup`), which is not in the image, so S3 builds fail.
- Secrets (Wi-Fi/MQTT passwords) are compiled into the firmware you build. They are kept out of the build log, but the last build's firmware and job files stay under `/data/work` (excluded from backups; wiped job folders on restart, the cargo target cache is not).
- The API has no authentication of its own (ingress only): other add-ons on the internal Home Assistant network can reach it. Restricting it to the ingress gateway is a planned hardening.
- The first build is memory hungry (fat LTO); cargo is limited to 2 parallel jobs. On a 2 GB host it may run out of memory or time (30-minute limit).

See `ARCHITECTURE.md` and `docs/tasks/00-index.md` in the source repository for the design. Host CLI (from this folder): `cargo run -p builder-engine -- validate <config.yaml>` and `-- generate <config.yaml>`.
