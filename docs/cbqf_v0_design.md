# CBQF v0 设计方案：Class-Based Queue Forwarding

> 目标读者：后续执行代码修改的智能体 / 实验实现者  
> 当前阶段：设计方案，不直接改代码  
> 参考基线：CSQF、TCQF、TQF  
> 建议分支：`cbqf-v0` 或 `cbqf`

---

## 1. 设计动机

目前已经完成三个基线机制：

| 机制 | 核心思想 | 优点 | 暴露问题 |
|---|---|---|---|
| CSQF | 源端写入逐跳 slot stack，交换机按 hop_index 取 slot | 路径调度意图明确，P95 稳定 | 源端把每跳 slot 写死，一旦到达相位偏移，容易错过时隙 |
| TCQF | 数据包携带 cycle_tag，交换机本地 remap 到下一服务 cycle | 包头较轻，本地 remap 稳定 | 静态映射表灵活性不足，不同 flow/queue 服务机会不均 |
| TQF | 交换机根据 arrival timestamp 计算 out_slot | 不依赖源端逐跳写死 slot | d1/d2 依赖参数，BE fallback 策略需要额外限制 |

CBQF 的设计目标不是简单再做一种固定 slot 机制，而是吸收三者经验：

```text
用轻量包头表达“流类别与调度需求”，
用交换机本地状态/映射完成队列选择，
用受限 BE fallback 保留低优先级流的发送机会，
同时避免源端把每跳 slot 完全写死。
```

CBQF 可以理解为：

```text
Class-Based Queue Forwarding
= flow/class aware queue selection
+ local cycle/slot state
+ limited BE fallback
```

---

## 2. CBQF v0 的核心假设

CBQF v0 不追求一步到位实现复杂动态调度，而是先实现一个可运行、可对比、可解释的最小版本。

### 2.1 v0 先不做的事情

- 不做 per-flow 在线拥塞控制。
- 不做真正硬件级抢占。
- 不做复杂 P4 register 队列深度反馈。
- 不在包头里写完整逐跳 slot stack。
- 不在 P4 中维护大规模动态状态。

### 2.2 v0 必须做到的事情

- 数据包携带 `class_id`，表达业务类别。
- TSN 与 BE/BG 分队列。
- 交换机根据 `class_id + 本地 slot/cycle` 选择 queue。
- 每个 slot 优先服务 TSN class queue。
- BE/BG 只能在授权 slot 中 fallback。
- 实验结果能与 CSQF、TCQF、TQF 形成清晰对比。

---

## 3. 机制命名与语义

建议命名：

```text
CBQF: Class-Based Queue Forwarding
```

一句话定义：

```text
CBQF 让数据包只携带轻量 class 标签，交换机根据本地 slot/cycle 状态将不同 class 映射到确定性队列，并在授权窗口中允许 BE fallback。
```

与已有机制的边界：

| 机制 | 包头调度信息 | 队列选择主体 | 时间依据 |
|---|---|---|---|
| CSQF | 每跳 slot stack | 源端主导 | 源端规划 |
| TCQF | cycle_tag | 交换机 remap | 本地 cycle |
| TQF | 无固定 schedule，靠 timestamp | 交换机 timestamp 计算 | arrival time |
| CBQF | class_id + optional cycle_hint | 交换机 class map | 本地 slot/cycle |

---

## 4. 包头设计

### 4.1 沿用现有 TSN header 框架

当前项目中的 TSN header 已经是：

```text
next_type: 16 bit
fid      : 16 bit
kind     : 8 bit
cycle_tag: 8 bit
ttl      : 8 bit
flags    : 8 bit
```

CBQF v0 建议尽量不扩大包头，复用字段语义：

| 字段 | CBQF v0 含义 |
|---|---|
| `next_type` | 保留 header chaining |
| `fid` | flow id |
| `kind` | traffic kind，`1=TSN`，`2=BG/BE` |
| `cycle_tag` | 复用为 `class_id` 或 `cycle_hint` |
| `ttl` | 保留 |
| `flags` | debug 字段，记录本地选择的 queue/slot |

推荐 v0 采用：

```text
cycle_tag = class_id
flags     = selected_queue 或 local_slot debug
```

这样不需要修改 Scapy header 长度，也不需要改 parser 的 next_type 逻辑。

### 4.2 class_id 编码

建议 v0 使用 4 个 class：

| class_id | 类型 | 语义 | 示例 flow |
|---:|---|---|---|
| 0 | BE | 背景流 | BG 200/300 |
| 1 | TSN-H | 高优先级 TSN | FID 101/201 |
| 2 | TSN-M | 中优先级 TSN | FID 102/202 |
| 3 | TSN-L | 低优先级 TSN | FID 103/203 |

