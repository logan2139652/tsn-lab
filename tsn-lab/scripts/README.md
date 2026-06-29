# TSN Lab — 脚本说明

本目录及子目录存放 TSN 实验的全部 Shell 脚本，按功能模块分类。

> **最近整理**：将原先散落在根目录的 9 个脚本归类迁移，合并了 `send_from_json` / `send_from_json_new` 和 `recv_from_json` / `recv_from_json_new` 两对重复脚本。

---

## 目录结构

```
scripts/
├── README.md                  ← 本文档
│
├── env.sh                     # 环境变量（所有脚本的基础依赖）
│
├── start_onos.sh              # ▸ ONOS 控制器
├── stop_onos.sh               # ▸ ONOS 控制器
├── onos_cli.sh                # ▸ ONOS 控制器
├── check_onos.sh              # ▸ ONOS 控制器
│
├── start_mininet.sh           # ▸ Mininet（ONOS + BMv2 模式）
├── clean_mininet.sh           # ▸ Mininet 清理
│
├── set_queue_rate.sh          # ▸ BMv2 运行时配置
│
├── analyze_tsn_queue_log.py   # ▸ 日志分析工具（Python）
│
└── traffic/                   # ▸ 流量实验（发送 / 接收 / 抓包）
    ├── send_flows.sh           #    ─ GCL 对齐发送
    ├── send_aligned.sh         #    ─ GCL 对齐发送（相位同步）
    ├── send_json.sh            #    ─ JSON 驱动发送
    ├── recv_delay.sh           #    ─ 接收 + 延迟统计
    ├── recv_json.sh            #    ─ JSON 驱动接收
    └── capture_tsn.sh          #    ─ 抓包分析

p4src/
└── bmv2-compile.sh            # P4 编译（Docker）
```

---

## 一、环境与基础设施

### `env.sh`

**所有脚本的公共环境变量**。被 `start_onos.sh`、`onos_cli.sh` 等 `source` 引入。

```bash
source scripts/env.sh
```

| 变量 | 值 | 说明 |
|------|----|------|
| `JAVA_HOME` | `/usr/lib/jvm/java-11-openjdk-amd64` | Java 运行环境 |
| `ONOS_HOME` | `~/onos/onos-2.7.0` | ONOS 安装目录 |
| `ONOS_ROOT` | `~/onos/onos-src-2.7.0` | ONOS 源码目录 |
| `ONOS_WEB_USER/PASS` | `onos / rocks` | Web UI 登录凭证 |
| `ONOS_SSH_USER/PORT` | `karaf / 8101` | CLI 登录信息 |
| `PIPECONF_ID` | `org.onosproject.pipelines.basic` | Pipeconf 标识 |

---

## 二、ONOS 控制器

### `start_onos.sh`

启动 ONOS 控制器，等待 60 秒就绪后输出状态。

```bash
bash scripts/start_onos.sh
```

### `stop_onos.sh`

停止 ONOS 控制器。

```bash
bash scripts/stop_onos.sh
```

### `onos_cli.sh`

打开 ONOS Karaf CLI 交互终端。

```bash
bash scripts/onos_cli.sh
# 密码: karaf
```

### `check_onos.sh`

快速检查 ONOS 运行状态、已连接设备和网络配置。

```bash
bash scripts/check_onos.sh
```

---

## 三、Mininet 管理

### `start_mininet.sh`

以 ONOS-BMv2 模式启动单交换机 Mininet 拓扑（配合 ONOS 使用）。

```bash
bash scripts/start_mininet.sh
```

> 注意：此脚本使用 `~onos/tools/dev/mininet/bmv2.py`，需要 `ONOS_ROOT` 已设置。

### `clean_mininet.sh`

清理残留的 Mininet 环境，并列出仍在运行的 `simple_switch_grpc` 进程。

```bash
bash scripts/clean_mininet.sh
```

常用组合（启动实验前一键清理）：

