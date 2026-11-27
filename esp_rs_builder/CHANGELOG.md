# Changelog

## 0.1.1
- aarch64 only; CI builds natively on an ARM runner (no QEMU); espflash 4.7.0 is the official release binary (SHA256-pinned) instead of a source build.

## 0.1.0
- Add-on packaging: multi-stage image (Debian bookworm) with `builder-server`, the web UI, schemas, firmware sources, a Rust toolchain with the `riscv32imac-unknown-none-elf` target and `espflash` 4.7.0.
- Ingress panel; build cache and cargo registry persist under `/data`; no extra privileges.
- Cargo limited to 2 parallel jobs; `/data/work` and `/data/cargo` are excluded from backups.
- CI workflow publishes the image to ghcr.io (amd64 + arm64).

## 0.0.1
- Skeleton: schemas, config validator and Rust code generator (CLI only); the add-on server is a stub.
