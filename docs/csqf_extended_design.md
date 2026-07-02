# CSQF 扩展机制设计：从 qid+cycle_id 入队到 SR-like 多跳调度

## 1. 当前阶段的核心修改

当前修改可以概括为一句话：

```text
在原来只根据 qid 入队的基础上，增加 cycle_id，使数据包根据 qid + cycle_id 联合映射到不同队列。
```

原始 baseline 的逻辑是：

```text
packet -> parse qid -> map qid to queue -> BMv2 scheduler release queue
```

也就是：

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

这种设计的问题是：同一个 `qid` 的包，不管它属于哪个调度周期，都会进入同一个队列。

例如：

```text
cycle 0 的 qid=6 packet -> queue 1
cycle 1 的 qid=6 packet -> queue 1
cycle 2 的 qid=6 packet -> queue 1
```

如果一个包因为发送端抖动、Linux 调度抖动、BMv2 处理抖动或 gate 边界错过而晚到，它仍然会被放进原来的 `qid` 队列。这样就会出现一个现象：

```text
包进入了正确的业务优先级队列，但不一定进入了正确的周期队列。
```

这会导致不同周期的数据包混在同一个队列中，进而可能出现：

```text
1. 当前周期应该发送的包被晚到包挤占；
2. 晚到包被错误地在当前周期释放；
3. 包错过当前 gate 后多等一个或多个周期；
4. P95/P99 仍然较好，但 MAX 出现长尾异常。
```

因此，CSQF v1 的第一步不是直接做完整的 SR routing，而是先把队列从：

```text
qid-aware queue
```

扩展为：

```text
qid + cycle_id-aware queue
```

## 2. qid + cycle_id 的入队逻辑

### 2.1 字段含义

建议在 TSN header 中至少加入：

```text
fid       : flow id，标识业务流
qid       : traffic class / queue id，标识业务优先级或服务等级
cycle_id  : cycle group，标识该包所属的调度周期组
flags     : 预留标志位
```

其中：

```text
qid       解决“这是什么等级的流”
cycle_id 解决“这是哪个调度周期的包”
```

两者组合后才能决定最终入队位置：

```text
queue = f(qid, cycle_id)
```

### 2.2 两周期队列组设计

在当前 BMv2 8 个优先级队列的限制下，可以先使用两个 cycle group。

建议映射如下：

```text
queue 0: background traffic

cycle group 0:
  qid=6 -> queue 1
  qid=5 -> queue 2
  qid=4 -> queue 3

cycle group 1:
  qid=6 -> queue 4
  qid=5 -> queue 5
  qid=4 -> queue 6

queue 7: reserved
```

如果 BMv2 当前逻辑是：

```text
queue_idx = 7 - standard_metadata.priority
```

则 P4 中可以设置：

```text
cycle_id=0:
  qid=6 -> priority=6 -> queue 1
  qid=5 -> priority=5 -> queue 2
  qid=4 -> priority=4 -> queue 3

cycle_id=1:
  qid=6 -> priority=3 -> queue 4
  qid=5 -> priority=2 -> queue 5
  qid=4 -> priority=1 -> queue 6

BG:
  qid=7 -> priority=7 -> queue 0
```

### 2.3 实例解释

假设有两个同优先级的 TSN 包：

```text
packet A:
  fid=101
  qid=6
  cycle_id=0

packet B:
  fid=101
  qid=6
  cycle_id=1
```

在 baseline 中：

```text
packet A -> queue 1
packet B -> queue 1
```

两个包会进入同一个队列，调度器只能看到“这两个都是 qid=6 的包”，无法知道它们属于不同周期。

在 CSQF v1 中：

```text
packet A -> queue 1
packet B -> queue 4
```

调度器可以按周期释放：

```text
cycle group 0 active -> release queue 1/2/3
cycle group 1 active -> release queue 4/5/6
```

这就把“业务等级”和“周期归属”解耦了。

## 3. 当前 v1 机制还缺什么

当前 `qid + cycle_id` 机制解决的是：

```text
同一个 qid 下，不同周期包混入同一队列的问题。
```

但它还不是完整 CSQF。主要缺口有三个。

### 3.1 缺少逐跳周期计算

真实的多跳 CSQF 中，包在第 1 跳、第 2 跳、第 3 跳、第 4 跳的目标发送周期通常不是完全相同的。

例如一个 4 跳路径：

```text
h1 -> s1 -> s2 -> s5 -> s6 -> h3
```

如果 cycle 长度是 10ms，一个理想的逐跳调度可能是：

```text
s1: cycle 10
s2: cycle 11
s5: cycle 12
s6: cycle 13
```

