#!/usr/bin/env bash
set -e

IFACE="h2-eth0"
DURATION="30"
CSV="/tmp/tsn_recv_delay.csv"

python3 /home/aaa/tsn-lab/traffic/recv_tsn_delay.py \
  --iface "$IFACE" \
  --duration "$DURATION" \
  --csv "$CSV"
