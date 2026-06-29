#!/usr/bin/env python3

from mininet.net import Mininet
from mininet.node import Switch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import os
import signal


class Bmv2GrpcSwitch(Switch):
    def __init__(self, name, json_path, grpc_port=50051, device_id=1, **kwargs):
        super().__init__(name, **kwargs)
        self.json_path = json_path
        self.grpc_port = grpc_port
        # self.thrift_port = thrift_port
        self.device_id = device_id
        self.pid_file = f"/tmp/{name}-simple-switch-grpc.pid"
        self.log_file = f"/tmp/{name}-simple-switch-grpc.log"

    def start(self, controllers):
        intf_args = []
        for port, intf in self.intfs.items():
            if port == 0:
                continue
            intf_args.append(f"-i {port}@{intf.name}")
        
        cmd = (
	    f"simple_switch_grpc "
	    f"--device-id {self.device_id} "
	    f"--log-file {self.log_file} "
            f"-L info "
            f"--log-flush "
	    f"{' '.join(intf_args)} "
	    f"{self.json_path} "
	    f"-- "
	    f"--grpc-server-addr 0.0.0.0:{self.grpc_port} "
	    f"> /tmp/{self.name}-stdout.log 2>&1 & echo $! > {self.pid_file}"
	)
        
        info(f"*** Starting {self.name}: {cmd}\n")
        self.cmd(cmd)

    def stop(self):
        if os.path.exists(self.pid_file):
            with open(self.pid_file) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            os.remove(self.pid_file)
        super().stop()


def main():
    # json_path = os.path.expanduser("~/tsn-lab/build/basic.json")
    # json_path = "/home/aaa/tsn-lab/build/basic.json"
    json_path = "/home/aaa/tsn-lab/build/tsn_basic.json"
    net = Mininet(controller=None, switch=None, link=TCLink, autoSetMacs=False)

    h1 = net.addHost("h1", ip="10.0.0.1/24", mac="00:00:00:00:00:01")
    h2 = net.addHost("h2", ip="10.0.0.2/24", mac="00:00:00:00:00:02")

    s1 = net.addSwitch(
        "s1",
        cls=Bmv2GrpcSwitch,
        json_path=json_path,
        grpc_port=50051,
        device_id=1,
    )

    # net.addLink(h1, s1, port2=1)
    # net.addLink(h2, s1, port2=2)
    net.addLink(h1, s1, port2=1, cls=TCLink, bw=100)
    net.addLink(h2, s1, port2=2, cls=TCLink, bw=100) # limit the bw to 100M bps
    

    gcl_path = "/tmp/tsn_gcl.txt"
    
# GCL table for the 8-slot cycle.
# Each entry specifies the egress queue allowed to transmit in that slot.
#
# slot0 -> queue1
# slot1 -> queue2
# slot2 -> queue3
# slot3 -> queue0  # BE / low-priority traffic
# slot4 -> queue1
# slot5 -> queue2
# slot6 -> queue3
# slot7 -> queue0  # BE / low-priority traffic
#
# Notes:
# - Queue IDs are BMv2 internal queue indexes.
# - TSN packets are mapped from qid to queue_idx by:
#     queue_idx = 7 - qid
# - Example:
#     qid=6 -> queue1
#     qid=5 -> queue2
#     qid=4 -> queue3
#     qid=7 -> queue0  # BE / low-priority traffic
# - The GCL is loaded by BMv2 at startup from /tmp/tsn_gcl.txt.
# - Restart BMv2/Mininet after changing this table.
    gcl_table = [1, 2, 3, 0, 1, 2, 3, 0]

    with open(gcl_path, "w") as f:
        f.write(" ".join(str(x) for x in gcl_table) + "\n")

    info(f"*** TSN GCL: {gcl_path} = {gcl_table}\n")

    net.start()
    info("*** BMv2 P4Runtime address: 127.0.0.1:50051, device_id=1\n")
    CLI(net)
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    main()