或者为了留出处理裕量：

```text
s1: cycle 10
s2: cycle 12
s5: cycle 14
s6: cycle 16
```

也就是说，数据包不能只携带一个全局 `cycle_id`，还需要让每一跳知道：

```text
这个包在本交换机应该进入哪个本地周期队列。
```

### 3.2 缺少 hop 位置感知

如果交换机不知道自己是路径上的第几跳，就很难从包头中选择正确的调度信息。

例如包头里有一个调度序列：

```text
schedule stack = [10, 11, 12, 13]
```

那么：

```text
s1 应该读取 10
s2 应该读取 11
s5 应该读取 12
s6 应该读取 13
```

这就需要包头或交换机本地状态中存在类似：

```text
hop_index
segment_pointer
path_pointer
```

的字段。

### 3.3 缺少 late packet 策略

如果包已经错过它应该进入的周期，系统必须明确处理策略：

```text
策略 A: 继续排队，等待下一个可用周期
策略 B: 标记为 late，但仍然转发
策略 C: 直接丢弃，保证最大时延边界
策略 D: 降级为 background 或 best-effort
```

如果实验目标是：

```text
保证 MAX delay 不超过某个上界
```

那么仅靠排队机制通常不够，因为迟到包如果继续等待，MAX 仍然可能拉长。严格有界时延通常需要：

```text
late detection + drop/mark policy
```

这也是“低丢包”和“强最大时延保证”之间的核心取舍。

## 4. 是否必须使用 SR routing

严格来说，CSQF 不一定必须使用 SR routing。

CSQF 的核心是：

```text
周期队列 + 逐跳周期调度 + 有界等待
```

SR routing 的核心是：

```text
源端把路径或段信息写入包头，网络设备按包头中的 segment/path 信息转发。
```

二者可以结合，但不是天然等价。

可以这样理解：

```text
CSQF 解决“什么时候出队”
SR routing 解决“往哪里转发”
```

如果把二者结合，就可以形成：

```text
source-routed deterministic scheduling
```

也就是发送端不只决定路径，还决定每一跳的调度周期或周期偏移。

你的设想“将跳数设计到数据包头部，因为 CSQF 的一大特点是使用 SR routing”可以作为一个增强型实验方案。更准确的表述可以是：

```text
在本实验中，将 CSQF 与 SR-like 源端路径/周期编码结合，使数据包携带逐跳调度信息，交换机根据包头中的 hop_index 或 segment_pointer 选择本跳应使用的 cycle_id。
```

这样写会更严谨，也更适合作为实验创新点。

## 5. 扩展包头设计

### 5.1 v1 包头：最小 cycle-aware queue

v1 只需要区分周期组：

```text
struct tsn_t {
    bit<16> fid;
    bit<8>  qid;
    bit<8>  cycle_id;
    bit<8>  flags;
}
```

适合验证：

```text
qid + cycle_id 是否能降低不同周期包混队导致的尾部异常。
```

缺点：

```text
1. cycle_id 是全局或发送端计算的，不能表达逐跳不同周期；
2. 不知道当前是第几跳；
3. 不支持 SR-like path/schedule stack。
```

### 5.2 v2 包头：加入 hop_index

v2 建议加入跳数/当前位置：

```text
struct tsn_t {
    bit<16> fid;
    bit<8>  qid;
    bit<8>  cycle_id;
    bit<8>  hop_index;
    bit<8>  path_len;
    bit<8>  flags;
}
```

字段含义：

```text
fid       : flow id
qid       : service class
cycle_id  : base cycle id 或当前 hop 的 cycle group
hop_index : 当前处理到路径上的第几跳
path_len  : 路径总跳数
flags     : late/drop/mark/reserved
```

逐跳处理逻辑：

```text
1. 交换机读取 hop_index；
2. 根据 fid + hop_index 查询本跳周期偏移；
3. 计算 target_cycle；
4. 根据 qid + target_cycle 入队；
5. 转发前 hop_index = hop_index + 1。
```

伪代码：

```text
base_cycle   = hdr.tsn.cycle_id
hop          = hdr.tsn.hop_index
offset       = table_lookup(fid, hop)
target_cycle = base_cycle + offset
cycle_group  = target_cycle % 2
queue        = queue_map(qid, cycle_group)
```

这种方案的优点是包头较小，逐跳信息由控制器下发表维护。

对应控制器表项可以设计为：

```text
key:
  fid
  hop_index

value:
  egress_port
  cycle_offset
  next_hop_index_delta
```

例如：

