#!/usr/bin/env bash
set -e

CONFIG="${1:-$HOME/tsn-lab/configs/tcqf_6sw_4host.json}"
TRAFFIC_DURATION="${2:-10}"

exec "$HOME/tsn-lab/scripts/run_test_simple.sh" "$CONFIG" "$TRAFFIC_DURATION"
