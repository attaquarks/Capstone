#!/bin/sh
# Container entrypoint for the Supply Chain Intelligence Agent.
#
# Responsibilities:
#   1. If CHROMA_HOST is set, wait until the ChromaDB service is reachable.
#   2. exec the command passed via Dockerfile CMD (uvicorn by default).
#
# Kept intentionally tiny so it works under POSIX sh (no bashisms).

set -e

if [ -n "${CHROMA_HOST}" ]; then
    CHROMA_PORT="${CHROMA_PORT:-8000}"
    HEARTBEAT_PATH="${CHROMA_HEARTBEAT_PATH:-/api/v2/heartbeat}"
    URL="http://${CHROMA_HOST}:${CHROMA_PORT}${HEARTBEAT_PATH}"

    echo "[entrypoint] Waiting for ChromaDB at ${URL} ..."
    attempts=0
    max_attempts="${CHROMA_WAIT_ATTEMPTS:-60}"
    until curl --silent --fail "${URL}" >/dev/null 2>&1; do
        attempts=$((attempts + 1))
        if [ "${attempts}" -ge "${max_attempts}" ]; then
            echo "[entrypoint] ChromaDB did not become ready after ${max_attempts} attempts; giving up." >&2
            exit 1
        fi
        sleep 2
    done
    echo "[entrypoint] ChromaDB is reachable."
fi

# Ensure the runtime directory (checkpoint DB, feedback DB, JSON mirror, local
# ChromaDB) exists even when a fresh anonymous volume is mounted over /app/runtime
# on first run.
if [ -n "${CHECKPOINT_DB_PATH}" ]; then
    mkdir -p "$(dirname "${CHECKPOINT_DB_PATH}")"
fi
mkdir -p /app/runtime/chroma_db

exec "$@"