```bash
bash scripts/clean_mininet.sh
sudo rm -f /tmp/s*-simple-switch-grpc.log.txt /tmp/tsn_gcl_*.txt /tmp/tsn_phase_*.txt
```

---

## 四、BMv2 运行时配置

### `set_queue_rate.sh`

设置 BMv2 交换机出口队列速率，用于限速测试。

```bash
bash scripts/set_queue_rate.sh [port] [rate_pps]
```

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `port` | `2` | 交换机端口号 |
| `rate_pps` | `50` | 队列限速（包/秒） |

原理：调用 `simple_switch_CLI` 的 `set_queue_rate` 命令。

---

## 五、流量实验（`scripts/traffic/`）

### 发送脚本

| 脚本 | 驱动方式 | 说明 |
|------|----------|------|
| `send_json.sh` | JSON 配置 | 从 `configs/*.json` 读取流定义发送 |
| `send_flows.sh` | 参数 | GCL 时隙对齐发送（固定参数版） |
| `send_aligned.sh` | 参数 + 同步 | GCL 对齐发送，主动等待相位同步信号 |

---

#### `send_json.sh`

从拓扑 JSON 配置文件读取 TSN 流并发送。支持传参指定配置文件。

```bash
# 默认使用 tsn_6sw_4host.json
bash scripts/traffic/send_json.sh

# 指定其他配置
bash scripts/traffic/send_json.sh ~/tsn-lab/configs/tsn_2sw.json
```

底层调用：`python3 traffic/send_from_json.py`

---

#### `send_flows.sh`

发送 GCL 时隙对齐的多条 TSN 流 + 背景流。

```bash
bash scripts/traffic/send_flows.sh
```

| 参数 | 值 | 说明 |
|------|----|------|
| `IFACE` | `h1-eth0` | 发送网卡 |
| `DURATION` | `10` | 持续时长（秒） |
| `TSN_INTER` | `0.02` | TSN 流发送间隔（秒） |
| `BG_PPS` | `200` | 背景流速率（包/秒） |
| `TSN_PAYLOAD` | `300` | TSN 包载荷（字节） |
| `BG_PAYLOAD` | `1200` | 背景包载荷（字节） |

底层调用：`python3 traffic/send_gcl_flows.py`

---

#### `send_aligned.sh`

发送 GCL 相位同步对齐的 TSN 流，主动等待主同步信号。

```bash
bash scripts/traffic/send_aligned.sh
```

| 参数 | 值 | 说明 |
|------|----|------|
| `IFACE` | `h1-eth0` | 发送网卡 |
| `DURATION` | `10` | 持续时长（秒） |
| `LEAD_US` | `3000` | 前置提前量（微秒） |
| `PHASE_OFFSET_US` | `0` | 全局相位偏移（微秒） |
| `BG_PPS` | `100` | 背景流速率 |
| `TSN_PAYLOAD` | `300` | TSN 载荷 |
| `BG_PAYLOAD` | `1200` | 背景载荷 |
| `SYNC_FILE` | `/tmp/tsn_phase.txt` | 同步信号文件 |

底层调用：`python3 traffic/send_gcl_aligned.py`

---

### 接收脚本

| 脚本 | 说明 |
|------|------|
| `recv_json.sh` | 从 JSON 配置读取接收参数，监听多个流 |
| `recv_delay.sh` | 单接口接收，统计端到端延迟 |

---

#### `recv_json.sh`

从拓扑 JSON 配置读取接收参数，自动监听所有目标流。

```bash
# 默认使用 tsn_6sw_4host.json
bash scripts/traffic/recv_json.sh

# 指定其他配置
bash scripts/traffic/recv_json.sh ~/tsn-lab/configs/tsn_2sw.json
```

底层调用：`python3 traffic/recv_from_json.py`

---

#### `recv_delay.sh`

监听指定接口，计算并输出 TSN 包端到端延迟统计。

```bash
bash scripts/traffic/recv_delay.sh
```

