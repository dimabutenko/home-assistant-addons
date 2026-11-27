# HANDOFF

## Status
- **Tasks 01–08 — DONE; no further task is planned.** (Task 08 = add-on packaging, version 0.1.0.)
- Verified: `cargo test --workspace` passes; the server run locally with `BUILDER_UI_DIR` serves `/`, `api/boards`, `style.css` (200). The UI uses relative URLs and a `location`-derived `ws:`/`wss:` URL, so it is ingress-prefix safe by inspection only (no real ingress run).
- **NOT verified: Docker is not installed here.** `docker build`, running the image, a real build inside it (`/data/work`), the CI workflow, and installation on the real Home Assistant were never run. Do not treat the image as working until the first CI build and a first on-HA build succeed. Also unverified: `/data` mounted without `noexec` (cargo runs build scripts from `/data/work/target`), memory/time of the first build on aarch64, GHCR package visibility (new packages are private; make it public or the pull fails).
- Still unverified from earlier tasks: DOM code of the UI in a browser, Web Serial flashing on a real ESP32-C6, ESP32-S3 build, firmware Wi-Fi/MQTT on hardware.
- Review: `addon-reviewer` run; fixes applied (see below). Not committed yet.

## Completed artifacts (task 08)
- `Dockerfile` (3 stages), `run.sh`, `.dockerignore`, `.gitattributes` (LF for sh/Dockerfile), `config.yaml` (0.1.0, `image:`, watchdog `/api/boards`, `backup_exclude`), `CHANGELOG.md`, `README.md`, `.gitignore` (`work/`), `.github/workflows/build-esp-rs-builder.yml` (amd64+arm64 to ghcr, gha cache, concurrency), `.claude/skills/addon-check/reference.md` row updated.

## Decisions (task 08)
- **Base image `rust:1.100.0-slim-bookworm`** (Debian/glibc): rustup, espflash and firmware build scripts are tested on glibc; musl unverified. Toolchain = that stable version (the firmware has no `rust-toolchain` file; 1.100.0 is what it was verified with). Target `riscv32imac-unknown-none-elf` added with `rustup`.
- **espflash 4.7.0 built from source** (`cargo install --locked --no-default-features --features cli`; no `update-check`, so no runtime network use) rather than a release binary: works for both arches from one Dockerfile. Needs `libudev1` at runtime.
- **Env:** `RUSTUP_HOME` in the image, `CARGO_HOME=/data/cargo`, `BUILDER_WORK_DIR=/data/work`, `CARGO_BUILD_JOBS=2` (fat-LTO memory). No extra privileges; `init` left at default (tini, signals/zombie reaping, per review).
- **Image published to ghcr** (`ghcr.io/dimabutenko/ha-addon-esp-rs-builder`) like the other add-ons: installs fail until CI has pushed the first image.
- No new Rust dependencies.

## Known limitations / follow-ups (no task yet)
- API has no auth; reachable by other add-ons on the hassio network (and they could download firmware with credentials). Hardening: accept only 172.30.32.2 + loopback (axum `ConnectInfo`). Documented in README.
- The last build ELF (with compiled-in credentials) stays in `/data/work/target`; excluded from backups only.
- Build timeout kills only `cargo`, not its children.
- CI rebuilds on any `esp_rs_builder/**` change (also docs).

## Environment notes / blockers
- `cargo` is not on the Git Bash PATH by default: `export PATH="$PATH:/c/Users/Dima/.cargo/bin"`. `espflash 4.7.0` is in `~/.cargo/bin`.
- A first real firmware build into an empty work dir takes several minutes.
- Board pin data is from memory and still needs a datasheet check (the pinout drawing uses its `ui` coordinates).
- Nothing is pushed (push needs explicit approval).

## Token / context assessment
- No next task is planned; the next step is for the user: review, commit approval, push (needs explicit approval), let CI build the image, install on Home Assistant, then try the UI in a browser. Open a new chat for any hardening work.

## Prompt for next session
None: all planned tasks (01–08) are done. If hardening is wanted, create a new task spec first (e.g. API peer-IP allowlist).
