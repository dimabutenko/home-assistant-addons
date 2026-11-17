# Home Assistant Add-on: Part-DB

[Part-DB](https://github.com/Part-DB/Part-DB-server) (inventory of electronic components) as a Home Assistant add-on,
with ingress and the built-in MCP server for AI assistants.

Wraps the upstream image `jbtronics/part-db1` (the version in `config.yaml` / `Dockerfile` follows upstream).

## How it works

* **Ingress**: Home Assistant sends the path prefix in `X-Ingress-Path`; `ha-ingress.conf` (Apache) copies it to
  `X-Forwarded-Prefix`, which Part-DB understands. Requests on the direct port get no prefix.
* **Data**: `ha-entrypoint.sh` bind-mounts `/data/partdb/uploads` (SQLite DB `app.db`, attachments, automigration backups) and
  `/data/partdb/media` over the image's `VOLUME` paths, so everything is part of the add-on backup. `APP_SECRET` is generated
  once into `/data/partdb/app_secret`.
* **First start**: migrations run automatically and the log prints the initial password of the `admin` user. Change it
  right away (user menu -> settings).
* **MCP**: enabled, endpoint `http://<host>:8087/mcp` (Streamable HTTP, `Authorization: Bearer tcp_...`). Create an API token in
  the user settings (scope Read-Only is enough for searching). Write tools stay off until the option `mcp_editing` is set.
* The direct port (8087) is only needed for MCP/API clients; remove the mapping in the add-on network settings if unused.