```text
fid=101, hop=0 -> port=s1-s2, offset=0
fid=101, hop=1 -> port=s2-s5, offset=1
fid=101, hop=2 -> port=s5-s6, offset=2
fid=101, hop=3 -> port=s6-h3, offset=3
```

### 5.3 v3 包头：SR-like path stack

如果希望更接近 SR routing，可以让包头携带路径段。

简化设计：

```text
struct tsn_t {
    bit<16> fid;
    bit<8>  qid;
    bit<8>  base_cycle;
    bit<8>  seg_ptr;
    bit<8>  seg_len;
    bit<8>  flags;
}

struct segment_t {
    bit<8> out_port;
    bit<8> cycle_offset;
}
```

包头逻辑类似：

```text
segments = [
  {out_port=s1_to_s2, cycle_offset=0},
  {out_port=s2_to_s5, cycle_offset=1},
  {out_port=s5_to_s6, cycle_offset=2},
  {out_port=s6_to_h3, cycle_offset=3}
]
```

交换机处理：

```text
seg = segments[seg_ptr]
target_cycle = base_cycle + seg.cycle_offset
queue = f(qid, target_cycle % 2)
egress_port = seg.out_port
seg_ptr = seg_ptr + 1
```

这个方案最接近 SR-like 设计：

```text
源端决定路径和逐跳周期偏移；
交换机只按照包头执行。
```

优点：

```text
1. 控制器逻辑更轻；
2. 包携带完整调度意图；
3. 方便做“源端确定性路径编排”的实验。
```

缺点：

```text
1. P4 variable-length stack 实现复杂；
2. 包头开销增加；
3. BMv2/P4 中对 header stack 的操作要小心；
4. 如果路径长，包头会明显变大；
5. 出端口直接写在包头中会带来安全和一致性问题。
```

### 5.4 v4 包头：schedule stack，不携带 out_port

还有一种折中方案：

```text
路径仍然由交换机本地转发表决定；
包头只携带逐跳 cycle schedule。
```

包头示例：

```text
struct tsn_t {
    bit<16> fid;
    bit<8>  qid;
    bit<8>  hop_index;
    bit<8>  path_len;
    bit<8>  flags;
}

struct cycle_slot_t {
    bit<8> cycle_id;
}
```

发送端写入：

```text
cycle_stack = [10, 11, 12, 13]
```

每跳读取：

```text
target_cycle = cycle_stack[hop_index]
queue = f(qid, target_cycle % 2)
hop_index++
```

转发仍然由：

```text
fid -> next hop / egress_port
```

决定。

这个方案比完整 SR routing 更稳妥：

```text
SR-like schedule, not SR forwarding
```

也就是源端决定逐跳调度周期，但不直接决定每跳出端口。

## 6. 推荐分阶段路线

### 阶段 1：CSQF v1，qid + cycle_id 入队

目标：

```text
验证周期感知队列是否能降低 TSN 长尾异常。
```

包头：

```text
fid, qid, cycle_id, flags
```

交换机：

```text
queue = f(qid, cycle_id % 2)
```

调度器：

```text
cycle group 0 -> release queue 1/2/3
cycle group 1 -> release queue 4/5/6
BG            -> release queue 0
```

这个阶段要重点检查：

```text
1. 发送端是否真的写入 cycle_id；
2. 接收端 CSV 是否记录 cycle_id；
3. P4 priority 是否正确映射到 BMv2 queue；
4. scheduler 是否仍然按 gate/cycle release，而不是扫描所有队列；
5. anomaly 是否按 cycle_id 统计。
```

### 阶段 2：CSQF v2，加入 hop_index

目标：

```text
让交换机知道当前是路径第几跳，从而支持逐跳周期偏移。
```

包头：

```text
fid, qid, base_cycle, hop_index, path_len, flags
```

控制器下发表：

```text
(fid, hop_index) -> egress_port, cycle_offset
```

交换机：

```text
target_cycle = base_cycle + cycle_offset
queue = f(qid, target_cycle % 2)
hop_index++
```

这个阶段的关键是不要一次性实现完整 header stack，而是先用控制器表项完成逐跳调度。

### 阶段 3：CSQF v3，SR-like schedule stack

目标：

```text
把每一跳的调度周期或周期偏移写入包头。
```

包头：

```text
fid, qid, hop_index, path_len, flags, cycle_stack[]
```

交换机：

```text
target_cycle = cycle_stack[hop_index]
queue = f(qid, target_cycle % 2)
hop_index++
```

转发方式可以先保持：

```text
fid -> egress_port
```

不建议一开始就把 out_port 也放入包头。

### 阶段 4：CSQF v4，完整 SR-like path + schedule

目标：

