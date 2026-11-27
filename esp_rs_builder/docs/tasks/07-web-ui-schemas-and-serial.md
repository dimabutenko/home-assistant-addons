# 07 — Web UI: schema-driven forms, SVG pinout, build log and Web Serial flasher

## Goal
A single-page web UI served by `builder-server` that lets the user pick a board, add components from the component schemas, fix validation errors, build the firmware, watch the build log and flash the resulting image to a connected ESP32-C6 over Web Serial.

## Scope
- `ui/` — SPA with **no build step beyond what the add-on image can do offline** (decision to record in HANDOFF: plain ES modules + a vendored, pinned flasher library, or a small bundler). Served by `builder-server` as static files (`BUILDER_UI_DIR`, default `ui/`; add `tower-http` `ServeDir` or a minimal handler — record the dependency).
- Data comes only from the server API of task 06: `GET /api/boards`, `GET /api/components` (raw schema files, including pin `ui` coordinates), `POST /api/validate`, `POST /api/build`, `GET /api/jobs/{id}`, `GET /api/jobs/{id}/firmware.bin`, `GET /ws?job=<id>`.
- **Forms:** generated from each component's `config` JSON Schema (draft 2020-12 subset used by the schemas: `type`, `enum`, `default`, `minimum/maximum`, `minLength/maxLength`, nested objects, `x-ref` = select of declared ids of another component, `x-secret` = password input). No component-specific UI code.
- **YAML:** the UI keeps the device config as a model, shows the YAML text (editable both ways is optional; read-only preview is enough for this task) and sends the YAML text to the API.
- **Diagnostics:** run `/api/validate` (debounced) and map each diagnostic `path` (e.g. `sensor[0].i2c_id`) to the form field; show errors/warnings inline.
- **SVG pinout:** drawn from the board schema `pins[].ui` (`side`, `x`, `y`) with `caps` / `flags` styling (strapping, flash, usb, reserved); pins already used by the config are highlighted; clicking a pin while a pin field is focused assigns it.
- **Build:** a Build button -> `POST /api/build` -> connect `/ws?job=<id>`; frames are JSON text: `{"type":"log","line":...}` and `{"type":"status","status":"queued|running|succeeded|failed"}` (the server closes the socket after a final status). Show the log (bounded in the UI too), handle HTTP 409 (busy) and 422 (diagnostics).
- **Flasher:** after success, "Flash" uses the Web Serial API (`navigator.serial`, Chromium only; show a clear message elsewhere) with a pinned JS flasher library (`esptool-js`, verify version on npm first) to write `firmware.bin` at offset `0x0` — the image is a **merged** image (`espflash save-image --merge`: bootloader + partition table + app), 4 MiB. Show progress; a "Download .bin" link as a fallback.

## Constraints
- No secrets in `localStorage` or in logs; Wi-Fi/MQTT passwords are kept in memory only (a "remember" option is out of scope).
- Home Assistant ingress: all URLs are **relative** (no leading `/`), the WebSocket URL is derived from `location` (`ws:`/`wss:`), so the UI works behind the ingress path.
- No framework requirement, but every dependency is pinned (exact version, verified on the registry) and recorded in HANDOFF; vendored files carry their licence.
- The UI must not hard-code component or board facts (see root `CLAUDE.md` / add-on `CLAUDE.md`): everything is rendered from the schemas.
- Only ESP32-C6 has to work end to end; ESP32-S3 is selectable but may fail to build.

## Verification
- Static checks that can run here: JS syntax check (`node --check`) and unit tests of the pure parts (schema -> field model, diagnostic path -> field id) with `node --test`.
- Manual (needs a browser; say in HANDOFF what was and was not done): load the UI against a running `builder-server`, build a config, see the log stream and the final status, download the `.bin`; flashing needs a real board and cannot be verified without one.

## Definition of Done
- `ui/` served by `builder-server`, forms + pinout + diagnostics + build log + flash flow implemented, pure-logic tests pass, manual checks recorded honestly in HANDOFF; `00-index.md` + `HANDOFF.md` updated; next task spec drafted (add-on packaging: `config.yaml`, `Dockerfile` with Rust toolchain + `espflash`, ingress, `/data` work dir).
