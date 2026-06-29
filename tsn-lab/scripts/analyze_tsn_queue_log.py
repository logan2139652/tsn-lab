#!/usr/bin/env python3

import argparse
import collections
import csv
import math
import re

TSN_RE = re.compile(r"\[(\d\d:\d\d:\d\d\.\d+)\].*TSN_QUEUE (enqueue|dequeue).*")

def time_to_sec(t):
    hh, mm, rest = t.split(":")
    ss = float(rest)
    return int(hh) * 3600 + int(mm) * 60 + ss

def pct(values, p):
    if not values:
        return None
    values = sorted(values)
    idx = max(0, min(len(values) - 1, math.ceil(len(values) * p / 100) - 1))
    return values[idx]

def parse_kv(line):
    return {k: int(v) for k, v in re.findall(r"(egress_port|priority|queue_idx|worker_id)=(\d+)", line)}

def load_events(path):
    events = []
    with open(path) as f:
        for line in f:
            m = TSN_RE.search(line)
            if not m:
                continue
            t_str, event = m.groups()
            kv = parse_kv(line)
            if "egress_port" not in kv or "priority" not in kv or "queue_idx" not in kv:
                continue
            events.append({
                "time_str": t_str,
                "time": time_to_sec(t_str),
                "event": event,
                "port": kv["egress_port"],
                "priority": kv["priority"],
                "queue_idx": kv["queue_idx"],
                "line": line.strip(),
            })
    return events

def load_send_log(path):
    counts = collections.Counter()
    first = {}
    last = {}
    with open(path) as f:
        reader = csv.DictReader(f)
        for row in reader:
            qid = int(row["qid"])
            counts[qid] += 1
            first.setdefault(qid, row["time"])
            last[qid] = row["time"]
    return counts, first, last

def parse_expect(items):
    expected = {}
    for item in items:
        qid, count = item.split("=")
        expected[int(qid)] = int(count)
    return expected

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("log", help="BMv2 log path, e.g. /tmp/s1-simple-switch-grpc.log.txt")
    parser.add_argument("--send-log", default=None)
    parser.add_argument("--expect", nargs="*", default=[], help="expected counts, e.g. 1=500 5=10")
    parser.add_argument("--high-priority", type=int, default=5)
    args = parser.parse_args()

    events = load_events(args.log)
    if not events:
        print("No TSN_QUEUE events found.")
        return

    enq_counts = collections.Counter()
    deq_counts = collections.Counter()
    pending = collections.defaultdict(collections.deque)
    backlog = collections.Counter()
    max_backlog = collections.Counter()
    waits = collections.defaultdict(list)
    unmatched_deq = collections.Counter()
    high_deq_while_lower_pending = 0

    t0 = events[0]["time"]

    for e in events:
        key = (e["port"], e["priority"], e["queue_idx"])
        prio = e["priority"]

        if e["event"] == "enqueue":
            enq_counts[prio] += 1
            pending[key].append(e["time"])
            backlog[prio] += 1
            max_backlog[prio] = max(max_backlog[prio], backlog[prio])

        else:
            deq_counts[prio] += 1

            lower_pending = sum(count for p, count in backlog.items() if p < prio)
            if prio >= args.high_priority and lower_pending > 0:
                high_deq_while_lower_pending += 1

            if pending[key]:
                enq_t = pending[key].popleft()
                waits[prio].append((e["time"] - enq_t) * 1000.0)
            else:
                unmatched_deq[prio] += 1

            if backlog[prio] > 0:
                backlog[prio] -= 1

    print("=== BMv2 TSN Queue Log Summary ===")
    print(f"events: {len(events)}")
    print(f"time window: {events[0]['time_str']} -> {events[-1]['time_str']} ({events[-1]['time'] - t0:.3f}s)")
    print()

    priorities = sorted(set(enq_counts) | set(deq_counts))
    for p in priorities:
        ws = waits[p]
        print(f"priority={p}")
        print(f"  enqueue={enq_counts[p]} dequeue={deq_counts[p]} max_backlog={max_backlog[p]} unmatched_dequeue={unmatched_deq[p]}")
        if ws:
            print(
                "  wait_ms "
                f"min={min(ws):.3f} avg={sum(ws)/len(ws):.3f} "
                f"p50={pct(ws, 50):.3f} p95={pct(ws, 95):.3f} max={max(ws):.3f}"
            )
        else:
            print("  wait_ms none")
        print()

    print("=== Priority Evidence ===")
    print(
        f"high priority dequeued while lower-priority backlog existed: "
        f"{high_deq_while_lower_pending}"
    )
    print()

    expected = parse_expect(args.expect)
    if expected:
        print("=== Expected vs BMv2 Enqueue ===")
        for qid, count in sorted(expected.items()):
            print(f"qid/priority={qid}: expected_send={count} bmv2_enqueue={enq_counts[qid]}")
        print()

    if args.send_log:
        send_counts, first, last = load_send_log(args.send_log)
        print("=== Send Log Summary ===")
        for qid in sorted(send_counts):
            print(
                f"qid={qid}: sent={send_counts[qid]} "
                f"send_window={first[qid]} -> {last[qid]} "
                f"bmv2_enqueue={enq_counts[qid]} dequeue={deq_counts[qid]}"
            )

if __name__ == "__main__":
    main()
