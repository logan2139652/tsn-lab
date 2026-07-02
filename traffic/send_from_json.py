#!/usr/bin/env python3

from scapy.all import *
import argparse
import json
import random
import struct
import threading
import time

class TSN(Packet):
    name = "TSN"
    fields_desc = [
        ShortField("next_type", 0x0800),
        ShortField("fid", 0),
        ByteField("hop_index", 0),
        ByteField("path_len", 4),
        ByteField("slot0", 0),
        ByteField("slot1", 0),
        ByteField("slot2", 0),
        ByteField("slot3", 0),
        ByteField("flags", 0),
    ]

bind_layers(Ether, TSN, type=0x1234)
bind_layers(TSN, IP, next_type=0x0800)

APP_HDR = struct.Struct("!4sHBIQ")
KIND_TSN = 1
KIND_BG = 2

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
        raise RuntimeError(f"BMv2 phase file is stale: age={age_ns / 1e6:.3f} ms")

    cycle_ns = cycle_us * 1000
    phase_ns = (phase_us * 1000 + age_ns) % cycle_ns
    cycle_base_ns = read_ns - phase_ns

    print(
        f"BMv2 phase sync: phase_us={phase_us}, "
        f"age_ms={age_ns / 1e6:.3f}, estimated_phase_us={phase_ns / 1000:.3f}"
    )
    cycle_group = data.get("cycle_group", 0)
    return cycle_base_ns, cycle_ns, cycle_group

def make_pkt(src_mac, dst_mac, src_ip, dst_ip,
             fid, path_len, slot0, slot1, slot2, slot3,
             kind, seq, payload_size):
    send_ns = time.time_ns()
    app = APP_HDR.pack(b"TSN1", fid, kind, seq, send_ns)
    payload = app + b"x" * max(0, payload_size - len(app))

    return (
        Ether(src=src_mac, dst=dst_mac, type=0x1234)
        / TSN(next_type=0x0800, fid=fid, hop_index=0, path_len=path_len,
              slot0=slot0, slot1=slot1, slot2=slot2, slot3=slot3, flags=0)
        / IP(src=src_ip, dst=dst_ip)
        / UDP(sport=10000 + fid, dport=4321)
        / Raw(payload)
    )

