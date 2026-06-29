#!/usr/bin/env python3

from scapy.all import *
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

IFACE = "h1-eth0"
DST_MAC = "00:00:00:00:00:02"
SRC_MAC = "00:00:00:00:00:01"

def make_pkt(qid, payload):
    return (
        Ether(src=SRC_MAC, dst=DST_MAC, type=0x1234)
        / TSN(next_type=0x0800, fid=100, qid=qid, flags=0)
        / IP(src="10.0.0.1", dst="10.0.0.2")
        / UDP(sport=1234, dport=4321)
        / Raw(payload)
    )

def send_low():
    pkt = make_pkt(1, b"low-qid1" * 100)
    sendp(pkt, iface=IFACE, count=500, inter=0.001, verbose=False)

def send_high():
    time.sleep(0.15)
    pkt = make_pkt(5, b"high-qid5" * 100)
    sendp(pkt, iface=IFACE, count=10, inter=0.01, verbose=False)

if __name__ == "__main__":
    t1 = threading.Thread(target=send_low)
    t2 = threading.Thread(target=send_high)

    print("Sending low qid=1 burst and high qid=5 inserts...")
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    print("Done.")
