#!/usr/bin/env python3
import csv, sys, os

result_dir = sys.argv[1]
print("SESSION    FID   SLOT_STACK          COUNT   ANOMALY")
print("-" * 56)
for f in sorted(os.listdir(result_dir)):
    if not f.startswith("tsn_recv_") or not f.endswith(".csv"):
        continue
    sess = f.replace("tsn_recv_", "").replace(".csv", "")
    csv_path = os.path.join(result_dir, f)
    with open(csv_path) as fh:
        reader = csv.DictReader(fh)
        groups = {}
        for row in reader:
            if row["kind"] != "TSN":
                continue
            fid = int(row["fid"])
            ss = "[%s,%s,%s,%s]" % (row.get("slot0","?"), row.get("slot1","?"), row.get("slot2","?"), row.get("slot3","?"))
            key = (fid, ss)
            groups.setdefault(key, []).append(float(row["delay_us"]))
    for (fid, ss), delays in sorted(groups.items()):
        anomaly = sum(1 for d in delays if d > 60000)
        print("%s  %4d  %18s  %6d  %8d" % (sess, fid, ss, len(delays), anomaly))
