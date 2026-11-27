#!/bin/sh
# Add-on entry point: prepare the persistent directories under /data and start the server.
set -eu
mkdir -p /data/work /data/cargo
exec builder-server
