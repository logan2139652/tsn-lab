# CSQF v1 修改建议：slot 级调度、BG 受限释放与 h1_h3 offset 校准

## 1. 修改目标

当前 CSQF v1 已经实现了：

```text
(qid, cycle_id) -> queue
```

即：

```text
cycle_id=0:
  qid=6 -> queue 1
  qid=5 -> queue 2
  qid=4 -> queue 3

cycle_id=1:
  qid=6 -> queue 4
  qid=5 -> queue 5
  qid=4 -> queue 6

BG:
  queue 0
```

但是当前测试结果中出现了两个问题：

```text
1. TSN 流的时延明显高于 BG 流；
2. h1_h3 路径 TSN 时延明显高于 h2_h4 路径。
```

主要原因是：

```text
1. BG 可以在 TSN 空隙中 fallback 发送，释放机会过多；
2. scheduler 使用 cycle group 内扫描多个队列，而不是严格按照 GCL slot 释放一个目标队列；
3. h1_h3 路径上的 s2/s5 GCL offset 可能没有与逐跳转发时序对齐。
```

因此建议修改目标为：

```text
1. 禁止 BG 在所有 TSN 空隙中自由 fallback；
2. 恢复 slot 级 GCL 调度；
3. 用 cycle_group 将 base_queue 映射到 queue 1-3 或 queue 4-6；
4. 重点校准 h1_h3 路径中 s2/s5 的 GCL offset；
5. 修正 DROP 统计口径，避免 per-cycle 统计产生 50% 伪丢包。
```

## 2. 需要修改的文件

建议优先修改以下文件：

```text
1. ~/Workspace/P4/behavioral-model/targets/simple_switch/simple_switch.cpp
   - 修改 BMv2 调度器；
   - 恢复 slot 级 GCL；
   - 限制 BG 只在 GCL idle/BG slot 释放。

2. ~/tsn-lab/python-controller/topo_from_json_bg.py
   - 检查或修改各交换机 GCL 文件生成逻辑；
   - 重点校准 s2/s5 offset。

3. ~/tsn-lab/configs/tsn_6sw_4host.json
   - 如果 GCL/offset 来自配置文件，则修改这里；
   - 明确每台交换机的 GCL 序列。

4. ~/tsn-lab/scripts/run_test_simple.sh
   - 修正 DROP 统计；
   - 增加 per-switch/per-queue/per-cycle 统计。

5. ~/tsn-lab/traffic/send_from_json.py
   - 保持动态 cycle_id；
   - 不建议恢复为读取启动时固定 cycle_group。
```

P4 文件通常不用大改：

```text
~/tsn-lab/p4src/include/tsn_queue.p4
```

只要它仍然实现：

```text
cycle_id=0 -> qid 6/5/4 -> priority 6/5/4 -> queue 1/2/3
cycle_id=1 -> qid 6/5/4 -> priority 3/2/1 -> queue 4/5/6
```

即可。

## 3. 修改 simple_switch.cpp

### 3.1 当前问题

当前调度器大概率类似：

```cpp
size_t group_start = (cycle_group == 0) ? 1 : 4;

for (size_t q = group_start; q < group_start + 3; q++) {
    popped = egress_buffers.try_pop_back_priority(
        worker_id, q, &port, &queue_idx, &packet);
    if (popped) break;
}

if (!popped) {
    popped = egress_buffers.try_pop_back_priority(
        worker_id, 0, &port, &queue_idx, &packet);
}
```

这种逻辑的问题是：

```text
1. 一个 cycle group 内 queue 1/2/3 或 queue 4/5/6 都可能被释放；
2. GCL slot 不再严格决定当前应该释放 qid=6、qid=5 还是 qid=4；
3. 如果当前 TSN group 中没有包，BG 会 fallback 发送；
4. BG 释放机会过多，导致 BG 延迟很好看，但不能证明 TSN 被保护；
5. TSN 仍然受 cycle/gate 约束，一旦错过窗口就会长时间等待。
```

### 3.2 推荐改法：slot 级 GCL + cycle group 映射

调度器应恢复为：

```text
GCL slot -> base_queue
cycle_group -> actual_queue
```

核心逻辑：

```text
base_queue = TSN_GCL[slot_id]

if base_queue in [1,2,3]:
    actual_queue = base_queue + cycle_group * 3
    release actual_queue

if base_queue == 0:
    release BG queue 0
```

映射关系：

```text
cycle_group=0:
  base_queue=1 -> queue 1
  base_queue=2 -> queue 2
  base_queue=3 -> queue 3

cycle_group=1:
  base_queue=1 -> queue 4
  base_queue=2 -> queue 5
  base_queue=3 -> queue 6

base_queue=0:
  BG -> queue 0
```

### 3.3 推荐伪代码

将原来的 group 内扫描逻辑改为：

