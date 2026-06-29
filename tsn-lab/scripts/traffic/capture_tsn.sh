#!/usr/bin/env bash
set -euo pipefail

tcpdump -i h2-eth0 -nn -e -XX ether proto 0x1234
