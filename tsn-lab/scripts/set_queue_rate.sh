#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-2}"
RATE_PPS="${2:-50}"

echo "set_queue_rate ${RATE_PPS} ${PORT}" | simple_switch_CLI --thrift-port 9090
echo "[BMv2] Set egress queue rate: port=${PORT}, rate=${RATE_PPS} pps"
