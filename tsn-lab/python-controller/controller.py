#!/usr/bin/env python3

import os
import sys
import time

P4_TUTORIALS = os.environ.get("P4_TUTORIALS", os.path.expanduser("~/Desktop/tutorials"))
sys.path.append(os.path.join(P4_TUTORIALS, "utils"))

import p4runtime_lib.helper
from p4runtime_lib.bmv2 import Bmv2SwitchConnection
from p4runtime_lib.switch import ShutdownAllSwitchConnections


#P4INFO = os.path.expanduser("~/tsn-lab/build/basic.p4info.txt")
#BMV2_JSON = os.path.expanduser("~/tsn-lab/build/basic.json")
P4INFO = "/home/aaa/tsn-lab/build/tsn_basic.p4info.txt"
BMV2_JSON = "/home/aaa/tsn-lab/build/tsn_basic.json"

def mac_to_int(mac):
    return int(mac.replace(":", ""), 16)


def write_l2_rule(p4info_helper, sw, in_port, dst_mac, out_port, priority=100):
    table_entry = p4info_helper.buildTableEntry(
        table_name="ingress.table0_control.table0",
        match_fields={
            "standard_metadata.ingress_port": (in_port, 0x1FF),
            "hdr.ethernet.dst_addr": (mac_to_int(dst_mac), 0xFFFFFFFFFFFF),
        },
        action_name="ingress.table0_control.set_egress_port",
        action_params={
            "port": out_port,
        },
        priority=priority,
    )
    sw.WriteTableEntry(table_entry)
    print(f"Installed rule: in_port={in_port}, dst={dst_mac} -> out_port={out_port}")


def main():
    p4info_helper = p4runtime_lib.helper.P4InfoHelper(P4INFO)

    s1 = Bmv2SwitchConnection(
        name="s1",
        address="127.0.0.1:50051",
        device_id=1,
        proto_dump_file="/tmp/s1-p4runtime-requests.txt",
    )

    try:
        s1.MasterArbitrationUpdate()

        s1.SetForwardingPipelineConfig(
            p4info=p4info_helper.p4info,
            bmv2_json_file_path=BMV2_JSON,
        )
        print("Installed P4 pipeline on s1")

        # h1 -> h2
        write_l2_rule(p4info_helper, s1, 1, "00:00:00:00:00:02", 2)

        # h2 -> h1
        write_l2_rule(p4info_helper, s1, 2, "00:00:00:00:00:01", 1)

        # ARP broadcast h1 -> h2
        write_l2_rule(p4info_helper, s1, 1, "ff:ff:ff:ff:ff:ff", 2, priority=50)

        # ARP broadcast h2 -> h1
        write_l2_rule(p4info_helper, s1, 2, "ff:ff:ff:ff:ff:ff", 1, priority=50)

        print("Controller finished installing rules.")
        print("Now try: h1 ping h2")

        while True:
            time.sleep(10)

    except KeyboardInterrupt:
        print("Stopping controller...")
    finally:
        ShutdownAllSwitchConnections()


if __name__ == "__main__":
    main()
