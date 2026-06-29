#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"

echo "[ONOS] Java:"
java -version

echo "[ONOS] Starting..."
"$ONOS_HOME/bin/onos-service" start

echo "[ONOS] Waiting..."
sleep 60

echo "[ONOS] Status:"
"$ONOS_HOME/bin/onos-service" status

echo "[ONOS] UI: http://localhost:8181/onos/ui/"
echo "[ONOS] CLI: $ONOS_HOME/bin/onos localhost"
