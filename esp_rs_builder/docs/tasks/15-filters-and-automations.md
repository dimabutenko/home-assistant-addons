# 15 — Filters, automations and templates (DRAFT, not prioritized)

> **Status: draft/placeholder.** Collected from the user's wishes; to be refined (and split into smaller tasks) before it is scheduled. Do not implement from this file alone.

## Goal
Cover the ESPHome features that make configs useful beyond plain components: sensor **filters** (`multiply`, `offset`, `sliding_window_moving_average`, `throttle`, `delta`, `calibrate_linear`, ...), **automations** (`on_value`, `on_press`, `on_boot`, `interval`, actions such as `switch.turn_on`, `delay`, `if`), and a replacement for **`lambda`** (C++ in ESPHome) that is safe for a Rust/`no_std` build.

## Open questions (decide in the first refinement session)
- **Lambda replacement:** no raw Rust from the user in YAML? Options: (a) a small expression language compiled by codegen to Rust (`x * 0.5 + 2`), (b) a fixed set of filters/actions only (no free code), (c) an "escape hatch" component that embeds a user Rust snippet (security/safety: it runs on the user's own device, but it also runs on the build server). Recommendation to evaluate: (b) first, then (a).
- **Execution model:** filter chains as `no_std` pipeline stages between the component task and the `Registry` slot; automations as Embassy tasks subscribed to `Watch`/`Signal`. Static allocation only (no dynamic component creation).
- **Triggers/actions catalog:** schema-driven like components (a `triggers` / `actions` schema kind) so the UI forms and the validator come for free.
- **UI:** an automation editor is a large piece; the first version can be YAML-only (code editor from task 13) with validation and completion.
- **Compatibility:** keep the ESPHome key names so existing snippets copy over.

## Suggested split (when scheduled)
1. Filter pipeline + 6–8 core filters (schema `filters`, codegen, firmware stages).
2. Triggers and actions engine for switches/binary sensors (`on_press`, `on_value`, `switch.turn_on/off/toggle`, `delay`, `if`).
3. `interval`/`time` + `on_boot`.
4. Expression language or chosen lambda replacement.
5. UI support (completion/forms) for the above.

## Definition of Done (for the refined tasks)
- Each sub-task gets its own spec with Goal/Scope/Constraints/Verification/DoD via the `new-task` skill; this draft is then marked superseded.
