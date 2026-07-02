# CSQF v1 实验方案：基于 cycle_id + qid 的周期感知入队机制

## 1. 当前 baseline 状态

当前系统已经实现了一个基础确定性转发 baseline：

```text
TSN packet -> P4 parser -> qid -> standard_metadata.priority
           -> BMv2 priority queue -> GCL slot release
```

当前核心逻辑是：

```text
qid -> queue
```

例如：

```text
qid=6 -> queue 1
qid=5 -> queue 2
qid=4 -> queue 3
BG    -> queue 0
```

当前 baseline 的实验现象是：

```text
DROP = 0
P95/P99 大多数情况下满足预期
但仍有少量 TSN 包出现 >60ms 的尾部异常
```

这说明系统主体转发路径和调度逻辑是有效的，但少量包可能因为软件调度抖动、发送相位偏差或 gate 边界错过，导致多等待一个或多个调度窗口。

## 2. 当前 baseline 的问题

当前机制只根据 `qid` 映射队列：

```text
qid -> queue
```

这会带来一个问题：同一个 `qid` 的包，不管它属于哪个周期，都会进入同一个队列。

例如：

```text
cycle 0 的 qid=6 包 -> queue 1
cycle 1 的 qid=6 包 -> queue 1
cycle 2 的 qid=6 包 -> queue 1
```

如果某个包因为抖动晚到，它可能已经不属于当前调度周期，但仍然进入当前 qid 对应的队列。这样当前周期、下一周期甚至更后周期的包可能混在同一个队列里。

结果是：

```text
包进入了正确业务队列，但不一定进入了正确周期队列。
```

这可能导致：

```text
包错过当前 gate
包等待下一次 queue release
尾部时延增大
MAX/P99 出现异常
```

## 3. 引入 cycle_id 的核心逻辑

新的思路是：在数据包中加入 `cycle_id`，让数据包不单单根据 `qid` 映射入队，而是在 `qid` 和 `cycle_id` 的联合下入队。

核心逻辑从：

```text
qid -> queue
```

升级为：

```text
(qid, cycle_id) -> queue
```

这样做的意义是：

```text
同一个 qid 的包，可能在不同 cycle 到达；
如果只根据 qid 入队，包可能被映射到不属于它的 cycle 的队列中转发；
加入 cycle_id 后，交换机可以区分“这是哪个周期的 qid=6 包”，从而把它放到对应周期队列中。
```

也就是说：

```text
qid 负责表示业务类别或优先级；
cycle_id 负责表示调度周期归属；
qid + cycle_id 共同决定最终队列。
```

## 4. 实例解释

假设仍然有三类 TSN 流：

```text
qid=6: 高优先级 TSN flow
qid=5: 中优先级 TSN flow
qid=4: 低优先级 TSN flow
```

baseline 中的映射是：

```text
qid=6 -> queue 1
qid=5 -> queue 2
qid=4 -> queue 3
```

这意味着所有 `qid=6` 的包都会进入 `queue 1`。

CSQF v1 中，将队列分为两个 cycle group：

```text
cycle group 0:
  qid=6 -> queue 1
  qid=5 -> queue 2
  qid=4 -> queue 3

cycle group 1:
  qid=6 -> queue 4
  qid=5 -> queue 5
  qid=4 -> queue 6

background:
  BG -> queue 0
```

此时映射变成：

```text
qid=6, cycle_id=0 -> queue 1
qid=6, cycle_id=1 -> queue 4

qid=5, cycle_id=0 -> queue 2
qid=5, cycle_id=1 -> queue 5

qid=4, cycle_id=0 -> queue 3
qid=4, cycle_id=1 -> queue 6
```

### 例子：同一个 qid 在不同周期到达

假设有两个 `qid=6` 的包：

```text
packet A:
  qid=6
  cycle_id=0

packet B:
  qid=6
  cycle_id=1
```

在 baseline 中：

```text
packet A -> queue 1
packet B -> queue 1
```

两个包混在同一个队列中。

在 CSQF v1 中：

```text
packet A -> queue 1
packet B -> queue 4
```

两个包进入不同周期队列。

这样交换机在调度时可以做到：

```text
当前周期释放 cycle group 0 的队列；
下一周期释放 cycle group 1 的队列。
```

这减少了不同周期的数据包互相污染的可能性。

## 5. CSQF v1 设计

CSQF v1 是一个最小可验证版本，目标不是一次实现完整论文级机制，而是验证：

```text
cycle-aware queue 是否能降低 TSN 尾部异常率。
```

### 5.1 数据包头部

建议扩展 TSN header：

```text
fid       # flow id
qid       # traffic class / queue id
cycle_id  # target cycle group, 0 or 1
flags     # reserved
```

如果为了减少 P4 结构改动，也可以复用 `flags` 的最低 bit：

```text
cycle_id = flags & 0x1
```

但实验阶段建议显式加入 `cycle_id` 字段，便于调试和日志分析。

### 5.2 P4 入队映射

P4 ingress 解析 `qid` 和 `cycle_id` 后，设置 `standard_metadata.priority`。

当前 BMv2 映射关系是：

