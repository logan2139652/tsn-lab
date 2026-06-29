#!/usr/bin/env python3

from scapy.all import *
import argparse
import csv
import json
import statistics
import struct
import time

class TSN(Packet):
    name = "TSN"
    fields_desc = [
        ShortField("next_type", 0x0800),
        ShortField("fid", 0),
        ByteField("qid", 0),
        ByteField("flags", 0),
    ]

bind_layers(Ether, TSN, type=0x1234)
bind_layers(TSN, IP, next_type=0x0800)

APP_HDR = struct.Struct("!4sHBBIQ")
KIND_NAME = {1: "TSN", 2: "BG"}

stats = {}
rows = []

def percentile(values, p):
    if not values:
        return 0.0
    values = sorted(values)
    idx = int((len(values) - 1) * p)
    return values[idx]

def print_stats():
    print("\n=== Delay Summary ===")
    for key, delays in sorted(stats.items()):
        kind, fid, qid = key
        avg = statistics.mean(delays)
        p50 = percentile(delays, 0.50)
        p95 = percentile(delays, 0.95)
        print(
            f"{kind} fid={fid} qid={qid} count={len(delays)} "
            f"avg={avg:.3f}us p50={p50:.3f}us p95={p95:.3f}us "
            f"min={min(delays):.3f}us max={max(delays):.3f}us"
        )

def handle(pkt):
    if TSN not in pkt or Raw not in pkt:
        return

    raw = bytes(pkt[Raw].load)
    if len(raw) < APP_HDR.size:
        return

    magic, fid, qid, kind, seq, send_ns = APP_HDR.unpack(raw[:APP_HDR.size])
    if magic != b"TSN1":
        return

    recv_ns = time.time_ns()
    delay_us = (recv_ns - send_ns) / 1000.0
    kind_name = KIND_NAME.get(kind, f"kind{kind}")

    key = (kind_name, fid, qid)
    stats.setdefault(key, []).append(delay_us)

    rows.append({
        "recv_ns": recv_ns,
        "kind": kind_name,
        "fid": fid,
        "qid": qid,
        "seq": seq,
        "delay_us": f"{delay_us:.3f}",
    })

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/home/aaa/tsn-lab/configs/tsn_6sw_4host.json")
    parser.add_argument("--iface", default=None)
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--csv", default=None)
    parser.add_argument("--session", default="h1_h3")
    args = parser.parse_args()

    stats.clear()
    rows.clear()

    with open(args.config) as f:
        cfg = json.load(f)

    session = cfg["traffic"]["sessions"][args.session]
    recv_cfg = session["receiver"]

    iface = args.iface or recv_cfg["iface"]
    duration = args.duration if args.duration is not None else recv_cfg.get("duration", 30.0)
    csv_path = args.csv or recv_cfg.get("csv", "/tmp/tsn_recv_delay.csv")

    print(f"session={args.session}")
    print(f"listening on {iface}, duration={duration}s")
    print(f"csv output: {csv_path}")

    sniff(
        iface=iface,
        filter="ether proto 0x1234",
        prn=handle,
        store=False,
        timeout=duration,
    )

    with open(csv_path, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["recv_ns", "kind", "fid", "qid", "seq", "delay_us"],
        )
        writer.writeheader()
        writer.writerows(rows)

    print_stats()

if __name__ == "__main__":
    main()
