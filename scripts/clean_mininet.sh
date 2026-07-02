#!/usr/bin/env bash
set -euo pipefail

echo "[Mininet] Cleaning..."
sudo mn -c

echo "[Mininet] BMv2 processes:"
pgrep -a simple_switch_grpc || true
