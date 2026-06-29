#!/usr/bin/env bash
set -euo pipefail

source "$(dirname "$0")/env.sh"

ssh \
  -o ServerAliveInterval=30 \
  -o ServerAliveCountMax=3 \
  -p "$ONOS_SSH_PORT" \
  "$ONOS_SSH_USER@localhost"
