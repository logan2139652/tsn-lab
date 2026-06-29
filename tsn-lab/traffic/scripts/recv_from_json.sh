#!/usr/bin/env bash
set -e

CONFIG=${1:-/home/aaa/tsn-lab/configs/tsn_6sw_4host.json}
SESSION=${2:-h1_h3}

python3 /home/aaa/tsn-lab/traffic/recv_from_json.py \
  --config "$CONFIG" \
  --session "$SESSION"