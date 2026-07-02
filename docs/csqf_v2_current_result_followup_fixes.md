# CSQF v2 当前结果后的修缮清单

## 1. 当前结果概述

当前最新结果显示，CSQF v2 的 `slot_stack + hop_index` 机制已经初步跑通。

结果中 TSN 数据如下：

```text
h1_h3 TSN 101 count=250 P95≈37ms anomaly=2
h1_h3 TSN 102 count=250 P95≈37ms anomaly=2
h1_h3 TSN 103 count=250 P95≈38ms anomaly=1
h2_h4 TSN 201 count=250 P95≈37ms anomaly=2
h2_h4 TSN 202 count=250 P95≈37ms anomaly=1
h2_h4 TSN 203 count=250 P95≈38ms anomaly=1
```

说明：

```text
1. 每条 TSN flow 都收到 250 个包；
2. 没有端到端 TSN 丢包；
3. P95 基本稳定在 37-38ms；
4. anomaly 数量已经很低；
5. 相比 v1 中 qid=5/qid=4 大量 117ms 异常，当前机制明显改善。
```

当前交换机统计显示：

```text
s1 enqueue=1500 dequeue=0
s2 enqueue=750  dequeue=0
s3 enqueue=750  dequeue=0
s4 enqueue=750  dequeue=0
s5 enqueue=750  dequeue=0
s6 enqueue=1500 dequeue=0
```

其中 `dequeue=0` 不可信。

原因：

```text
接收端已经收到 1500 个 TSN 包；
如果交换机真的没有 dequeue，接收端不可能收到数据。
```

因此当前主要问题不是机制失败，而是：

```text
1. run_test_simple.sh 的 dequeue 日志解析没有适配新日志；
2. BE/BG 没有进入最终分析表；
3. 需要补充 hop_index、slot_stack、BE opportunistic transmission 的验收；
4. 需要多轮测试确认 anomaly 是否稳定。
```

## 2. 当前阶段结论

可以暂时形成如下阶段性结论：

```text
CSQF v2 的 slot_stack + hop_index pointer 机制已经初步可用。
```

核心机制为：

```text
1. 数据包携带逐跳 slot_stack；
2. hop_index 作为逻辑指针；
3. 每个交换机读取 slot_stack[hop_index]；
4. 根据本地 slot -> queue 映射入 TSN queue；
5. 转发前 hop_index++；
6. BMv2 scheduler 在当前 slot 优先释放对应 TSN queue；
7. 若 TSN queue 为空，允许 BE queue 机会式补发。
```

这相当于：

```text
SR routing: segment list + segment pointer
CSQF v2:   slot_stack + hop_index pointer
```

与 v1 的区别：

```text
v1: packet header 中写 qid + cycle_id，并由它们决定 queue；
v2: packet header 中写逐跳 slot 计划，queue 由交换机本地解释。
```

当前实验说明：

```text
v2 机制相比 v1 更稳定，避免了 qid/cycle_id 静态绑定导致的部分流大面积错过 gate 的问题。
```

## 3. 下一步需要修缮的问题

### 3.1 修正 dequeue 统计

问题：

```text
Switch Scheduling Stats 中 dequeue=0，但接收端有完整 delay 数据。
```

判断：

```text
dequeue=0 是统计脚本错误，不是交换机真的没有出队。
```

可能原因：

```text
simple_switch.cpp 中出队日志关键字已经变化；
run_test_simple.sh 仍然按旧关键字解析。
```

旧日志可能类似：

```text
TSN_GCL dequeue ...
```

新日志可能类似：

```text
CSQF dequeue ...
```

或其他格式。

需要修改文件：

```text
~/tsn-lab/scripts/run_test_simple.sh
~/Workspace/P4/behavioral-model/targets/simple_switch/simple_switch.cpp
```

推荐做法：

```text
1. 在 simple_switch.cpp 中统一 enqueue/dequeue 日志格式；
2. 在 run_test_simple.sh 中按统一格式解析；
3. 保留兼容旧关键字的 grep 规则。
```

推荐日志格式：

```text
CSQF_ENQUEUE sw=<sw> queue=<queue_idx> priority=<priority> port=<port>
CSQF_DEQUEUE sw=<sw> queue=<queue_idx> priority=<priority> port=<port> slot=<slot_id>
```

如果 simple_switch.cpp 不方便写 `sw`，至少保证：

```text
CSQF_ENQUEUE
CSQF_DEQUEUE
queue_idx=
```

run_test_simple.sh 可以按文件名识别交换机：

```text
s1-simple-switch-grpc.log.txt
s2-simple-switch-grpc.log.txt
...
```

脚本 grep 规则建议兼容：

```bash
grep -E "CSQF_DEQUEUE|TSN_GCL dequeue|dequeue"
```

