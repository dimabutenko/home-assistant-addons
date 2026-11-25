# Changelog

## 2.21.2
* Part-DB 2.21.2 (from 2.20.7): label editor improvements (real paper size, part images, barcode size), creating/updating parts from info providers via API and MCP
* Database migrations run automatically on start (`DB_AUTOMIGRATE`), as required by 2.21.0
* Fixes: WebAssembly loading, gzip assets in browsers without brotli, missing permission checks

## 2.20.7
* Initial release: Part-DB 2.20.7 as a Home Assistant add-on with ingress
* Data (SQLite database, attachments, media) lives in `/data`, so it is part of add-on backups
* MCP server enabled (`/mcp` on the direct port); write tools off by default (option `mcp_editing`)
