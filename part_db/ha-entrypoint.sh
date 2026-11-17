#!/bin/sh
# Home Assistant wrapper around the upstream Part-DB entrypoint:
# - keeps the data in /data (included in add-on backups) by bind-mounting it over the image's VOLUME paths
# - generates APP_SECRET once
# - maps add-on options to Part-DB environment variables
set -e

DATA=/data/partdb
mkdir -p "$DATA/uploads" "$DATA/media"

echo "[HA Add-on] Mounting data directories from $DATA ..."
mount --bind "$DATA/uploads" /var/www/html/uploads
mount --bind "$DATA/media" /var/www/html/public/media

if [ ! -s "$DATA/app_secret" ]; then
    echo "[HA Add-on] Generating APP_SECRET"
    head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > "$DATA/app_secret"
    chmod 600 "$DATA/app_secret"
fi
APP_SECRET="$(cat "$DATA/app_secret")"
export APP_SECRET

if [ -f /data/options.json ]; then
    MCP_EDITING_ENABLED="$(php -r '$o = json_decode(file_get_contents("/data/options.json"), true); echo !empty($o["mcp_editing"]) ? "1" : "0";')"
else
    MCP_EDITING_ENABLED=0
fi
export MCP_EDITING_ENABLED
echo "[HA Add-on] MCP enabled, write tools (MCP_EDITING_ENABLED): $MCP_EDITING_ENABLED"

exec partdb-entrypoint.sh "$@"