但最终最好统一成：

```text
CSQF_DEQUEUE
```

验收标准：

```text
Switch Scheduling Stats 中 dequeue 不再为 0；
各交换机 enqueue/dequeue 数与路径转发逻辑一致；
接收端 count 与 dequeue 统计可解释。
```

### 3.2 将 BE/BG 纳入最终分析表

当前结果中只有：

```text
KIND=TSN
```

没有：

```text
KIND=BG
KIND=BE
```

但 CSQF v2 设计包含：

```text
TSN 优先，BE 空隙补发
```

因此 BE/BG 必须进入实验结果，否则无法验证 BE opportunistic transmission。

需要检查文件：

```text
~/tsn-lab/traffic/send_from_json.py
~/tsn-lab/traffic/recv_from_json.py
~/tsn-lab/scripts/run_test_simple.sh
~/tsn-lab/configs/tsn_6sw_4host.json
```

检查点：

```text
1. send_from_json.py 是否仍启动 background_sender；
2. bg_pps 是否大于 0；
3. BG 包是否设置 KIND_BG；
4. recv_from_json.py 是否解析 KIND_BG；
5. CSV 是否写出 kind=BG；
6. run_test_simple.sh 是否过滤掉 BG 行。
```

推荐分析表：

```text
SESSION KIND FID COUNT AVG(us) P50(us) P95(us) P99(us) MAX(us) ANOMALY
```

其中 KIND 至少包含：

```text
TSN
BG
```

如果当前术语希望从 BG 改成 BE，也要统一：

```text
代码里 KIND_BG 可以保留；
报告里说明 BG/BE 表示 best-effort/background traffic。
```

验收标准：

```text
Delay Analysis 中出现 BG/BE 行；
BG/BE count 非 0；
BG/BE 延迟能反映机会式补发效果。
```

### 3.3 验证 hop_index 是否正确前移

v2 机制的核心之一是：

```text
每经过一跳 hop_index++。
```

对于当前 4-hop 路径：

```text
h1_h3: s1 -> s2 -> s5 -> s6
h2_h4: s1 -> s3 -> s4 -> s6
```

接收端应看到：

```text
hop_index = 4
```

需要检查文件：

```text
~/tsn-lab/p4src/include/tsn_queue.p4
~/tsn-lab/traffic/recv_from_json.py
~/tsn-lab/scripts/run_test_simple.sh
```

P4 中应存在：

```p4
if (hdr.tsn.hop_index < hdr.tsn.path_len) {
    hdr.tsn.hop_index = hdr.tsn.hop_index + 8w1;
}
```

并且顺序必须是：

```text
1. 先用旧 hop_index 读取 target_slot；
2. 再执行 hop_index++。
```

receiver CSV 应包含：

```text
hop_index
path_len
slot0
slot1
slot2
slot3
flags
```

验收标准：

```text
接收端 CSV 中 TSN 包 hop_index=4；
如果 hop_index=0，说明交换机没有前移；
如果 hop_index=1/2/3，说明中间某跳未处理或未加载新 P4。
```

### 3.4 验证 slot_stack 是否符合预期

需要在 CSV 或日志中确认每个 fid 的 slot_stack。

推荐预期：

```text
FID 101: [0,1,2,3]
FID 102: [1,2,3,4]
FID 103: [2,3,4,5]
FID 201: [0,1,2,3]
FID 202: [1,2,3,4]
FID 203: [2,3,4,5]
```

该映射表示：

```text
同一条流每跳延后一个 slot；
不同流使用不同起始 slot；
交换机根据本地 slot->queue 映射入队。
```

需要检查：

```text
send_from_json.py 中 slot_stack 生成逻辑；
recv_from_json.py 中 CSV 是否记录 slot0-slot3；
run_test_simple.sh 是否输出 slot_stack 统计。
```

推荐新增表：

```text
SESSION FID SLOT_STACK COUNT ANOMALY
```

示例：

```text
h1_h3 101 [0,1,2,3] 250 2
h1_h3 102 [1,2,3,4] 250 2
h1_h3 103 [2,3,4,5] 250 1
```

### 3.5 确认 P4 不再依赖 qid/cycle_id

v2 核心逻辑不应再依赖：

```text
qid
cycle_id
```

入队逻辑应为：

```text
target_slot = slot_stack[hop_index]
base_queue = slot_to_queue[target_slot]
priority = queue_to_priority[base_queue]
```

需要检查文件：

```text
~/tsn-lab/p4src/include/headers.p4
~/tsn-lab/p4src/include/custom_headers.p4
~/tsn-lab/p4src/include/parsers.p4
~/tsn-lab/p4src/include/tsn_queue.p4
~/tsn-lab/traffic/send_from_json.py
~/tsn-lab/traffic/recv_from_json.py
```

