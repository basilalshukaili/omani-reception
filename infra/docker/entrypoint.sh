#!/usr/bin/env bash
# Omani Reception — container entrypoint
# Waits for Postgres + Redis to become healthy, then execs the CMD.
# LF line endings are mandatory; .gitattributes enforces this.

set -euo pipefail

RECEPTION_VERSION="${RECEPTION_VERSION:-0.1.0}"
RECEPTION_BUSINESS_ID="${RECEPTION_BUSINESS_ID:-generic_demo}"

POSTGRES_HOST="${POSTGRES_HOST:-postgres}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
POSTGRES_USER="${POSTGRES_USER:-reception}"
POSTGRES_DB="${POSTGRES_DB:-reception}"

REDIS_HOST="${REDIS_HOST:-redis}"
REDIS_PORT="${REDIS_PORT:-6379}"
REDIS_PASSWORD="${REDIS_PASSWORD:-}"

# ---------- banner ----------
echo "=============================================================="
echo " Omani Reception v${RECEPTION_VERSION}"
echo " business : ${RECEPTION_BUSINESS_ID}"
echo " postgres : ${POSTGRES_HOST}:${POSTGRES_PORT}/${POSTGRES_DB}"
echo " redis    : ${REDIS_HOST}:${REDIS_PORT}"
echo "=============================================================="

# ---------- wait for Postgres ----------
echo "[entrypoint] waiting for Postgres at ${POSTGRES_HOST}:${POSTGRES_PORT}..."
for i in $(seq 1 30); do
    if pg_isready -h "${POSTGRES_HOST}" -p "${POSTGRES_PORT}" -U "${POSTGRES_USER}" -d "${POSTGRES_DB}" >/dev/null 2>&1; then
        echo "[entrypoint] Postgres ready after ${i}s."
        break
    fi
    if [ "${i}" -eq 30 ]; then
        echo "[entrypoint] ERROR: Postgres did not become ready within 30s." >&2
        exit 1
    fi
    sleep 1
done

# ---------- wait for Redis ----------
echo "[entrypoint] waiting for Redis at ${REDIS_HOST}:${REDIS_PORT}..."
for i in $(seq 1 30); do
    if [ -n "${REDIS_PASSWORD}" ]; then
        reply="$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" -a "${REDIS_PASSWORD}" --no-auth-warning ping 2>/dev/null || true)"
    else
        reply="$(redis-cli -h "${REDIS_HOST}" -p "${REDIS_PORT}" ping 2>/dev/null || true)"
    fi
    if [ "${reply}" = "PONG" ]; then
        echo "[entrypoint] Redis ready after ${i}s."
        break
    fi
    if [ "${i}" -eq 30 ]; then
        echo "[entrypoint] ERROR: Redis did not become ready within 30s." >&2
        exit 1
    fi
    sleep 1
done

echo "[entrypoint] dependencies healthy — exec'ing: $*"
exec "$@"
