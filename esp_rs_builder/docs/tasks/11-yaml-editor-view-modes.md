# 11 — YAML code editor and Code / Split / Visual view modes

## Goal
The builder UI works like the ESPHome editor: a **code editor** for the device YAML and the existing **visual editor** (forms + pinout) that stay in sync, with a switch between three modes: **Code only**, **Split** (code and visual side by side), **Visual only**. Editing the YAML updates the forms and the pinout; editing the forms updates the YAML. Diagnostics from `/api/validate` are shown in both views (squiggle/gutter marker in the code, inline in the forms).

## Scope
- **YAML -> model:** today the YAML is a read-only preview. Add the reverse direction. Prefer a server endpoint `POST /api/parse` (body = YAML, returns the config as JSON, or a diagnostic with line/column) implemented with `serde_yaml` in `builder-engine`, so the UI needs **no YAML parser dependency**. `!secret name` tags must survive the round trip (return them as a marked value, e.g. `{"$secret":"name"}`; the model/emitter writes them back as `!secret name`). Unknown keys/components are kept and shown, not dropped.
- **Editor component:** pick and record in HANDOFF one of: (a) a vendored, pinned **CodeMirror 6** bundle produced once with `esbuild` and committed to `ui/vendor/` (YAML mode, line numbers, diagnostics gutter, autocompletion API — needed by task 12), or (b) a minimal textarea + highlight overlay. Recommendation: (a); no build step at add-on build time, the bundle is a committed artifact with its licence and a README on how it was produced. Verify versions on npm first.
- **Sync rules:** one source of truth in the UI = the YAML text. Visual edits regenerate the text (existing emitter in `ui/lib/model.js`); text edits (debounced) go through `/api/parse` and rebuild the model. If the text does not parse, keep the last good model, show the parse error in the code view, and disable the visual view's inputs with a notice (no data loss). Preserve user comments/ordering as far as practical (state in HANDOFF what is lost when switching from visual edits; acceptable for the first version: regenerated text replaces comments only when the visual editor changes something).
- **View-mode switch** (three buttons in the header) remembered per browser (`localStorage`, mode only — never YAML or secrets). Layout responsive (stacked on narrow screens).
- **Diagnostics -> code:** map `path` (`sensor[0].i2c_id`) to a line range in the text (via the parser's source positions, or a path lookup helper in `ui/lib/`) and show markers; pure logic covered by `node --test`.
- Keep **Build / Download / Flash** and the log panel working in every mode.
- **Out of scope:** secrets UI and `!secret` autocomplete (task 12), custom boards (dropped), multi-file configs/includes.

## Constraints
- Ingress: relative URLs only; no secrets or YAML in `localStorage`.
- No component/board facts hard-coded in `ui/`; everything from schemas.
- Vendored files are pinned, carry their licence, and are listed in HANDOFF; the add-on image must still need no `npm` at build time.
- `ARCHITECTURE.md` "Web UI" section is updated in the same change (editor decision, sync rules).

## Verification
- `cargo test --workspace` (parse endpoint: valid YAML, syntax error with position, `!secret` round trip, unknown keys) and `cargo clippy --workspace --all-targets`.
- `cd ui && node --test test/` (round trip model -> YAML -> model for every shipped component; path -> line mapping; `$secret` handling) and `node --check` on every `.js`.
- Manual with a running `builder-server` and a browser: type in the code, see forms update; change a form, see code update; switch the three modes; break the YAML and see the error without losing the model. **If no browser is available say so in HANDOFF** (the DOM code of tasks 07 and 11 is then unverified).

## Definition of Done
- Three view modes working with two-way sync, parse endpoint + tests, editor bundle vendored with licence, docs/CHANGELOG/version bump, `00-index.md` + `HANDOFF.md` updated with the next prompt (task 12).
