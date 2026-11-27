---
paths:
  - "esp_rs_builder/**"
---
# esp_rs_builder
- Read `esp_rs_builder/CLAUDE.md` (technical rules), `ARCHITECTURE.md`, `HANDOFF.md` before any change; execute exactly one `docs/tasks/NN-*.md`.
- `schemas/` is the single source of truth (validation, codegen, UI). `firmware/` is strict `no_std`, a standalone crate outside the host workspace.
- Do not commit `firmware/src/generated.rs` with real credentials (see HANDOFF concern).
- `cargo` is not on PATH in the Git Bash tool; use PowerShell (`%USERPROFILE%\.cargo\bin`). If the toolchain/target is missing, say so in the handoff.
