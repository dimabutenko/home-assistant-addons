#!/bin/bash
set -e

echo "[HA Addon] Setting up storage mounts (01-ha-links)..."

CONFIG_DIR="/config"
INGEST_DIR="/cwa-book-ingest"
LIBRARY_DIR="/calibre-library"

# Пути к данным в /share (внутри контейнера)
DATA_SOURCE_CONFIG="/share/calibre-automated/config"
DATA_SOURCE_INGEST="/share/calibre-automated/ingest"
DATA_SOURCE_LIBRARY="/share/calibre-automated/library"

# Убедимся, что папки существуют
mkdir -p ${DATA_SOURCE_CONFIG}
mkdir -p ${DATA_SOURCE_INGEST}
mkdir -p ${DATA_SOURCE_LIBRARY}

# Выполняем "хак"
echo "[HA Addon] Mounting volumes..."
mount --bind ${DATA_SOURCE_CONFIG} ${CONFIG_DIR}
mount --bind ${DATA_SOURCE_INGEST} ${INGEST_DIR}
mount --bind ${DATA_SOURCE_LIBRARY} ${LIBRARY_DIR}

echo "[HA Addon] Storage is mounted. Handing over to s6-overlay init..."