如果现有发送脚本暂时不方便显式写 class，也可以先用 `fid` 推导：

```text
fid 101 / 201 -> class_id 1
fid 102 / 202 -> class_id 2
fid 103 / 203 -> class_id 3
BG 200 / 300  -> class_id 0
```

但推荐最终由配置文件显式写入：

```json
{
  "fid": 101,
  "kind": "TSN",
  "class_id": 1,
  "period_ms": 40
}
```

---

## 5. 队列设计

当前 BMv2 priority queue 数量为 8，因此 v0 不扩展 `queueing.h`。

建议队列分配：

| queue | 用途 |
|---:|---|
| 0 | BE/BG queue |
| 1 | TSN class 1 primary queue |
| 2 | TSN class 2 primary queue |
| 3 | TSN class 3 primary queue |
| 4 | TSN class 1 secondary / catch-up queue |
| 5 | TSN class 2 secondary / catch-up queue |
| 6 | TSN class 3 secondary / catch-up queue |
| 7 | reserved / debug / emergency |

这样比 TQF 的 `queue 1..7 = slot queue` 更偏 class-based：

```text
TQF: queue 表示时间 slot
CBQF: queue 表示 class + phase group
```

---

## 6. 本地调度状态

CBQF v0 的本地状态不放在 P4 register 中，而由 C++ 调度线程维护/计算。

### 6.1 本地 slot

沿用 TQF 的 pow2 时间设置：

```text
slot_us = 8192
slots_per_cycle = 8
cycle_us = 65536
local_slot = (get_ts().count() >> 13) & 0x7
```

### 6.2 class service map

交换机本地维护一个静态服务表：

```text
slot 0 -> class 1 primary
slot 1 -> class 2 primary
slot 2 -> class 3 primary
slot 3 -> class 1 secondary
slot 4 -> BE fallback window
slot 5 -> class 2 secondary
slot 6 -> class 3 secondary
slot 7 -> BE fallback window
```

对应 queue：

```text
slot 0 -> queue 1
slot 1 -> queue 2
slot 2 -> queue 3
slot 3 -> queue 4
slot 4 -> BE fallback only
slot 5 -> queue 5
slot 6 -> queue 6
slot 7 -> BE fallback only
```

这只是 v0 默认表，可以通过配置文件调整。

### 6.3 为什么不是每个 slot 一个 TSN queue

TQF 中 queue 代表 out_slot，因此容易出现：

```text
arrival_slot 计算正确，但 d1/d2 策略决定尾延迟。
```

CBQF 中 queue 代表 class，因此数据包不是被固定送到某个绝对 slot queue，而是进入 class queue，等待本地 class service window：

```text
packet.class_id = 2
-> enqueue queue2 或 queue5
-> 当前交换机在 class2 服务窗口出队
```

这能弱化“到达必须赶上下一个固定 slot”的要求。

---

## 7. 入队逻辑

### 7.1 P4 入队目标

P4 负责根据 `kind/class_id/fid` 设置 `standard_metadata.priority`。

注意 BMv2 映射：

```text
queue_idx = 7 - priority
```

因此：

| queue_idx | priority |
|---:|---:|
| 0 | 7 |
| 1 | 6 |
| 2 | 5 |
| 3 | 4 |
| 4 | 3 |
| 5 | 2 |
| 6 | 1 |
| 7 | 0 |

### 7.2 v0 入队映射

最小版本可先使用 primary queue：

```text
BE/BG -> queue 0
class 1 -> queue 1
class 2 -> queue 2
class 3 -> queue 3
```

后续增强版再把 late packet 或 overflow packet 映射到 secondary queue：

```text
class 1 catch-up -> queue 4
class 2 catch-up -> queue 5
class 3 catch-up -> queue 6
```

### 7.3 P4 伪代码

```p4
action derive_class_id() {
    if (hdr.tsn.kind == 8w2) {
        local_metadata.class_id = 8w0;
    } else if (hdr.tsn.cycle_tag != 8w0) {
        local_metadata.class_id = hdr.tsn.cycle_tag;
    } else if (hdr.tsn.fid == 16w101 || hdr.tsn.fid == 16w201) {
        local_metadata.class_id = 8w1;
    } else if (hdr.tsn.fid == 16w102 || hdr.tsn.fid == 16w202) {
        local_metadata.class_id = 8w2;
    } else {
        local_metadata.class_id = 8w3;
    }
}

action set_queue_from_class() {
    if (local_metadata.class_id == 8w0) {
        local_metadata.base_queue = 8w0;
        standard_metadata.priority = 3w7;
    } else if (local_metadata.class_id == 8w1) {
        local_metadata.base_queue = 8w1;
        standard_metadata.priority = 3w6;
    } else if (local_metadata.class_id == 8w2) {
        local_metadata.base_queue = 8w2;
        standard_metadata.priority = 3w5;
    } else {
        local_metadata.base_queue = 8w3;
        standard_metadata.priority = 3w4;
    }

    hdr.tsn.flags = local_metadata.base_queue;
}

apply {
    if (hdr.tsn.isValid()) {
        derive_class_id();
        set_queue_from_class();
    } else {
        standard_metadata.priority = 3w7;
    }
}
```