允许 `fid` 保留：

```text
fid 用于统计和识别业务流。
```

但不要使用：

```text
qid -> queue
cycle_id -> queue group
```

作为核心入队逻辑。

验收标准：

```text
grep qid/cycle_id 后，核心 P4 入队逻辑中不再依赖它们；
APP_HDR 中不再 pack/unpack qid/cycle_id；
run_test_simple.sh 不再要求 CSV 中存在 qid/cycle 字段。
```

### 3.6 完善 BMv2 scheduler 的 BE 机会式补发

当前机制应为：

```text
当前 slot 对应 TSN queue 有包 -> 发送 TSN；
当前 slot 对应 TSN queue 为空 -> 允许 BE queue 发送；
当前 slot 是 BE slot -> 发送 BE queue。
```

不是：

```text
TSN 和 BE 进入同一个 FIFO queue。
```

也不是：

```text
BE 帧级抢占 TSN/TSN 帧级抢占 BE。
```

需要在报告中明确：

```text
本机制是 packet-level opportunistic BE；
不是 IEEE 802.1Qbu / 802.3br frame preemption。
```

需要检查文件：

```text
~/Workspace/P4/behavioral-model/targets/simple_switch/simple_switch.cpp
```

推荐 scheduler 伪代码：

```cpp
int base_queue = TSN_GCL[slot_id];
bool popped = false;

if (base_queue >= 1 && base_queue <= 3) {
    popped = try_pop(base_queue);   // TSN first

    if (!popped) {
        popped = try_pop(0);        // BE opportunistic
    }
} else if (base_queue == 0) {
    popped = try_pop(0);            // BE slot
}
```

验收标准：

```text
日志能区分 TSN queue dequeue 与 BE queue dequeue；
BE 出现在结果表；
TSN P95 不因 BE 补发明显恶化。
```

## 4. 建议更新的文档内容

需要补充到实验报告或设计文档中：

```text
1. 当前 CSQF v2 已从 qid/cycle 队列绑定转为 slot_stack 指针机制；
2. slot_stack + hop_index 借鉴 SR routing 的 list + pointer 思想；
3. 每跳读取当前 slot，交换机本地解释 slot 到 queue；
4. BE 采用 packet-level opportunistic transmission；
5. 当前实验 TSN 结果已经基本稳定；
6. dequeue=0 是统计问题，不是交换机行为问题；
7. 后续需要补齐 BE 统计和多轮实验。
```

推荐表述：

```text
CSQF v2 将调度计划从队列选择中解耦。数据包头部携带逐跳 slot_stack，并通过 hop_index 指示当前应执行的调度指令。交换机根据本地 slot-to-queue 映射将 TSN 包送入对应队列，BMv2 scheduler 在当前时隙优先释放该 TSN 队列；若该队列为空，则允许 BE 队列机会式使用该发送机会。该机制实现的是包级机会式 BE 复用，而非帧级抢占。
```

## 5. 智能体修缮任务清单

建议将以下任务交给智能体执行：

```text
Task 1:
  检查 simple_switch.cpp 当前 enqueue/dequeue 日志格式；
  修改为稳定的 CSQF_ENQUEUE / CSQF_DEQUEUE；
  更新 run_test_simple.sh 统计逻辑。

Task 2:
  检查 send_from_json.py 是否发送 BG/BE；
  检查 recv_from_json.py 是否记录 KIND_BG；
  修改 run_test_simple.sh，让 BG/BE 出现在 Delay Analysis。

Task 3:
  检查 recv CSV 是否包含 hop_index/path_len/slot0-slot3/flags；
  增加 slot_stack 统计表。

Task 4:
  检查 P4 是否正确执行 hop_index++；
  用接收端 hop_index=4 作为验收。

Task 5:
  连续运行至少 3-5 轮测试；
  汇总 TSN/BG 的 AVG/P50/P95/P99/MAX/ANOMALY；
  判断 anomaly 是否稳定。
```

## 6. 最终验收标准

修缮完成后，应满足：

```text
1. Delay Analysis 同时包含 TSN 和 BG/BE；
2. TSN 每条 flow count=250；
3. BG/BE count 非 0；
4. switch dequeue 不再显示 0；
5. 接收端 TSN hop_index=4；
6. CSV 中 slot_stack 可见；
7. TSN P95 稳定在当前水平或更好；
8. anomaly 维持低水平；
9. 多轮结果没有系统性丢包。
```

## 7. 一句话总结

当前 CSQF v2 的主体机制已经初步跑通，下一步不是重做机制，而是修缮：

```text
统计脚本、dequeue 日志解析、BE/BG 纳入分析、hop_index/slot_stack 验收、多轮实验稳定性。
```

