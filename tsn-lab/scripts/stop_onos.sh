#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"

echo "[ONOS] Stopping..."
"$ONOS_HOME/bin/onos-service" stop
"$ONOS_HOME/bin/onos-service" status || true