---

## 8. 出队逻辑

### 8.1 C++ 服务表

在 `simple_switch.cpp` 中定义：

```cpp
static const std::array<int, 8> CBQF_GCL =
    {{1, 2, 3, 4, 0, 5, 6, 0}};
```

含义：

```text
0 表示 BE fallback window
1/2/3 表示 primary TSN class queue
4/5/6 表示 secondary TSN class queue
```

### 8.2 出队策略 v0

```text
当前 slot -> target_queue = CBQF_GCL[slot]

if target_queue > 0:
    尝试从 target_queue 出队
    如果为空:
        不立即全局扫描其他 TSN queue
        仅在授权 fallback slot 才尝试 BE

if target_queue == 0:
    尝试从 BE queue 0 出队
```

### 8.3 可选增强：class catch-up

如果 primary queue 空，而对应 secondary queue 有包，可以补发同 class 的 secondary queue：

```text
slot0 queue1 empty -> try queue4
slot1 queue2 empty -> try queue5
slot2 queue3 empty -> try queue6
```

但 v0 建议先不加 catch-up，避免结果难解释。

### 8.4 C++ 伪代码

```cpp
int target_queue = CBQF_GCL[slot_id];
bool popped = false;
bool be_fallback = false;

if (target_queue > 0) {
    popped = try_pop(target_queue);
}

if (!popped && target_queue == 0) {
    popped = try_pop(0);
    be_fallback = popped;
}

if (popped) {
    log("CBQF_DEQUEUE ... slot_id={} target_queue={} be_fallback={}",
        slot_id, target_queue, be_fallback);
}
```

---

## 9. BE/BG 策略

CBQF v0 推荐使用 strict-BE：

```text
BE/BG 固定 queue0
仅 GCL 中 target_queue == 0 的 slot 才允许出队
```

默认：

```text
BE fallback slot = slot 4, slot 7
BE 服务窗口 = 2/8
```

如果 BE 过强：

```text
改成 slot 7 only
```

如果 BE 过弱：

```text
改成 slot 3, slot 7
```

---

## 10. 配置文件设计

新增：

```text
configs/cbqf_6sw_4host.json
scripts/run_test_cbqf.sh
```

配置字段：

```json
{
  "mechanism": "cbqf",
  "cbqf": {
    "enabled": true,
    "slot_us": 8192,
    "slots_per_cycle": 8,
    "cycle_us": 65536,
    "queue_mode": "class_based",
    "be_queue": 0,
    "gcl": [1, 2, 3, 4, 0, 5, 6, 0],
    "classes": {
      "1": {"name": "TSN-H", "primary_queue": 1, "secondary_queue": 4},
      "2": {"name": "TSN-M", "primary_queue": 2, "secondary_queue": 5},
      "3": {"name": "TSN-L", "primary_queue": 3, "secondary_queue": 6}
    }
  }
}
```

flow 中增加：

```json
{
  "fid": 101,
  "kind": "TSN",
  "class_id": 1,
  "slot": 0
}
```

---

## 11. 需要修改的文件

### 11.1 P4

```text
p4src/include/custom_headers.p4
p4src/include/parsers.p4
p4src/include/tsn_queue.p4
```

建议：

- `custom_headers.p4` 增加 `class_id` local metadata。
- 不扩展 TSN header，复用 `cycle_tag` 为 class_id。
- `tsn_queue.p4` 新增 `derive_class_id()` 和 `set_queue_from_class()`。
- `parsers.p4` 不需要大改，只要保留当前 TSN parser。

### 11.2 发送/接收脚本

```text
traffic/send_from_json.py
traffic/recv_from_json.py
scripts/slot_stack_summary.py
scripts/run_test_simple.sh
```

建议：

- `send_from_json.py` 在 `mechanism == "cbqf"` 时把 `class_id` 写入 `cycle_tag`。
- `recv_from_json.py` 保持兼容，读取 `cycle_tag` 可显示为 `class_id`。
- summary 输出中将 `cycle_tag` 标注为 `class/class_id`。