```text
源端同时编码路径和逐跳调度周期。
```

包头：

```text
segment_stack[] = [
  {node/port, cycle_offset},
  {node/port, cycle_offset},
  ...
]
```

交换机：

```text
seg = segment_stack[seg_ptr]
egress_port = seg.port
target_cycle = base_cycle + seg.cycle_offset
queue = f(qid, target_cycle % 2)
seg_ptr++
```

这个阶段实现成本最高，适合作为论文机制扩展或后续实验。

## 7. 多跳周期设计示例

假设：

```text
cycle length = 10ms
path = h1 -> s1 -> s2 -> s5 -> s6 -> h3
hop count = 4 switches
```

### 7.1 理想逐跳周期

如果每跳消耗一个周期：

```text
s1 release at cycle N
s2 release at cycle N+1
s5 release at cycle N+2
s6 release at cycle N+3
h3 receive before cycle N+4 end
```

端到端上界近似：

```text
4 hops * 10ms + source alignment margin = about 40ms-50ms
```

这也是你之前说“4 跳、10ms 时隙，最大应该约 50ms”的直觉来源。

但要真的保证这个上界，需要满足：

```text
1. 发送端按周期边界发包；
2. 每个交换机本地周期同步；
3. 每跳包都在目标 gate 打开前到达；
4. 晚到包不能无限等待；
5. scheduler 不被 Linux/BMv2 抖动严重影响。
```

### 7.2 带裕量逐跳周期

为了减少错过 gate，可以每跳留一个周期裕量：

```text
s1: N
s2: N+2
s5: N+4
s6: N+6
```

优点：

```text
更不容易因为软件抖动错过下一跳 gate。
```

缺点：

```text
端到端时延上界变大。
```

这个可以作为实验变量：

```text
offset_step = 1 cycle
offset_step = 2 cycles
offset_step = 3 cycles
```

对比：

```text
P95, P99, MAX, ANOMALY, DROP
```

## 8. late packet 检测与处理

如果目标是降低 MAX，而不仅是降低 anomaly 数量，建议加入 late detection。

包头可以增加：

```text
deadline_cycle
```

或使用：

```text
base_cycle + path_len + slack
```

计算端到端 deadline。

交换机本地判断：

```text
if local_cycle > target_cycle + allowed_slack:
    packet is late
```

处理策略：

```text
mark:
  继续转发，但 flags.late = 1

drop:
  直接丢弃，保证后续统计中的 MAX 不被迟到包拉长

demote:
  降级进入 BG 队列
```

实验中可以设计三组：

```text
CSQF-no-drop:
  不丢迟到包，观察 MAX 是否仍有长尾

CSQF-mark-late:
  标记迟到包，统计 late 与 anomaly 的对应关系

CSQF-drop-late:
  丢弃迟到包，验证 MAX 上界是否更稳定，但 DROP 是否上升
```

这能解释一个关键问题：

```text
如果要求 MAX 严格有界，就可能必须接受少量 late drop。
```

## 9. P4 与 BMv2 实现建议

### 9.1 P4 parser

需要解析 TSN header 中的新字段：

```text
fid
qid
cycle_id or base_cycle
hop_index
path_len
flags
```

并写入 metadata：

```text
local_metadata.fid
local_metadata.qid
local_metadata.cycle_id
local_metadata.hop_index
```

### 9.2 P4 ingress

v1：

```text
cycle_group = hdr.tsn.cycle_id & 0x1
priority = map_priority(qid, cycle_group)
```

v2：

```text
offset = csqf_hop_table[fid, hop_index]
target_cycle = hdr.tsn.base_cycle + offset
cycle_group = target_cycle & 0x1
priority = map_priority(qid, cycle_group)
hop_index = hop_index + 1
```

### 9.3 BMv2 scheduler

不建议 scheduler 简单扫描所有队列。

正确方向应该是：

```text
1. 保留 gate/cycle release 语义；
2. 当前周期只释放对应 cycle group 的队列；
3. BG 队列可以按独立策略释放；
4. 不属于当前 cycle group 的 TSN 队列必须等待。
```

伪代码：

```text
current_group = current_cycle % 2

if current_group == 0:
    candidate_queues = [1, 2, 3]
else:
    candidate_queues = [4, 5, 6]

try_dequeue(candidate_queues)
try_dequeue_bg_if_allowed(queue 0)
```

如果仍然扫描所有队列：

```text
queue 1..6 都可能被释放
```

那就失去了 CSQF 的周期隔离意义。

## 10. 配置文件建议

建议在 JSON 配置中增加一个 `csqf` 字段。

示例：

