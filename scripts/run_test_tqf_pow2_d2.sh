#!/usr/bin/env bash
set -euo pipefail

CONFIG="${1:-$HOME/tsn-lab/configs/tqf_pow2_d2_6sw_4host.json}"
DURATION="${2:-10}"

exec "$HOME/tsn-lab/scripts/run_test_simple.sh" "$CONFIG" "$DURATION"
