#!/usr/bin/env python3
"""Program TCQF cycle remap tables via simple_switch_CLI"""
import json, sys, subprocess

config_path = sys.argv[1]
with open(config_path) as f:
    cfg = json.load(f)

tcqf = cfg.get("tcqf", {})
delta = tcqf.get("default_delta", 1)
cycle_count = tcqf.get("cycle_count", 8)
be_cycle = tcqf.get("be_cycle", 7)

tsn_fids = [101, 102, 103, 201, 202, 203]
bg_fids = [200, 300]

for sw_name in ["s1", "s2", "s3", "s4", "s5", "s6"]:
    cli_port = 50051 + int(sw_name[1:]) - 1
    for fid in tsn_fids + bg_fids:
        # Determine ingress port
        if sw_name == "s1":
            ing_port = 1 if fid < 200 else 2
        elif sw_name == "s2" and fid < 200:
            ing_port = 1
        elif sw_name == "s3" and fid >= 200:
            ing_port = 1
        elif sw_name == "s4" and fid >= 200:
            ing_port = 1
        elif sw_name == "s5" and fid < 200:
            ing_port = 1
        elif sw_name == "s6":
            ing_port = 1 if fid < 200 else 2
        else:
            continue

        for in_cycle in range(8):
            if fid >= 200:
                out_cycle = be_cycle
            else:
                out_cycle = (in_cycle + delta) % cycle_count
            cmd = (
                f"echo 'table_add tcqf_cycle_map set_out_cycle "
                f"{ing_port} {fid} {in_cycle} => {out_cycle}' "
                f"| simple_switch_CLI --thrift-port {cli_port}"
            )
            subprocess.run(cmd, shell=True, capture_output=True)
    print(f"  OK {sw_name}")
print("TCQF cycle map programmed")
