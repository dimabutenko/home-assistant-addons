# Add-on reference (state at 2026-11-27)

| Folder | Kind | Checks (run from the folder) | CI |
|---|---|---|---|
| `twinkly_garland` | Python 3.12 FastAPI + numpy, ingress 8099, aarch64, `image: ghcr.io/dimabutenko/ha-addon-twinkly` | `python tests/test_channels.py`, `tests/test_golden.py`, `tests/test_live.py`, `tests/test_theme.py`, `tests/edge_cases.py` | `build-twinkly.yml` |
| `calibre_web_automated` | wrapper of an upstream image, `privileged`, `map: media` | none | `build.yml` (single arch, ghcr) |
| `nvme_smart` | shell (`run.sh`), `privileged` + `devices` | none | none |
| `part_db` | upstream wrapper (`ha-entrypoint.sh`, `ha-ingress.conf`) | none | none |
| `esp_rs_builder` | Rust workspace + firmware, ingress 8099, version 0.1.0 (in development) | PowerShell, from the folder: `cargo test --workspace` | `build-esp-rs-builder.yml` |
| `koinsight`, `dzen_analytics`, `samba-v1` | config-only / minimal | none | none |

Notes
- `cargo` is missing from the Git Bash PATH here; use PowerShell with `%USERPROFILE%\.cargo\bin`.
- `dzen_analytics`, `koinsight` have no Dockerfile/CHANGELOG/README; `samba-v1` has no CHANGELOG/README. Report, do not "fix" outside the task scope.
- Keep this table current when an add-on or a CI workflow is added.
