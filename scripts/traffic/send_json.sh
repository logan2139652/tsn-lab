#!/usr/bin/env bash
set -e

CONFIG=${1:-/home/aaa/tsn-lab/configs/tsn_6sw_4host.json}

python3 /home/aaa/tsn-lab/traffic/send_from_json.py \
  --config "$CONFIG"
