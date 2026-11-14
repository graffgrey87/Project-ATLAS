#!/usr/bin/env bash
# =============================================================================
# ATLAS — entrypoint.sh (заглушка, Шаг 1)
# Полная реализация (zero-config GPU detection) — Шаг 3
# =============================================================================
set -euo pipefail

echo "[ATLAS] Entrypoint stub — full implementation in Step 3"
echo "[ATLAS] Starting supervisord..."

exec supervisord -c /docker/supervisord.conf
