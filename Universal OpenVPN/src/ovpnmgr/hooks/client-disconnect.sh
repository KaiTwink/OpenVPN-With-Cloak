#!/usr/bin/env bash
set -euo pipefail
PYTHON_BIN="/opt/ovpnmgr/venv/bin/python"
export PYTHONPATH="/opt/ovpnmgr/src"
if [[ -z "${common_name:-}" ]]; then
  exit 0
fi
RX="${bytes_received:-0}"
TX="${bytes_sent:-0}"
exec "$PYTHON_BIN" -m ovpnmgr.traffic_update "$common_name" "$RX" "$TX"