| 参数 | 值 | 说明 |
|------|----|------|
| `IFACE` | `h2-eth0` | 监听网卡 |
| `DURATION` | `30` | 监听时长（秒） |
| `CSV` | `/tmp/tsn_recv_delay.csv` | 延迟数据输出 |

底层调用：`python3 traffic/recv_tsn_delay.py`

---

### 抓包分析

#### `capture_tsn.sh`

在 h2 上抓取 TSN 协议包（EtherType 0x1234），用于协议调试。

```bash
bash scripts/traffic/capture_tsn.sh
```

底层调用：`tcpdump -i h2-eth0 -nn -e -XX ether proto 0x1234`

---

## 六、P4 编译

### `p4src/bmv2-compile.sh`

使用 Docker 容器编译 P4 程序，生成 BMv2 JSON 和 P4Info。

```bash
cd ~/tsn-lab/p4src
bash bmv2-compile.sh <profile> [flags]

# 示例
bash bmv2-compile.sh tsn_basic
bash bmv2-compile.sh tsn_basic --std p4-16
```

| 参数 | 说明 |
|------|------|
| `<profile>` | P4 文件名（不含 `.p4` 后缀） |
| `[flags]` | 传递给 `p4c-bm2-ss` 的额外参数 |

输出：
- `build/<profile>.json` — 交换机数据平面配置
- `build/<profile>_p4info.txt` — P4Runtime API 信息
- `build/<profile>_pp.p4` — 预处理后的 P4 源码（调试用）

---

## 七、典型实验工作流

### 方式 A：Python 拓扑 + GCL 控制器（推荐，`tsn_6sw_4host.json`）

```bash
# 1. 清理
bash scripts/clean_mininet.sh
sudo rm -f /tmp/s*-simple-switch-grpc.log.txt /tmp/tsn_gcl_*.txt /tmp/tsn_phase_*.txt

# 2. 终端1 — 启动 6 交换机 Mininet + simple_switch_grpc
sudo ~/tsn-lab/python-controller/topo_from_json.py

# 3. 终端2 — 查看交换机日志
tail -f /tmp/s1-simple-switch-grpc.log.txt

# 4. 终端3 — 运行 GCL 控制器
~/tsn-lab/python-controller/controller_from_json.py

# 5. Mininet 内接收端
h3: bash scripts/traffic/recv_json.sh
h4: bash scripts/traffic/recv_json.sh

# 6. Mininet 内发送端
h1: bash scripts/traffic/send_json.sh
h2: bash scripts/traffic/send_json.sh
```

### 方式 B：单交换机基础验证

```bash
# 终端1 — 启动 topo
sudo ~/tsn-lab/python-controller/topo.py

# 终端3 — 运行控制器
~/tsn-lab/python-controller/controller_from_json.py

# Mininet 内
h2: bash scripts/traffic/recv_delay.sh
h1: bash scripts/traffic/send_aligned.sh
```

### 方式 C：ONOS 模式（历史保留）

```bash
bash scripts/start_onos.sh          # 等 60 秒
bash scripts/start_mininet.sh
bash scripts/onos_cli.sh            # 手动下发流表
bash scripts/check_onos.sh          # 确认设备上线
```

### P4 代码修改后重编译

```bash
cd ~/tsn-lab/p4src
bash bmv2-compile.sh tsn_basic      # P4 → JSON
# 如果修改了 BMv2 源码：
cd ~/Workspace/P4/behavioral-model
make -C targets/simple_switch_grpc -j$(nproc)
sudo make -C targets/simple_switch_grpc install
sudo ldconfig
```

---

## 八、常用调试

```bash
# 查看 GCL 相位同步状态
cat /tmp/tsn_phase.txt

# 查看时隙调度日志
tail -f /tmp/tsn_gcl_s1.txt

# 查看接收延迟 CSV
cat /tmp/tsn_recv_delay.csv

# 分析延迟日志
python3 scripts/analyze_tsn_queue_log.py /tmp/tsn_gcl_s1.txt

# 限速压测
bash scripts/set_queue_rate.sh 2 30
```

---

## 九、整理记录

