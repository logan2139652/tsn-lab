#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"

BMV2_HELPER="$ONOS_ROOT/tools/dev/mininet/bmv2.py"

if [ ! -f "$BMV2_HELPER" ]; then
  echo "[ERROR] Missing bmv2.py: $BMV2_HELPER"
  exit 1
fi

echo "[Mininet] Starting BMv2 topology..."
echo "[Mininet] Pipeconf: $PIPECONF_ID"

sudo -E mn \
  --custom "$BMV2_HELPER" \
  --switch "onosbmv2,pipeconf=$PIPECONF_ID" \
  --controller remote,ip=127.0.0.1 \
  --topo single,2
