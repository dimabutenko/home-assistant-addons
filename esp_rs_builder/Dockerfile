# ESP-RS Builder add-on image.
# Target: aarch64 only (Raspberry Pi 5). Base: Debian bookworm (glibc): rustup, espflash and the cargo build scripts of the firmware crates are
# tested upstream on glibc; Alpine/musl was not verified. Toolchain tag pinned to the version the
# firmware was verified with (rustc 1.100.0, stable channel, no rust-toolchain file).
ARG RUST_IMAGE=rust:1.100.0-slim-bookworm

# --- Stage 1: builder-server (release) ---
FROM ${RUST_IMAGE} AS server
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY crates/ crates/
COPY schemas/ schemas/
RUN cargo build --release --locked -p builder-server

# --- Stage 2: espflash 4.7.0 (official release binary, aarch64, SHA256-pinned; no compile) ---
FROM ${RUST_IMAGE} AS espflash
ARG ESPFLASH_SHA256=3158e1c78f3e80ad0389c1d925b69736e1955a60b3cadf932e6d0d74d731b448
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip \
 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL -o /tmp/espflash.zip https://github.com/esp-rs/espflash/releases/download/v4.7.0/espflash-aarch64-unknown-linux-gnu.zip \
 && echo "${ESPFLASH_SHA256}  /tmp/espflash.zip" | sha256sum -c - \
 && unzip /tmp/espflash.zip espflash -d /opt/espflash \
 && chmod +x /opt/espflash/espflash

# --- Final image ---
FROM ${RUST_IMAGE}
# gcc (already in the slim base) links host build scripts of the firmware dependencies; libudev1: runtime lib of espflash
RUN apt-get update \
 && apt-get install -y --no-install-recommends gcc libc6-dev libudev1 ca-certificates \
 && rm -rf /var/lib/apt/lists/* \
 && rustup target add riscv32imac-unknown-none-elf

LABEL org.opencontainers.image.source=https://github.com/dimabutenko/home-assistant-addons
COPY --from=server /src/target/release/builder-server /usr/local/bin/builder-server
COPY --from=espflash /opt/espflash/espflash /usr/local/bin/espflash
COPY schemas/ /opt/esp_rs_builder/schemas/
COPY ui/ /opt/esp_rs_builder/ui/
COPY firmware/ /opt/esp_rs_builder/firmware/
COPY run.sh /run.sh
RUN chmod +x /run.sh

# Toolchain stays in the image (RUSTUP_HOME); the cargo registry/git cache and the build
# cache (BUILDER_WORK_DIR/target) live under /data and survive restarts.
ENV RUSTUP_HOME=/usr/local/rustup \
    CARGO_HOME=/data/cargo \
    CARGO_BUILD_JOBS=2 \
    BUILDER_BIND=0.0.0.0:8099 \
    BUILDER_SCHEMAS_DIR=/opt/esp_rs_builder/schemas \
    BUILDER_FIRMWARE_DIR=/opt/esp_rs_builder/firmware \
    BUILDER_UI_DIR=/opt/esp_rs_builder/ui \
    BUILDER_ESPFLASH=/usr/local/bin/espflash \
    BUILDER_WORK_DIR=/data/work
EXPOSE 8099
CMD ["/run.sh"]