def tsn_sender(args, cfg, session, events, start_ns, stop_ns, base_ns, cycle_ns, slot_ns, cycle_group):
    
    src_mac, dst_mac, src_ip, dst_ip = get_sender_addrs(cfg, session)

    sock = conf.L2socket(iface=args.iface)
    seq = {event["fid"]: 0 for event in events}

    wait_until(start_ns)
    cycle = max(0, (start_ns - base_ns) // cycle_ns)

    while True:
        for event in events:
            slot_id = event["slot"]
            fid = event["fid"]
            qid = event["qid"]
            lead_us = event.get("lead_us")
            if lead_us is None:
                lead_us = args.lead_us
	    

            slot_start_ns = base_ns + cycle * cycle_ns + slot_id * slot_ns
            send_time_ns = slot_start_ns - lead_us * 1000

            if send_time_ns < start_ns:
                continue
            if send_time_ns >= stop_ns:
                sock.close()
                return

            wait_until(send_time_ns)

            # CSQF v2: slot stack generation
            path_len = session.get("path_len", 4)
            slots_per_cycle = cfg["tsn"].get("slots_per_cycle", 8)
            hop_slot_offsets = session.get("hop_slot_offsets", [0, 1, 2, 3])

            slot_list = [
                (slot_id + offset) % slots_per_cycle
                for offset in hop_slot_offsets
            ]
            s0, s1, s2, s3 = slot_list[:4]

            pkt = make_pkt(src_mac, dst_mac,
                src_ip, dst_ip,
                fid, path_len, s0, s1, s2, s3,
                KIND_TSN, seq[fid],
                session.get("tsn_payload", 300),
            )
            sock.send(pkt)
            seq[fid] += 1

        cycle += 1

def background_sender(args, cfg, session, bg_flow, start_ns, stop_ns):
    if not bg_flow or args.bg_pps <= 0:
        return

    src_mac, dst_mac, src_ip, dst_ip = get_sender_addrs(cfg, session)

    sock = conf.L2socket(iface=args.iface)
    seq = 0
    cycle = 0
    
    wait_until(start_ns)

    while time.monotonic_ns() < stop_ns:
        pkt = make_pkt(
            src_mac, dst_mac,
            src_ip, dst_ip,
            bg_flow["fid"], 0, 7, 7, 7, 7,
            KIND_BG, seq,
            session.get("bg_payload", 1200),
        )
        sock.send(pkt)
        seq += 1
        time.sleep(random.expovariate(args.bg_pps))

    sock.close()

def build_events(session):
    events = []
    bg_flow = None

    for flow in session["flows"]:
        if flow.get("type", "tsn") == "background":
            bg_flow = flow
            continue

        for slot in flow["slots"]:
            events.append({
                "slot": slot,
                "fid": flow["fid"],
                "qid": flow["qid"],
                "lead_us": flow.get("lead_us"),
            })

    events.sort(key=lambda x: x["slot"])
    return events, bg_flow

def get_sender_addrs(cfg, session):
    sender_cfg = session["sender"]
    receiver_cfg = session["receiver"]
    
    src_host = cfg["hosts"][sender_cfg["host"]]
    dst_host = cfg["hosts"][receiver_cfg["host"]]

    src_mac = src_host["mac"]
    dst_mac = dst_host["mac"]
    src_ip = src_host["ip"].split("/")[0]
    dst_ip = dst_host["ip"].split("/")[0]

    return src_mac, dst_mac, src_ip, dst_ip
    
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", default="/home/aaa/tsn-lab/configs/tsn_6sw_4host.json")
    parser.add_argument("--session", default="h1_h3")
    parser.add_argument("--iface", default=None)
    parser.add_argument("--duration", type=float, default=None)
    parser.add_argument("--start-delay", type=float, default=None)
    parser.add_argument("--lead-us", type=int, default=None)
    parser.add_argument("--phase-offset-us", type=int, default=None)
    parser.add_argument("--bg-pps", type=float, default=None)
    parser.add_argument("--max-sync-age-ms", type=float, default=100.0)
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)
        
    session = cfg["traffic"]["sessions"][args.session]
    sender_cfg = session["sender"]
    tsn_cfg = cfg["tsn"]

    args.iface = args.iface or sender_cfg.get("iface", "h1-eth0")
    args.duration = args.duration if args.duration is not None else session.get("duration", 10.0)
    args.start_delay = args.start_delay if args.start_delay is not None else session.get("start_delay", 0.2)
    args.lead_us = args.lead_us if args.lead_us is not None else tsn_cfg.get("lead_us", 3000)
    args.phase_offset_us = (
    args.phase_offset_us if args.phase_offset_us is not None
    else tsn_cfg.get("phase_offset_us", 0)
)
    args.bg_pps = args.bg_pps if args.bg_pps is not None else session.get("bg_pps", 100.0)

    sync_switch = tsn_cfg.get("sync_switch", "s1")
    sync_file = cfg["switches"][sync_switch]["phase_path"]

    base_ns, cycle_ns, cycle_group = read_bmv2_cycle_base_ns(sync_file, args.max_sync_age_ms)
    base_ns += args.phase_offset_us * 1000

    slot_us = tsn_cfg.get("slot_us", 10000)
    slot_ns = slot_us * 1000

    start_ns = time.monotonic_ns() + int(args.start_delay * 1e9)
    stop_ns = start_ns + int(args.duration * 1e9)

    events, bg_flow = build_events(session)

    print("JSON-driven GCL sender")
    print(f"config={args.config}")
    print(f"sync_switch={sync_switch}, sync_file={sync_file}")
    print(f"lead_us={args.lead_us}, phase_offset_us={args.phase_offset_us}")
    print(f"events={events}")
    print(f"background={bg_flow}, bg_pps={args.bg_pps}")

    bg = threading.Thread(target=background_sender, args=(args, cfg, session, bg_flow, start_ns, stop_ns))
    bg.start()
    tsn_sender(args, cfg, session, events, start_ns, stop_ns, base_ns, cycle_ns, slot_ns, cycle_group)
    bg.join()

    print("done")

if __name__ == "__main__":
    main()
