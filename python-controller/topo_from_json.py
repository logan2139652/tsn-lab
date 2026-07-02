#!/usr/bin/env python3

from mininet.net import Mininet
from mininet.node import Switch
from mininet.cli import CLI
from mininet.log import setLogLevel, info
from mininet.link import TCLink
import argparse
import json
import os
import signal


class Bmv2GrpcSwitch(Switch):
    def __init__(self, name, json_path, grpc_port, device_id,
                 gcl_path, phase_path, **kwargs):
        super().__init__(name, **kwargs)
        self.json_path = json_path
        self.grpc_port = grpc_port
        self.device_id = device_id
        self.gcl_path = gcl_path
        self.phase_path = phase_path
        self.pid_file = f"/tmp/{name}-simple-switch-grpc.pid"
        self.log_file = f"/tmp/{name}-simple-switch-grpc.log"
        self.stdout_file = f"/tmp/{name}-stdout.log"

    def start(self, controllers):
        intf_args = []
        for port, intf in self.intfs.items():
            if port == 0:
                continue
            intf_args.append(f"-i {port}@{intf.name}")

        cmd = (
            f"TSN_GCL_PATH={self.gcl_path} "
            f"TSN_PHASE_PATH={self.phase_path} "
            f"simple_switch_grpc "
            f"--device-id {self.device_id} "
            f"--log-file {self.log_file} "
            f"-L info --log-flush "
            f"{' '.join(intf_args)} "
            f"{self.json_path} "
            f"-- "
            f"--grpc-server-addr 0.0.0.0:{self.grpc_port} "
            f"> {self.stdout_file} 2>&1 & echo $! > {self.pid_file}"
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


def write_gcl(path, table):
    with open(path, "w") as f:
        f.write(" ".join(str(x) for x in table) + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--config",
        default="/home/aaa/tsn-lab/configs/tsn_2sw.json",
    )
    args = parser.parse_args()

    with open(args.config) as f:
        cfg = json.load(f)

    json_path = cfg["p4"]["bmv2_json"]

    for sw_name, sw_cfg in cfg["switches"].items():
        write_gcl(sw_cfg["gcl_path"], sw_cfg["gcl"])
        if os.path.exists(sw_cfg["phase_path"]):
            os.remove(sw_cfg["phase_path"])
        info(f"*** {sw_name} GCL: {sw_cfg['gcl_path']} = {sw_cfg['gcl']}\n")

    net = Mininet(controller=None, switch=None, link=TCLink, autoSetMacs=False)
    nodes = {}

    for host_name, host_cfg in cfg["hosts"].items():
        nodes[host_name] = net.addHost(
            host_name,
            ip=host_cfg["ip"],
            mac=host_cfg["mac"],
        )

    for sw_name, sw_cfg in cfg["switches"].items():
        nodes[sw_name] = net.addSwitch(
            sw_name,
            cls=Bmv2GrpcSwitch,
            json_path=json_path,
            grpc_port=sw_cfg["grpc_port"],
            device_id=sw_cfg["device_id"],
            gcl_path=sw_cfg["gcl_path"],
            phase_path=sw_cfg["phase_path"],
        )

    for link in cfg["links"]:
        kwargs = {}
        if "port1" in link:
            kwargs["port1"] = link["port1"]
        if "port2" in link:
            kwargs["port2"] = link["port2"]
        if "bw" in link:
            kwargs["bw"] = link["bw"]

        net.addLink(nodes[link["node1"]], nodes[link["node2"]], **kwargs)

    net.start()
    net.staticArp()

    info("*** P4Runtime endpoints:\n")
    for sw_name, sw_cfg in cfg["switches"].items():
        info(
            f"***   {sw_name}: 127.0.0.1:{sw_cfg['grpc_port']} "
            f"device_id={sw_cfg['device_id']} "
            f"phase={sw_cfg['phase_path']}\n"
        )

    CLI(net)
    net.stop()


if __name__ == "__main__":
    setLogLevel("info")
    main()
