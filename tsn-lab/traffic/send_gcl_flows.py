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

def make_pkt(args, fid, qid, kind, seq, payload_size):
    send_ns = time.time_ns()
    app = APP_HDR.pack(b"TSN1", fid, qid, kind, seq, send_ns)
    pad_len = max(0, payload_size - len(app))
    payload = app + (b"x" * pad_len)

    return (
        Ether(src=args.src_mac, dst=args.dst_mac, type=0x1234)
        / TSN(next_type=0x0800, fid=fid, qid=qid, flags=0)
        / IP(src=args.src_ip, dst=args.dst_ip)
        / UDP(sport=10000 + fid, dport=4321)
        / Raw(payload)
    )

def periodic_flow(args, fid, qid, inter, payload_size, stop_at):
    seq = 0
    while time.time() < stop_at:
        pkt = make_pkt(args, fid, qid, KIND_TSN, seq, payload_size)
        sendp(pkt, iface=args.iface, verbose=False)
        seq += 1
        time.sleep(inter)

def background_flow(args, fid, qid, pps, payload_size, stop_at):
    seq = 0
    while time.time() < stop_at:
        pkt = make_pkt(args, fid, qid, KIND_BG, seq, payload_size)
        sendp(pkt, iface=args.iface, verbose=False)
        seq += 1
        if pps > 0:
            time.sleep(random.expovariate(pps))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iface", default="h1-eth0")
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--src-mac", default="00:00:00:00:00:01")
    parser.add_argument("--dst-mac", default="00:00:00:00:00:02")
    parser.add_argument("--src-ip", default="10.0.0.1")
    parser.add_argument("--dst-ip", default="10.0.0.2")
    parser.add_argument("--tsn-inter", type=float, default=0.02)
    parser.add_argument("--bg-pps", type=float, default=200.0)
    parser.add_argument("--tsn-payload", type=int, default=300)
    parser.add_argument("--bg-payload", type=int, default=1200)
    args = parser.parse_args()

    stop_at = time.time() + args.duration

    flows = [
        threading.Thread(target=periodic_flow, args=(args, 101, 6, args.tsn_inter, args.tsn_payload, stop_at)),
        threading.Thread(target=periodic_flow, args=(args, 102, 5, args.tsn_inter, args.tsn_payload, stop_at)),
        threading.Thread(target=periodic_flow, args=(args, 103, 4, args.tsn_inter, args.tsn_payload, stop_at)),
        threading.Thread(target=background_flow, args=(args, 200, 7, args.bg_pps, args.bg_payload, stop_at)),
    ]

    print("start sending")
    print("TSN: fid=101 qid=6 queue1")
    print("TSN: fid=102 qid=5 queue2")
    print("TSN: fid=103 qid=4 queue3")
    print("BG : fid=200 qid=7 queue0")

    for t in flows:
        t.start()
    for t in flows:
        t.join()

    print("done")

if __name__ == "__main__":
    main()