### 11.3 BMv2

```text
bmv2-patches/simple_switch.cpp
```

建议：

- 新增 `CBQF_GCL`。
- 日志关键词使用 `CBQF_ENQUEUE` / `CBQF_DEQUEUE`。
- 出队逻辑按 class service map 服务 queue。
- 时间源继续使用 `get_ts().count()`，不要回到 `tsn_monotonic_us()`。

### 11.4 配置和脚本

```text
configs/cbqf_6sw_4host.json
scripts/run_test_cbqf.sh
```

---

## 12. 最小实现路线

### Step 1：新建分支

```bash
git switch -c cbqf-v0
```

### Step 2：复制 TQF strict-BE 作为起点

原因：

```text
TQF strict-BE 已经完成：
- TSN/BE 分队列
- queue0 BE
- limited BE fallback
- get_ts().count() 时间源
```

CBQF v0 可以直接从该版本演进。

### Step 3：P4 改为 class-based queue

将：

```text
arrival_slot -> out_slot -> queue
```

改为：

```text
class_id -> queue
```

### Step 4：C++ 改为 CBQF_GCL

将 TQF 的 slot queue 出队：

```text
slot -> queue
```

改为 CBQF class service：

```text
slot -> class queue
```

### Step 5：新增配置与脚本

新增 `cbqf_6sw_4host.json` 与 `run_test_cbqf.sh`。

### Step 6：编译与测试

```bash
p4c-bm2-ss --arch v1model \
  -o build/tsn_basic.json \
  --p4runtime-files build/tsn_basic.p4info.txt \
  p4src/tsn_basic.p4

cd ~/Workspace/P4/behavioral-model-tqf-pow2/behavioral-model
make -C targets/simple_switch -j1
make -C targets/simple_switch_grpc -j1

cd ~/tsn-lab
bash scripts/run_test_cbqf.sh
```

---

## 13. 预期结果

理想情况下：

| 指标 | 预期 |
|---|---|
| TSN P50 | 低于 TCQF，接近或略高于 TQF strict-BE |
| TSN P95 | 低于默认 TCQF，接近 CSQF/TQF strict-BE |
| TSN 异常率 | 约 0.5%-1.0% |
| BG P50 | 高于 TQF all-slot fallback |
| BG 异常率 | 明显高于 TSN |
| 路径偏置 | h1->h3 与 h2->h4 接近 |

如果结果中某个 class 明显更差，需要检查：

```text
CBQF_GCL 是否给不同 class 的服务窗口不均
flow 到 class 的映射是否合理
BE fallback 是否过强
secondary queue 是否需要启用
```

---

## 14. 与三个基线的对比口径

| 机制 | 主对比指标 |
|---|---|
| CSQF v2 | 源端显式逐跳 slot 的 P95/P99 与异常率 |
| TCQF | cycle_tag remap 的稳定性与头部简洁性 |
| TQF strict-BE | timestamp-to-slot + limited BE fallback 的 TSN/BE 隔离 |
| CBQF v0 | class-based local queue scheduling 的灵活性与稳定性 |

报告中建议强调：

```text
CBQF 不是替代所有机制，而是吸收它们的长处：
- 不像 CSQF 那样写死逐跳 slot
- 不像 TCQF 那样只依赖静态 cycle remap
- 不像 TQF 那样只由 arrival timestamp 决定 out_slot
```

---

## 15. 风险与注意事项

1. class service map 如果设计不均，会重现 TCQF strict-BE 的 queue fairness 问题。

2. 如果只用 primary queue，某些 class 在负载高时可能尾延迟变大。

3. 如果启用 secondary/catch-up queue，机制解释会更复杂，建议 v1 再做。

4. 不建议一开始扩展队列数量到 16。先用 8 队列跑通 v0。

5. 不建议把 timestamp slot 与 class queue 同时作为强约束，否则会退化成 TQF 的参数问题。

---

## 16. v0 最终推荐方案

```text
Header:
  reuse cycle_tag as class_id

P4 ingress:
  kind/fid/class_id -> queue 0..3

C++ egress:
  local_slot -> CBQF_GCL -> target class queue
  target queue first
  BE only in queue0 service slot

GCL:
  [1, 2, 3, 4, 0, 5, 6, 0]

BE:
  queue0 only
  slot4/slot7 service

First experiment:
  configs/cbqf_6sw_4host.json
  scripts/run_test_cbqf.sh
```

该方案是最小可实现版本，重点验证：

```text
class-based local queue scheduling 是否能在不写死逐跳 slot 的情况下，
获得接近 CSQF/TQF strict-BE 的 TSN 稳定性，
同时保留清晰的 BE 隔离语义。
```