| 日期 | 变更 |
|------|------|
| 2026-06-25 | 将根目录 7 个脚本迁入 `scripts/traffic/`；合并 `send_from_json`（新旧）和 `recv_from_json`（新旧）；`set_queue_rate.sh` 迁入 `scripts/`；根目录 sh 文件清零 |

---

## 十、一键全自动测试

### `run_full_test.sh`

一键完成完整实验流程，无需手工分步操作。

```bash
# 默认配置（6 交换机 4 主机）
bash scripts/run_full_test.sh

# 指定配置文件 + 流量时长
bash scripts/run_full_test.sh --config configs/tsn_2sw.json --duration 15
```

### 自动执行步骤

| 步骤 | 内容 |
|------|------|
| 1/7 | 清理旧进程/文件 |
| 2/7 | 启动 `topo_from_json_bg.py`（后台模式） |
| 3/7 | 轮询等待所有交换机 gRPC 端口就绪 |
| 4/7 | 运行 `controller_from_json.py` 下发流表 |
| 5/7 | 启动 h3、h4 接收端（`ip netns exec`） |
| 6/7 | 启动 h1、h2 发送端 |
| 7/7 | 等待完成 → 延迟统计 → 异常检测 → 按需检查交换机日志 |

### 输出

- 测试结果汇总到 `/tmp/tsn_test_<时间戳>/`
- 包含每个 session 的 CSV + 收发 stdout 日志 + 交换机日志（有异常时）
- 退出码：0 = 通过，1 = 有异常

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--config` | `configs/tsn_6sw_4host.json` | 拓扑配置文件 |
| `--duration` | `10` | 每个 session 流量持续秒数 |
| `--verbose` / `-v` | 关 | 详细输出 |

### 新增文件

| 文件 | 说明 |
|------|------|
| `python-controller/topo_from_json_bg.py` | topo 后台变体，`--duration N` 自动运行 |
| `scripts/run_full_test.sh` | 全自动编排脚本 |

### 注意事项

- 需要 `sudo`（Mininet + `ip netns exec` 均需 root）
- 测试期间请勿关闭终端
- Ctrl+C 会触发自动清理（trap EXIT）


## 十、一键全自动测试

### `run_full_test.sh`

一键完成完整实验流程，无需手工分步操作。

```bash
# 默认配置（6 交换机 4 主机）
bash scripts/run_full_test.sh

# 指定配置文件 + 流量时长
bash scripts/run_full_test.sh --config configs/tsn_2sw.json --duration 15
```

### 自动执行步骤

| 步骤 | 内容 |
|------|------|
| 1/7 | 清理旧进程/文件 |
| 2/7 | 启动 `topo_from_json_bg.py`（后台模式） |
| 3/7 | 轮询等待所有交换机 gRPC 端口就绪 |
| 4/7 | 运行 `controller_from_json.py` 下发流表 |
| 5/7 | 启动 h3、h4 接收端 (`ip netns exec`) |
| 6/7 | 启动 h1、h2 发送端 |
| 7/7 | 等待完成 → 延迟统计 → 异常检测 → 按需检查交换机日志 |

### 输出

- 测试结果汇总到 `/tmp/tsn_test_<时间戳>/`
- 包含每个 session 的 CSV + 收发 stdout 日志 + 交换机日志（有异常时）
- 退出码：0 = 通过，1 = 有异常

### 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--config` | `configs/tsn_6sw_4host.json` | 拓扑配置文件 |
| `--duration` | `10` | 每个 session 流量持续秒数 |
| `--verbose` / `-v` | 关 | 详细输出 |

### 新增文件

| 文件 | 说明 |
|------|------|
| `python-controller/topo_from_json_bg.py` | topo 后台变体，`--duration N` 自动运行 |
| `scripts/run_full_test.sh` | 全自动编排脚本 |

### 注意事项

- 需要 `sudo`（Mininet + `ip netns exec` 均需 root）
- 测试期间请勿关闭终端
- Ctrl+C 会触发自动清理（trap EXIT）
