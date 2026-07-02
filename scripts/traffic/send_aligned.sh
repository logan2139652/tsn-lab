#!/usr/bin/env bash
set -e

IFACE="h1-eth0"
DURATION="10"
START_DELAY="0.2"
LEAD_US="3000"
PHASE_OFFSET_US="0"
BG_PPS="000"

python3 /home/aaa/tsn-lab/traffic/send_gcl_aligned.py \
  --iface "$IFACE" \
  --duration "$DURATION" \
  --start-delay "$START_DELAY" \
  --lead-us "$LEAD_US" \
  --phase-offset-us "$PHASE_OFFSET_US" \
  --sync-file /tmp/tsn_phase.txt \
  --max-sync-age-ms 100 \
  --bg-pps "$BG_PPS" \
  --tsn-payload 300 \
  --bg-payload 1200
