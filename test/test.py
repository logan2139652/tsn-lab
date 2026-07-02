from scapy.all import *

class TSN(Packet):
    name = "TSN"
    fields_desc = [
        ShortField("next_type", 0x0800),
        ShortField("fid", 100),
        ByteField("qid", 1),
        ByteField("flags", 0),
    ]

bind_layers(Ether, TSN, type=0x1234)
bind_layers(TSN, IP, next_type=0x0800)

pkt = Ether(src="00:00:00:00:00:01", dst="00:00:00:00:00:02", type=0x1234) \
    / TSN(next_type=0x0800, fid=100, qid=1, flags=0) \
    / IP(src="10.0.0.1", dst="10.0.0.2") \
    / UDP(sport=1234, dport=4321) \
    / Raw(b"qid1")

sendp(pkt, iface="h1-eth0", count=3, inter=1)
