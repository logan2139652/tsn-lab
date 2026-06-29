# TSN 仿真实验代码备份

本项目基于 BMv2 + Mininet + P4Runtime 实现 TSN 确定性调度仿真。

## 目录
- tsn-lab/ — 实验主目录（P4源码、Python控制器、拓扑配置、流量脚本、自动化测试）
- bmv2-src/ — 修改过的 BMv2 源码
  - simple_switch.h/cpp — 优先级队列 + GCL 调度日志
  - queueing.h — try_pop_back_priority 出队逻辑

## BMv2 编译命令
cd ~/Workspace/P4/behavioral-model
make -C targets/simple_switch clean && make -C targets/simple_switch -j$(nproc)
make -C targets/simple_switch_grpc clean && make -C targets/simple_switch_grpc -j$(nproc)
sudo make -C targets/simple_switch_grpc install && sudo ldconfig

## 环境
- Ubuntu 20.04.6
- p4c 1.2.2.1
- BMv2 1.15.0
- Mininet 2.3.1b1
