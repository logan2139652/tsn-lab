#!/usr/bin/env python3
import csv
import os
import sys

result_dir = sys.argv[1]

print("SESSION    FID   BATCH_NO   QUEUE   COUNT   COMPLETE   ANOMALY")
print("-" * 68)

for filename in sorted(os.listdir(result_dir)):
    if not filename.startswith("tsn_recv_") or not filename.endswith(".csv"):
        continue

    sess = filename.replace("tsn_recv_", "").replace(".csv", "")
    csv_path = os.path.join(result_dir, filename)
    groups = {}

    with open(csv_path) as fh:
        reader = csv.DictReader(fh)
        for row in reader:
            if row.get("kind") != "TSN":
                continue

            fid = int(row["fid"])
            batch_size = int(row.get("batch_size") or 1)
            batch_no = int(
                row.get("batch_no") or
                (int(row.get("seq", 0)) // max(1, batch_size)))
            queue = row.get("flags", "?")
            key = (fid, batch_no, batch_size, queue)
            groups.setdefault(key, []).append(float(row["delay_us"]))

    for (fid, batch_no, batch_size, queue), delays in sorted(groups.items()):
        anomaly = sum(1 for delay in delays if delay > 60000)
        complete = "yes" if len(delays) >= batch_size else "no"
        print(
            "%-8s  %4d  %9d  %6s  %6d  %8s  %8d" %
            (sess, fid, batch_no, queue, len(delays), complete, anomaly))
