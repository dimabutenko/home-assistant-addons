# 10 — Secrets backend: `!secret` and a persistent `secrets.yaml`

## Goal
Like ESPHome: a device config can reference a value from a separate secrets file with `!secret <name>` (e.g. `password: !secret wifi_password`). The secrets file lives in `/data` (add-on) and is managed through the server API. The validator, code generator and build use the resolved values; logs, API responses and the YAML preview never reveal them. Plain literal values keep working.

## Scope
- **Storage:** a flat YAML map `name: value` (strings only) at `BUILDER_SECRETS_FILE` (default `<BUILDER_WORK_DIR>/../secrets.yaml`; in the image `/data/secrets.yaml`, **not** under `/data/work`, which is excluded from backups the user may want to keep secrets in — decide and record; file mode `0600`). Atomic write (temp file + rename). Names: `[A-Za-z0-9_]+`.
- **Engine (`builder-engine`):** parse the `!secret name` tag (serde_yaml tagged value) in the config; resolve it against a `Secrets` map **after** parsing and before schema/validation of values (so `minLength` of a Wi-Fi password is checked on the real value), but keep the diagnostics `path`s unchanged. An unknown name is a validation **error** at that path (`unknown secret "wifi_password"`), not a panic. `!secret` is allowed only where the component schema marks the property `x-secret` — **or** on any string property (decide; ESPHome allows anywhere; recommend: any scalar property, simplest rule). Codegen and `redact` use the resolved values (redaction list = all resolved secret values + literal `x-secret` values).
- **API (`builder-server`):** `GET /api/secrets` → names only (`["wifi_password", ...]`), never values; `PUT /api/secrets/{name}` (body = value, max 4 KiB) and `DELETE /api/secrets/{name}`; `GET /api/secrets/file` / `PUT /api/secrets/file` for the raw YAML text (needed by the UI editor in task 14; the raw read is the **only** place values are returned — local to the add-on ingress, document this) with validation (flat string map). `POST /api/validate|generate|build` read the secrets from the store; no secrets in the request body.
- `main.rs`: new env `BUILDER_SECRETS_FILE`; create an empty file on first start if missing.
- `Dockerfile`/`run.sh`: set `BUILDER_SECRETS_FILE=/data/secrets.yaml`; `config.yaml` unchanged (no new privileges, no option). `backup_exclude` must **not** list the secrets file.
- Docs: `ARCHITECTURE.md` (secrets section), README (how secrets work, where the file is), CHANGELOG + minor version bump.
- **Out of scope:** any UI (tasks 13–14), encryption at rest, secret rotation, per-device secrets.

## Constraints
- Never log or return secret values except the explicit raw-file endpoint; error messages use names only.
- The generated `src/generated.rs` still contains real credentials in the per-job work copy (known concern in HANDOFF); do not commit it. Keep the committed `firmware/src/generated.rs` placeholder-only.
- Test passwords are built at runtime (`"fake".repeat(3)`) because the repo hook flags password-like literals.
- No new dependencies unless unavoidable (record in HANDOFF).

## Verification
- `cargo test --workspace`: `!secret` resolved in validate/generate; unknown name → error with correct path; secret value shorter than `minLength` → error; resolved values redacted in build output; API never returns values (except the raw-file endpoint); atomic write and `0600` mode (on Unix; skip the mode check on Windows and say so); name validation.
- `cargo clippy --workspace --all-targets` clean.
- Manual with a running server: `PUT` a secret, validate a YAML using `!secret`, `GET /api/secrets` shows only the name.
- **Cannot run here:** the Docker image with `/data/secrets.yaml`.

## Definition of Done
- Engine + API + env + Dockerfile updated, tests pass, docs updated, `00-index.md` + `HANDOFF.md` updated with the next prompt (task 13).
