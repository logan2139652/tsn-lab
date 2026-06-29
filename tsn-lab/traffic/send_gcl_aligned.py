#!/usr/bin/env python3

from scapy.all import *
import argparse
import random
import struct
import threading
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
KIND_TSN = 1
KIND_BG = 2

SLOT_NS = 10_000_000
CYCLE_NS = 80_000_000

TSN_EVENTS = [
    (0, 101, 6),  # slot0 -> queue1
    (1, 102, 5),  # slot1 -> queue2
    (2, 103, 4),  # slot2 -> queue3
    (4, 101, 6),  # slot4 -> queue1
    (5, 102, 5),  # slot5 -> queue2
    (6, 103, 4),  # slot6 -> queue3
]

def make_pkt(args, fid, qid, kind, seq, payload_size):
    send_ns = time.time_ns()
    app = APP_HDR.pack(b"TSN1", fid, qid, kind, seq, send_ns)
    payload = app + b"x" * max(0, payload_size - len(app))

    return (
        Ether(src=args.src_mac, dst=args.dst_mac, type=0x1234)
        / TSN(next_type=0x0800, fid=fid, qid=qid, flags=0)
        / IP(src=args.src_ip, dst=args.dst_ip)
        / UDP(sport=10000 + fid, dport=4321)
        / Raw(payload)
    )

def wait_until(target_ns):
    while True:
        remain_ns = target_ns - time.monotonic_ns()
        if remain_ns <= 0:
            return
        if remain_ns > 2_000_000:
            time.sleep((remain_ns - 1_000_000) / 1e9)
        elif remain_ns > 100_000:
            time.sleep(remain_ns / 2 / 1e9)
            

def read_bmv2_cycle_base_ns(path, max_age_ms):
    data = {}
    with open(path) as f:
        for line in f:
            if "=" in line:
                k, v = line.strip().split("=", 1)
                data[k] = int(v)

    read_ns = time.monotonic_ns()
    mono_ns = data["mono_ns"]
    phase_us = data["phase_us"]
    cycle_us = data.get("cycle_us", 80000)

    age_ns = max(0, read_ns - mono_ns)
    if age_ns > int(max_age_ms * 1_000_000):
        raise RuntimeError(
            f"BMv2 phase file is stale: age={age_ns / 1e6:.3f} ms"
        )

    cycle_ns = cycle_us * 1000
    phase_ns = (phase_us * 1000 + age_ns) % cycle_ns
    cycle_base_ns = read_ns - phase_ns

    print(
        f"BMv2 phase sync: phase_us={phase_us}, "
        f"age_ms={age_ns / 1e6:.3f}, "
        f"estimated_phase_us={phase_ns / 1000:.3f}"
    )

    return cycle_base_ns


def tsn_sender(args, start_ns, stop_ns, base_ns):
    sock = conf.L2socket(iface=args.iface)
    seq = {101: 0, 102: 0, 103: 0}

    wait_until(start_ns)

    cycle = max(0, (start_ns - base_ns) // CYCLE_NS)

    while True:
        for slot_id, fid, qid in TSN_EVENTS:
            slot_start_ns = base_ns + cycle * CYCLE_NS + slot_id * SLOT_NS
            send_time_ns = slot_start_ns - args.lead_us * 1000

            if send_time_ns < start_ns:
                continue

            if send_time_ns >= stop_ns:
                sock.close()
                return

            wait_until(send_time_ns)

            pkt = make_pkt(args, fid, qid, KIND_TSN, seq[fid], args.tsn_payload)
            sock.send(pkt)
            seq[fid] += 1

        cycle += 1

def background_sender(args, start_ns, stop_ns):
    if args.bg_pps <= 0:
        return

    sock = conf.L2socket(iface=args.iface)
    seq = 0

    wait_until(start_ns)

    while time.monotonic_ns() < stop_ns:
        pkt = make_pkt(args, 200, 7, KIND_BG, seq, args.bg_payload)
        sock.send(pkt)
        seq += 1
        time.sleep(random.expovariate(args.bg_pps))

    sock.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iface", default="h1-eth0")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--start-delay", type=float, default=1.0)
    parser.add_argument("--phase-offset-us", type=int, default=0)
    parser.add_argument("--lead-us", type=int, default=3000)
    parser.add_argument("--bg-pps", type=float, default=200.0)
    parser.add_argument("--tsn-payload", type=int, default=300)
    parser.add_argument("--bg-payload", type=int, default=1200)
    parser.add_argument("--src-mac", default="00:00:00:00:00:01")
    parser.add_argument("--dst-mac", default="00:00:00:00:00:02")
    parser.add_argument("--src-ip", default="10.0.0.1")
    parser.add_argument("--dst-ip", default="10.0.0.2")
    parser.add_argument("--sync-file", default="/tmp/tsn_phase.txt")
    parser.add_argument("--max-sync-age-ms", type=float, default=100.0)
    args = parser.parse_args()

    base_ns = (
        read_bmv2_cycle_base_ns(args.sync_file, args.max_sync_age_ms)
        + args.phase_offset_us * 1000
    )

    start_ns = time.monotonic_ns() + int(args.start_delay * 1e9)
    stop_ns = start_ns + int(args.duration * 1e9)

    print("GCL-aligned TSN sender")
    print("fid=101 qid=6 queue1 -> slot0/slot4")
    print("fid=102 qid=5 queue2 -> slot1/slot5")
    print("fid=103 qid=4 queue3 -> slot2/slot6")
    print("fid=200 qid=7 queue0 -> random background")
    print(
    f"lead_us={args.lead_us}, phase_offset_us={args.phase_offset_us}, "
    f"sync_file={args.sync_file}")

    bg = threading.Thread(target=background_sender, args=(args, start_ns, stop_ns))
    bg.start()
    tsn_sender(args, start_ns, stop_ns, base_ns)
    bg.join()

    print("done")

if __name__ == "__main__":
    main()
