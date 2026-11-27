# Placeholder: builds the host workspace (builder-engine + builder-server).
# The firmware toolchain (esp-hal targets, espflash) is added once the build step exists (see docs/tasks/).
FROM rust:1-alpine AS build
RUN apk add --no-cache musl-dev
WORKDIR /src
COPY Cargo.toml Cargo.lock ./
COPY crates/ crates/
COPY schemas/ schemas/
RUN cargo build --release -p builder-server

FROM alpine:3.20
COPY --from=build /src/target/release/builder-server /usr/local/bin/builder-server
COPY schemas/ /opt/esp_rs_builder/schemas/
ENV BUILDER_SCHEMAS_DIR=/opt/esp_rs_builder/schemas
EXPOSE 8099
CMD ["builder-server"]
