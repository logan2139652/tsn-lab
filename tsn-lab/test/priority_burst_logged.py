#!/usr/bin/env python3

from scapy.all import *
import argparse
import csv
import datetime
import threading
import time

class TSN(Packet):
    name = "TSN"
    fields_desc = [
        ShortField("next_type", 0x0800),
        ShortField("fid", 100),
        ByteField("qid", 0),
        ByteField("flags", 0),
    ]

bind_layers(Ether, TSN, type=0x1234)
bind_layers(TSN, IP, next_type=0x0800)

def now_hms():
    return datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3]

def make_pkt(qid, seq, payload_size):
    payload = f"qid={qid},seq={seq},".encode()
    if len(payload) < payload_size:
        payload += b"x" * (payload_size - len(payload))

    return (
        Ether(src="00:00:00:00:00:01", dst="00:00:00:00:00:02", type=0x1234)
        / TSN(next_type=0x0800, fid=100, qid=qid, flags=0)
        / IP(src="10.0.0.1", dst="10.0.0.2")
        / UDP(sport=1234, dport=4321)
        / Raw(payload)
    )

def sender(args, qid, count, inter, delay, label, writer, lock):
    time.sleep(delay)
    for seq in range(count):
        pkt = make_pkt(qid, seq, args.payload_size)
        sendp(pkt, iface=args.iface, count=1, verbose=False)

        with lock:
            writer.writerow({
                "time": now_hms(),
                "label": label,
                "qid": qid,
                "seq": seq,
                "payload_size": args.payload_size,
            })

        time.sleep(inter)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--iface", default="h1-eth0")
    parser.add_argument("--log", default="/tmp/tsn_send_log.csv")
    parser.add_argument("--low-qid", type=int, default=1)
    parser.add_argument("--high-qid", type=int, default=5)
    parser.add_argument("--low-count", type=int, default=1000)
    parser.add_argument("--high-count", type=int, default=10)
    parser.add_argument("--low-inter", type=float, default=0)
    parser.add_argument("--high-inter", type=float, default=0.001)
    parser.add_argument("--high-delay", type=float, default=0.6)
    parser.add_argument("--payload-size", type=int, default=1400)
    args = parser.parse_args()

    lock = threading.Lock()

    with open(args.log, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["time", "label", "qid", "seq", "payload_size"],
        )
        writer.writeheader()

        low = threading.Thread(
            target=sender,
            args=(args, args.low_qid, args.low_count, args.low_inter, 0, "low", writer, lock),
        )
        high = threading.Thread(
            target=sender,
            args=(args, args.high_qid, args.high_count, args.high_inter, args.high_delay, "high", writer, lock),
        )

        print(f"send log: {args.log}")
        low.start()
        high.start()
        low.join()
        high.join()

    print("done")

if __name__ == "__main__":
    main()