```cpp
int base_queue = TSN_GCL[slot_id];
bool popped = false;

if (base_queue >= 1 && base_queue <= 3) {
    size_t target_queue =
        static_cast<size_t>(base_queue) + cycle_group * 3;

    popped = egress_buffers.try_pop_back_priority(
        worker_id, target_queue, &port, &queue_idx, &packet);
} else if (base_queue == 0) {
    popped = egress_buffers.try_pop_back_priority(
        worker_id, static_cast<size_t>(0), &port, &queue_idx, &packet);
}

if (popped) {
    break;
}

std::this_thread::sleep_for(std::chrono::microseconds(100));
```

注意：

```text
1. TSN slot 中不要 fallback 到 BG；
2. BG 只在 base_queue == 0 的 idle/BG slot 中释放；
3. 每个 slot 只尝试一个目标 TSN queue，而不是扫描多个 TSN queue；
4. 如果该 slot 对应的 TSN queue 为空，则该 slot 可以空转，不强行发送 BG。
```

### 3.4 为什么这样改

这样改后，调度语义从：

```text
当前 cycle group 中哪个 TSN queue 有包就发哪个；
没有 TSN 就发 BG。
```

恢复为：

```text
当前 GCL slot 指定哪个业务等级，就只发该业务等级；
只有 GCL 明确指定 BG/idle slot 时才发 BG。
```

这更符合确定性调度：

```text
slot 0 -> qid=6
slot 1 -> qid=5
slot 2 -> qid=4
slot 3 -> BG/idle
slot 4 -> qid=6
slot 5 -> qid=5
slot 6 -> qid=4
slot 7 -> BG/idle
```

在 CSQF 中再叠加 cycle group：

```text
cycle 0 的 slot 0 -> queue 1
cycle 1 的 slot 0 -> queue 4
```

## 4. 修改 GCL/offset 配置

### 4.1 需要检查的位置

GCL 文件通常由拓扑脚本生成：

```text
~/tsn-lab/python-controller/topo_from_json_bg.py
```

启动后写到：

```text
/tmp/tsn_gcl_s1.txt
/tmp/tsn_gcl_s2.txt
/tmp/tsn_gcl_s3.txt
/tmp/tsn_gcl_s4.txt
/tmp/tsn_gcl_s5.txt
/tmp/tsn_gcl_s6.txt
```

如果 GCL 来自 JSON 配置，则检查：

```text
~/tsn-lab/configs/tsn_6sw_4host.json
```

### 4.2 当前应重点校准 h1_h3

当前两条路径：

```text
h1_h3:
  h1 -> s1 -> s2 -> s5 -> s6 -> h3

h2_h4:
  h2 -> s1 -> s3 -> s4 -> s6 -> h4
```

测试现象：

```text
h2_h4 TSN 延迟较低，说明 s1/s3/s4/s6 这一条路径相位大体可用；
h1_h3 TSN 延迟较高，说明 s2/s5 或 s6 上针对 h1_h3 的释放窗口可能错位。
```

因此优先检查：

```text
s2
s5
s6 上 h1_h3 入端口对应的调度时隙
```

### 4.3 理想 offset 关系

对于 4 switch hops：

```text
h1 -> s1 -> s2 -> s5 -> s6 -> h3
```

如果每跳用一个 10ms slot：

```text
s1: slot N
s2: slot N+1
s5: slot N+2
s6: slot N+3
```

也可以保守一点，每跳留两个 slot：

```text
s1: slot N
s2: slot N+2
s5: slot N+4
s6: slot N+6
```

但是当前 cycle 只有 8 个 slot，且 slot 3/7 可能用于 BG/idle，因此要避免 offset 与 BG slot 冲突。

建议先采用：

```text
每跳 +1 slot
```

并确保不同业务 qid 的 slot 保持原先顺序：

```text
qid=6 -> base_queue 1
qid=5 -> base_queue 2
qid=4 -> base_queue 3
```

### 4.4 GCL 示例

假设 s1 的 GCL 是：

```text
s1: [1, 2, 3, 0, 1, 2, 3, 0]
```

如果 s2 比 s1 晚 1 slot：

```text
s2: [0, 1, 2, 3, 0, 1, 2, 3]
```

如果 s5 再晚 1 slot：

```text
s5: [3, 0, 1, 2, 3, 0, 1, 2]
```

如果 s6 再晚 1 slot：

```text
s6: [2, 3, 0, 1, 2, 3, 0, 1]
```

这个示例和之前 baseline 的逐跳 offset 思路一致。

需要注意：

```text
如果 CSQF scheduler 使用 cycle_group 映射 queue 1-3 / 4-6，
则 GCL 文件中仍然只需要写 base_queue 0/1/2/3，
不要直接写 4/5/6。
```

也就是说：

```text
GCL 决定 qid 级别；
cycle_group 决定使用哪一组 cycle queue。
```

## 5. 修改 run_test_simple.sh

### 5.1 当前 DROP 问题

当前结果中 TSN 按 cycle 拆分后显示：

```text
cycle 0 count = 125, DROP = 50%
cycle 1 count = 125, DROP = 50%
```

