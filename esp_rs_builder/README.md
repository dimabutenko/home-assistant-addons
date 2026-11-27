# ESP-RS Builder

A Home Assistant add-on: a visual builder for smart-home firmware on **ESP32-C6 / ESP32-S3**, written in Rust + Embassy (`no_std`). A YAML config is validated against JSON schemas (`schemas/`), compiled to Rust (`generated.rs`), built and flashed from a web UI.

Status: early development; the add-on server is a stub. See `ARCHITECTURE.md` and `docs/tasks/00-index.md`.

Host CLI (from this folder): `cargo run -p builder-engine -- validate <config.yaml>` and `-- generate <config.yaml>`.