```json
{
  "csqf": {
    "enabled": true,
    "cycle_us": 10000,
    "cycle_groups": 2,
    "queue_mapping": {
      "bg": 0,
      "cycle0": {
        "6": 1,
        "5": 2,
        "4": 3
      },
      "cycle1": {
        "6": 4,
        "5": 5,
        "4": 6
      }
    },
    "late_policy": "mark",
    "allowed_slack_cycles": 0
  }
}
```

v2 可以加入 per-hop offset：

```json
{
  "flows": [
    {
      "fid": 101,
      "path": ["s1", "s2", "s5", "s6"],
      "qid": 6,
      "base_cycle_mode": "sender_clock",
      "hop_offsets": [0, 1, 2, 3]
    }
  ]
}
```

v3 可以加入 schedule stack：

```json
{
  "flows": [
    {
      "fid": 101,
      "qid": 6,
      "cycle_schedule": [10, 11, 12, 13]
    }
  ]
}
```

## 11. 接收端与日志设计

接收端 CSV 建议至少包含：

```text
session
kind
fid
qid
cycle_id
base_cycle
hop_index_final
seq
send_ns
recv_ns
delay_us
late_flag
drop_reason
```

分析脚本建议输出：

```text
SESSION
KIND
FID
QID
CYCLE
COUNT
AVG(us)
P50(us)
P95(us)
P99(us)
MAX(us)
DROP(%)
ANOMALY
LATE
```

还可以增加：

```text
ANOMALY_BY_CYCLE
ANOMALY_BY_FID
ANOMALY_BY_HOP
ANOMALY_BY_SWITCH
```

交换机日志建议记录：

```text
switch_id
fid
qid
cycle_id
hop_index
enqueue_queue
enqueue_time
dequeue_queue
dequeue_time
local_cycle
target_cycle
late_flag
```

这样才能判断异常到底发生在：

```text
1. 发送端相位不准；
2. 第一个交换机入队时已经 late；
3. 中间某一跳错过 gate；
4. scheduler 放错 queue group；
5. 接收端统计错误。
```

## 12. 实验对比矩阵

建议按阶段对比：

```text
baseline:
  qid -> queue

CSQF-v1:
  qid + cycle_id -> queue

CSQF-v2:
  qid + base_cycle + hop_index + offset -> queue

CSQF-v3:
  qid + schedule_stack[hop_index] -> queue

CSQF-v3-drop-late:
  schedule_stack + late drop
```

指标：

```text
DROP
P50
P95
P99
MAX
ANOMALY > 60000us
LATE packet count
per-cycle anomaly distribution
per-switch enqueue/dequeue count
```

预期现象：

```text
baseline:
  DROP 低，P95 较好，但少量 MAX 长尾

CSQF-v1:
  周期混队减少，anomaly 应下降，但不能解决逐跳周期错配

CSQF-v2:
  逐跳周期更明确，长尾应进一步下降

CSQF-v3:
  发送端可完整控制逐跳调度，机制表达能力更强

CSQF-v3-drop-late:
  MAX 最稳定，但 DROP 可能上升
```

## 13. 推荐当前下一步

结合你现在的实现状态，建议按这个顺序推进：

```text
1. 先修正 v1，使 send/recv/P4/BMv2 全链路跑通；
2. 确认 switch enqueue/dequeue 不再为 0；
3. 确认 qid + cycle_id 能正确映射到 queue 1..6；
4. 确认 scheduler 没有扫描所有队列，而是按 cycle group release；
5. 在结果中增加 per-cycle anomaly 统计；
6. 再加入 hop_index；
7. 用控制器表项实现 (fid, hop_index) -> cycle_offset；
8. 最后再考虑 schedule stack 或完整 SR-like path stack。
```

最稳妥的设计路线是：

```text
v1: qid + cycle_id
v2: qid + base_cycle + hop_index + per-hop offset
v3: qid + schedule stack
v4: segment stack = path + schedule
```

这样每一步都有独立可验证的实验结论，不会把“周期队列是否有效”“逐跳偏移是否有效”“SR-like 包头是否有效”混在一起。

## 14. 一句话总结

当前修改的本质是：

```text
用 cycle_id 把同一个 qid 的不同周期数据包分离到不同队列，减少周期混队导致的调度失败。
```

下一步扩展的本质是：

```text
在包头中加入 hop_index / path_len / schedule 信息，使每一跳都能知道自己应该使用哪个本地周期队列，从而从单跳周期感知队列扩展为多跳 CSQF 调度。
```

如果再进一步结合 SR routing，则可以形成：

```text
发送端编码路径和逐跳调度计划，交换机按包头逐跳执行确定性转发。
```

