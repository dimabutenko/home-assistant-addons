# ui

Build-less single-page web UI served by `builder-server` (`BUILDER_UI_DIR`, default `ui`). See `ARCHITECTURE.md` ("Web UI").

- `index.html`, `style.css`, `app.js` — DOM code. `lib/model.js`, `lib/pinout.js` — pure logic. `lib/api.js` — server client. `lib/flash.js` — Web Serial flasher.
- `vendor/` — pinned third-party code (see `vendor/README.md`).
- Tests: `cd ui && node --test test/` (Node 20+; reads the schemas from `../schemas`).
- Run: `builder-server` from the add-on folder (or set `BUILDER_UI_DIR`), open `http://127.0.0.1:8099/`.
