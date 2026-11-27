# 11 — ESPHome schema import and component stubs

## Goal
The UI lists (greyed out, not selectable for build) every ESPHome component we have not ported yet, so the porting backlog is visible and each stub already carries the right config keys. A tool converts the published ESPHome component schema into our component-schema format with `"status": "stub"`; flipping a stub to a real component means adding the firmware module (task 10 kit) and removing the status. A coverage view shows what is implemented vs. stub.

## Scope
- **Licence check first (blocking):** the ESPHome schemas are published at `esphome/esphome-schema` (Apache-2.0 per the GitHub API; the Python side of ESPHome is MIT, the C++ files are GPLv3). Read the actual LICENSE files, decide whether generated stubs may be committed here, record the decision and attribution (NOTICE/README) in HANDOFF. If committing is not acceptable, the importer runs on demand and the output stays untracked.
- **Importer** (`builder-engine import-esphome <component> [--platform <p>]`, or a small separate host crate/script — decide, no Python dependency at runtime): reads the ESPHome schema JSON (local file or URL given by the user; do not hard-wire network access into the add-on), maps its keys to our JSON Schema subset (types, enums, defaults, required, `pin_schema` -> a `pins` role, `use_id` -> `x-ref`, secrets -> `x-secret`), keeps unsupported constructs as notes in the stub (`x-esphome-unsupported`), writes `schemas/components/<id>.json` with `"status": "stub"` and `firmware: null`.
- **Engine:** stubs load, validate their own YAML shape, but a config that uses one gets a clear **error** (`component "dht" is not implemented yet`), never a silent build; `GET /api/components` includes `status` (default `ready`).
- **UI:** the add-component list shows stubs greyed out with a "not implemented" badge (tooltip: ESPHome key names are ready, firmware missing), searchable; a **Coverage** page/section lists ready vs stub per category with counts. Pure logic covered by `node --test`.
- **Seed set:** import a first batch of ~15–25 popular components (e.g. `dht`, `ds18b20`/`dallas_temp`, `aht10`, `sht3xd`, `bh1750`, `ads1115`, `ina219`, `adc`, `pwm`/`ledc output`, `light` basics, `uart`, `spi`, `status_led`, `time`, `interval`) as stubs, chosen from ESPHome's most-used list; record the list.
- **Out of scope:** implementing any of them, filters/automations/lambda (task 15), a generic remote catalog sync.

## Constraints
- Schemas remain the single source of truth; the UI must not know any component by name.
- A stub must never reach codegen/build.
- No new runtime network access in the add-on; the importer is a developer tool.
- Everything in English; no copied ESPHome C++ or Python code, only schema data (after the licence decision).

## Verification
- `cargo test --workspace`: importer golden tests on 2–3 saved ESPHome schema excerpts (checked-in fixtures); engine rejects a config with a stub; `status` appears in `/api/components`.
- `cargo clippy --workspace --all-targets`; `cd ui && node --test test/` and `node --check`.
- Manual in a browser (say if not run): stubs greyed in the list, Coverage page counts.
- **Cannot run here:** anything needing a live fetch of the upstream repo if the network is blocked; say so.

## Definition of Done
- Licence decision recorded; importer + stub status in engine and UI; seed stubs committed (or documented as untracked); `docs/PORTING.md` mentions the stub -> real workflow; `ARCHITECTURE.md`, README, `CHANGELOG.md` + version bump; `00-index.md` + `HANDOFF.md` updated with the prompt for task 12.