这通常是伪丢包。

因为原始期望是：

```text
每个 TSN flow 总计 250 个包
```

拆成两个 cycle 后自然是：

```text
cycle 0: 125
cycle 1: 125
```

因此：

```text
按 cycle 行计算 DROP 会得到 50%；
按 fid 汇总计算 DROP 应该是 0%。
```

### 5.2 推荐统计口径

建议分成两张表：

第一张：按 flow 汇总，用于真实 DROP：

```text
SESSION KIND FID QID COUNT_TOTAL EXPECTED DROP_REAL
```

第二张：按 cycle 展示延迟：

```text
SESSION KIND FID QID CYCLE COUNT AVG P50 P95 P99 MAX ANOMALY
```

也可以保留一张表，但在按 cycle 展示时：

```text
DROP 不显示；
或 expected = total_expected / cycle_groups。
```

推荐直接去掉 cycle 维度表中的 DROP，避免误读。

### 5.3 增加 per-queue 统计

为了定位 h1_h3 是否在 s2/s5 等待，建议增加：

```text
switch
queue_idx
cycle_group
enqueue_count
dequeue_count
avg_wait_us
max_wait_us
```

至少先增加：

```text
switch queue_idx enqueue dequeue
```

如果 simple_switch.cpp 日志已有：

```text
TSN_QUEUE enqueue ... queue_idx=...
TSN_GCL dequeue ... queue_idx=...
```

那么 `run_test_simple.sh` 可以从交换机日志中 grep/awk 统计。

## 6. send_from_json.py 保持现状

发送端应继续使用动态 cycle_id：

```python
cycle_id = int(cycle % 2)
```

不要改回：

```python
cycle_id = int(cycle_group)
```

原因：

```text
cycle_group 是启动时从 phase 文件读到的一个瞬时值；
如果将它作为整个测试期间的 cycle_id，会导致所有包进入同一组队列。
```

正确逻辑是：

```text
每个发送周期动态计算 cycle_id；
cycle 0 -> cycle_id 0；
cycle 1 -> cycle_id 1；
cycle 2 -> cycle_id 0；
cycle 3 -> cycle_id 1。
```

## 7. P4 侧暂时无需大改

当前 P4 的作用是：

```text
根据 qid + cycle_id 设置 standard_metadata.priority
```

只要保持：

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
  priority=7 -> queue 0
```

就可以。

后续如果做 CSQF v2，再考虑加入：

```text
hop_index
base_cycle
deadline_cycle
```

等字段。

## 8. 建议修改顺序

推荐按以下顺序推进：

```text
1. 修改 simple_switch.cpp
   - 恢复 slot 级 GCL；
   - 禁止 TSN slot 中 fallback BG；
   - 使用 base_queue + cycle_group * 3 选择实际队列。

2. 重新编译安装 BMv2
   - make
   - sudo make install
   - sudo ldconfig

3. 重新运行 run_test_simple.sh
   - 检查 BG 延迟是否不再异常好看；
   - 检查 TSN P95/P99 是否下降；
   - 检查 h1_h3 是否仍明显差于 h2_h4。

4. 如果 h1_h3 仍差：
   - 检查 /tmp/tsn_gcl_s2.txt；
   - 检查 /tmp/tsn_gcl_s5.txt；
   - 检查 /tmp/tsn_gcl_s6.txt；
   - 调整 s2/s5/s6 offset。

5. 修改 run_test_simple.sh
   - 修正 DROP 统计；
   - 增加 per-queue 统计。

6. 记录对比：
   - baseline；
   - CSQF v1 group-scan scheduler；
   - CSQF v1 slot-level scheduler；
   - CSQF v1 slot-level + offset tuned。
```

## 9. 预期结果

修改后预期：

```text
1. BG 延迟可能上升；
2. TSN 在正确相位路径上的 P95/P99 应更稳定；
3. h1_h3 如果 offset 校准正确，P95 应明显下降；
4. cycle 0/1 的 count 仍各约 125；
5. 按 fid 汇总后 DROP 应接近 0；
6. ANOMALY 数量应低于当前 group-scan scheduler。
```

如果 BG 延迟上升，这是合理现象。

因为：

```text
BG 不再能钻所有 TSN 空隙；
它只能在 GCL 明确允许的 idle/BG slot 中发送。
```

这更符合 TSN/CSQF 的实验目标。

## 10. 一句话总结

当前问题不是 `(qid, cycle_id) -> queue` 映射失败，而是 scheduler 仍然太宽松：

```text
TSN 被 gate 严格限制；
BG 却能在所有 TSN 空隙中 fallback；
GCL slot 也没有严格限定唯一目标队列。
```

因此要把调度器改成：

```text
GCL slot 选择 base_queue；
cycle_group 选择 queue group；
BG 只在 idle/BG slot 中释放。
```

然后再校准：

```text
h1_h3 路径上的 s2/s5/s6 GCL offset。
```

