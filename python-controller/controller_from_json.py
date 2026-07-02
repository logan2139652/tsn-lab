#!/usr/bin/env python3

import argparse
import json
import os
import sys
import time

P4_TUTORIALS = os.environ.get(
    "P4_TUTORIALS",
    "/home/aaa/Workspace/P4/tutorials",
)
sys.path.insert(0, os.path.join(P4_TUTORIALS, "utils"))

import p4runtime_lib.bmv2
import p4runtime_lib.helper
from p4runtime_lib.switch import ShutdownAllSwitchConnections


def build_match(route, pipeline):
    fields = pipeline["match_fields"]
    match = {}

    # 自定义匹配时，ternary 字段应在 JSON 中写成 [value, mask]
    if "match" in route:
        return route["match"]

    if fields.get("in_port") and "in_port" in route:
        match[fields["in_port"]] = (
            route["in_port"],
            0x1FF,  # bit<9> full mask
        )

    if fields.get("eth_src") and "src_mac" in route:
        match[fields["eth_src"]] = (
            route["src_mac"],
            0xFFFFFFFFFFFF,  # bit<48> full mask
        )

    if fields.get("eth_dst") and "dst_mac" in route:
        match[fields["eth_dst"]] = (
            route["dst_mac"],
            0xFFFFFFFFFFFF,
        )

    return match


def insert_route(sw, p4info_helper, route, pipeline):
    table_name = route.get("table", pipeline["table"])
    action_name = route.get("action_name", pipeline["action"])
    port_param = pipeline.get("port_param", "port")

    match_fields = build_match(route, pipeline)

    if "action_params" in route:
        action_params = route["action_params"]
    else:
        action_params = {port_param: route["out_port"]}

    kwargs = {
        "table_name": table_name,
        "match_fields": match_fields,
        "action_name": action_name,
        "action_params": action_params,
    }

    kwargs["priority"] = route.get("priority", 10)

    entry = p4info_helper.buildTableEntry(**kwargs)
    sw.WriteTableEntry(entry)

    print(
        f"[{sw.name}] route match={match_fields} "
        f"action={action_name} params={action_params}"
    )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="/home/aaa/tsn-lab/configs/tsn_2sw.json",
    )
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    p4info_helper = p4runtime_lib.helper.P4InfoHelper(cfg["p4"]["p4info"])
    bmv2_json = cfg["p4"]["bmv2_json"]
    pipeline = cfg["pipeline"]

    switches = {}

    try:
        for sw_name, sw_cfg in cfg["switches"].items():
            sw = p4runtime_lib.bmv2.Bmv2SwitchConnection(
                name=sw_name,
                address=f"127.0.0.1:{sw_cfg['grpc_port']}",
                device_id=sw_cfg["device_id"],
                proto_dump_file=f"/tmp/{sw_name}-p4runtime-requests.txt",
            )
            switches[sw_name] = sw

        for sw_name, sw in switches.items():
            print(f"[{sw_name}] MasterArbitrationUpdate")
            sw.MasterArbitrationUpdate()

        for sw_name, sw in switches.items():
            print(f"[{sw_name}] SetForwardingPipelineConfig")
            sw.SetForwardingPipelineConfig(
                p4info=p4info_helper.p4info,
                bmv2_json_file_path=bmv2_json,
            )

        time.sleep(0.5)

        for sw_name, routes in cfg["routes"].items():
            sw = switches[sw_name]
            for route in routes:
                insert_route(sw, p4info_helper, route, pipeline)

        print("Controller programming complete.")

    finally:
        ShutdownAllSwitchConnections()


if __name__ == "__main__":
    main()
