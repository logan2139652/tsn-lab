#!/usr/bin/env bash
set -euo pipefail

PORT="${1:-2}"
RATE_PPS="${2:-50}"
#!/usr/bin/env bash
set -e

IFACE="h1-eth0"
DURATION="10"
TSN_INTER="0.02"
BG_PPS="200"
TSN_PAYLOAD="300"
BG_PAYLOAD="1200"

python3 /home/aaa/tsn-lab/traffic/send_gcl_flows.py \
  --iface "$IFACE" \
  --duration "$DURATION" \
  --tsn-inter "$TSN_INTER" \
  --bg-pps "$BG_PPS" \
  --tsn-payload "$TSN_PAYLOAD" \
  --bg-payload "$BG_PAYLOAD"
