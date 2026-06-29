#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"

echo "[ONOS] Service status:"
"$ONOS_HOME/bin/onos-service" status || true

echo
echo "[ONOS] Devices:"
curl -s --user "$ONOS_WEB_USER:$ONOS_WEB_PASS" \
  "http://localhost:8181/onos/v1/devices"
echo

echo
echo "[ONOS] Network config:"
curl -s --user "$ONOS_WEB_USER:$ONOS_WEB_PASS" \
  "http://localhost:8181/onos/v1/network/configuration/"
echo