```text
queue_idx = 7 - priority
```

因此可以设计：

```text
cycle_id=0:
  qid=6 -> priority=6 -> queue_idx=1
  qid=5 -> priority=5 -> queue_idx=2
  qid=4 -> priority=4 -> queue_idx=3

cycle_id=1:
  qid=6 -> priority=3 -> queue_idx=4
  qid=5 -> priority=2 -> queue_idx=5
  qid=4 -> priority=1 -> queue_idx=6

background:
  qid=7 -> priority=7 -> queue_idx=0
```

### 5.3 BMv2 scheduler

baseline scheduler 是：

```text
当前 slot 允许某个 queue 出队
```

CSQF v1 可以改成：

```text
当前 cycle group = current_cycle % 2

如果 cycle group = 0:
  release queue 1/2/3

如果 cycle group = 1:
  release queue 4/5/6

BG:
  release queue 0
```

换句话说，scheduler 不再只看 slot，也看当前 cycle group。

### 5.4 发送端

`send_from_json.py` 需要在构造 TSN header 时写入 `cycle_id`。

基本逻辑：

```text
target_cycle = 当前发送目标周期
cycle_id = target_cycle % 2
```

然后写入包头：

```text
TSN(fid, qid, cycle_id, flags)
```

### 5.5 接收端

`recv_from_json.py` 需要解析并记录 `cycle_id`，建议 CSV 增加字段：

```text
cycle_id
```

这样后续可以分析：

```text
异常包是否集中在某个 cycle_id；
某些 cycle group 是否更容易出现尾部异常。
```

## 6. 与 SR routing 的区别

CSQF 不一定像 SR routing 那样，把路径上所有 hop 的 id 都写在发送端，然后每跳 pop 一个标签。

SR routing 更关注：

```text
路径选择 / 下一跳 segment
```

CSQF 更关注：

```text
周期队列 / 出队周期 / 调度窗口
```

典型 CSQF 更倾向于：

```text
包头携带 flow/timing 信息；
每跳交换机根据本地周期、本地 offset、flow 配置决定目标 cycle queue。
```

也就是说，典型逻辑是：

```text
target_cycle = local_current_cycle + per_hop_offset
queue = f(qid, target_cycle)
```

其中 `per_hop_offset` 可以由控制器下发到交换机，而不一定写在包头里。

当然，实验上也可以设计一个 SR-like schedule stack：

```text
cycle_stack = [cycle_s1, cycle_s2, cycle_s5, cycle_s6]
```

每一跳读取自己的 cycle id。但这个机制更像：

```text
source-routed schedule
```

它不适合作为第一个 CSQF 原型。建议后续作为 v3 或扩展机制再考虑。

## 7. 实验目标

当前 baseline 的观测结果：

```text
TSN DROP = 0
P95/P99 基本满足预期
但 TSN anomaly >60ms 仍有约 0.4%-0.6%
```

CSQF v1 的目标：

```text
保持 DROP = 0
保持 P95/P99 不明显恶化
降低 TSN anomaly >60ms 的数量
降低 MAX delay
```

建议对比指标：

```text
AVG(us)
P50(us)
P95(us)
P99(us)
MAX(us)
DROP(%)
ANOMALY > 60000us
```

## 8. 需要修改的模块

最小实现路径：

```text
1. 修改 tsn_basic.p4
   - TSN header 增加 cycle_id
   - ingress 中根据 qid + cycle_id 设置 priority

2. 修改 send_from_json.py
   - 计算 cycle_id
   - 发包时写入 cycle_id

3. 修改 recv_from_json.py
   - 解析 cycle_id
   - CSV 输出 cycle_id

4. 修改 simple_switch.cpp
   - scheduler 支持 cycle group
   - 当前 cycle group 控制 queue 1/2/3 或 queue 4/5/6 出队

5. 修改配置文件
   - 增加 mode: csqf
   - 增加 cycle_groups 或 queue_mapping

6. 修改 run_test_simple.sh
   - 输出 CSQF 相关统计
   - 统计 anomaly by cycle_id
```

## 9. 分阶段实现建议

### CSQF v1：header-driven cycle queue

```text
包头携带 cycle_id
P4 根据 qid + cycle_id 入队
BMv2 scheduler 根据 current_cycle % 2 释放 queue group
```

目标：

```text
验证 cycle-aware queue 是否降低尾部异常。
```

### CSQF v2：per-hop offset

```text
包头携带 base_cycle
每跳根据本地 offset 计算 target_cycle
queue = f(qid, target_cycle)
```

目标：

```text
更接近真实 CSQF，每跳本地控制周期偏移。
```

### CSQF v3：source-routed schedule stack

```text
包头携带每跳 cycle schedule
交换机读取自己的 cycle id
```

目标：

```text
探索 SR-like 确定性调度机制。
```

## 10. 一句话总结

当前 baseline 是：

```text
qid-aware queue
```

CSQF v1 要升级为：

```text
qid + cycle_id-aware queue
```

这样同一个业务等级的包，也能根据所属周期进入不同队列，从而减少不同周期包混队导致的调度失败和尾部异常。
