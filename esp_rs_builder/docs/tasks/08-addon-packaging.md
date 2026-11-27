# 08 — Add-on packaging: config.yaml, Dockerfile, ingress

## Goal
Make `esp_rs_builder` installable and usable as a Home Assistant add-on: one image that contains `builder-server`, the web UI, the schemas, the firmware sources, a Rust toolchain for the ESP32-C6 target and `espflash`, reachable through the HA ingress panel, with all persistent state under `/data`.

## Scope
- `Dockerfile` (replaces the placeholder): multi-stage. Stage 1 builds `builder-server` in release mode. The final image has: the binary, `schemas/`, `ui/` (without `ui/test` and `node_modules`), `firmware/` (without `target/`), a Rust toolchain with the `riscv32imac-unknown-none-elf` target (installed with `rustup`, pinned to the toolchain the firmware needs — check `firmware/rust-toolchain.toml` / the HANDOFF notes), a C linker (`gcc`/`build-base`) for host build scripts, and `espflash` **4.7.0** (`cargo install --locked` in a build stage, or a pinned release binary — record the choice). Decide the base image (Debian slim is the safer default for `rustup` + `espflash`; Alpine/musl only if verified) and say why in HANDOFF.
- `config.yaml`: keep `ingress: true`, `ingress_port: 8099`; add `ingress_entry`/`panel_*` as needed; **no** extra privileges (no `host_network`, no `uart`/`usb`, no `full_access`: flashing happens in the user's browser). `map:` nothing. Options: none, or only a documented, non-secret one (e.g. a log level). Bump `version` (minor) and add a `CHANGELOG.md` entry in the same change.
- Runtime environment in the image: `BUILDER_BIND=0.0.0.0:8099`, `BUILDER_SCHEMAS_DIR`, `BUILDER_FIRMWARE_DIR`, `BUILDER_UI_DIR` pointing at the copied folders, `BUILDER_ESPFLASH=/usr/local/bin/espflash`, **`BUILDER_WORK_DIR=/data/work`** (job copies + shared cargo target = build cache that survives restarts), `CARGO_HOME` and `RUSTUP_HOME` set so the toolchain is read-only in the image and the cargo registry cache goes under `/data` (so firmware dependencies are downloaded once). Startup script (`run.sh`, or direct `CMD`): create `/data/work` and start `builder-server`.
- Ingress check: the UI uses relative URLs and a `location`-derived WebSocket URL (task 07); verify the server works behind the ingress prefix (static files, `/api/*`, `/ws` upgrade) and add a short note on the **secure-context** requirement of Web Serial (HA must be opened over HTTPS or `localhost`; otherwise use "Download .bin").
- CI: update the workflow path filter / build matrix for this add-on if the repository has one (use the `addon-check` skill); keep `.dockerignore` so `target/`, `firmware/target/`, `ui/node_modules/` and `work/` are not sent to the Docker context.
- `README.md` (add-on): what it does, first-run notes (first build downloads firmware dependencies and takes minutes; later builds use the cache), the limits (ESP32-C6 only verified; S3 needs `espup`, not in the image), how to flash.

## Constraints
- Minimal privileges (repo rule `addon-manifest.md`); no secrets in the image, `config.yaml` or logs; the add-on stores only under `/data`.
- The image must not need a network at **runtime** except what `cargo` needs to fetch firmware crates on the first build (document it); do not add dependencies without recording them in HANDOFF.
- Keep the version in `config.yaml` and the top entry of `CHANGELOG.md` in sync.
- Work only inside `esp_rs_builder/`.

## Verification
- `addon-check` skill: manifest keys, version vs CHANGELOG, Dockerfile, CI path filter.
- If Docker is available: `docker build` for `linux/amd64`, run the image with a temporary `/data` volume, `curl` `/`, `/api/boards`, then one real C6 build through `POST /api/build` (as in task 06) and check that `/data/work` is populated. If Docker is **not** available here, say so in HANDOFF and do not claim the image builds.
- On the real Home Assistant (read-only access per the root `CLAUDE.md`): confirm the add-on appears after the repository refresh only if the user has pushed; otherwise leave it for the user.

## Definition of Done
- `Dockerfile`, `config.yaml`, `CHANGELOG.md`, `README.md`, `.dockerignore` (and CI filter if present) updated and consistent; verification results recorded honestly in HANDOFF; `00-index.md` + `HANDOFF.md` updated; a review with the `addon-reviewer` subagent (privileges, `/data`, ingress) done before commit.
