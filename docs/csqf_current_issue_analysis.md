# CSQF 当前编译版本问题分析

## 1. 现象

最新结果目录：

```text
/tmp/tsn_test_20260630_071500
```

接收端 CSV 只有表头：

```text
tsn_recv_h1_h3.csv: 1 line
tsn_recv_h2_h4.csv: 1 line
```

接收端日志只显示监听和空 summary：

```text
session=h1_h3
listening on h3-eth0, duration=20.0s
csv output: /tmp/tsn_recv_h1_h3.csv

=== Delay Summary ===
```

因此这次“Delay Analysis 空表、交换机 enqueue/dequeue 为 0”的直接原因不是接收端统计错误，而是没有有效数据包进入实验链路。

## 2. 直接原因：发送端在发包前崩溃

`send_h1.log` 和 `send_h2.log` 中都有两个错误。

### 2.1 background 线程缺少 cycle_id 参数

当前 `send_from_json.py` 的函数定义是：

```python
def make_pkt(src_mac, dst_mac, src_ip, dst_ip, fid, qid, cycle_id, kind, seq, payload_size):
```

但是 background 调用是：

```python
pkt = make_pkt(
    src_mac, dst_mac,
    src_ip, dst_ip,
    bg_flow["fid"], bg_flow["qid"], KIND_BG, seq,
    session.get("bg_payload", 1200),
)
```

这里少传了 `cycle_id`，所以日志中出现：

```text
TypeError: make_pkt() missing 1 required positional argument: 'payload_size'
```

修正方式：

```python
pkt = make_pkt(
    src_mac, dst_mac,
    src_ip, dst_ip,
    bg_flow["fid"], bg_flow["qid"], 0, KIND_BG, seq,
    session.get("bg_payload", 1200),
)
```

BG 流可以固定 `cycle_id=0`，因为 P4 中非 TSN/BG 本质上最终应该进入 queue 0。

### 2.2 APP_HDR 格式仍然是 6 字段，但 pack/unpack 按 7 字段使用

当前 sender：

```python
APP_HDR = struct.Struct("!4sHBBBQ")
```

这个格式代表：

```text
4s : magic
H  : fid
B  : qid
B  : cycle_id
B  : kind
Q  : send_ns
```

一共 6 个字段。

但 sender 实际 pack：

```python
APP_HDR.pack(b"TSN1", fid, qid, cycle_id, kind, seq, send_ns)
```

这里是 7 个字段，多了 `seq`。

所以日志中出现：

```text
struct.error: pack expected 6 items for packing (got 7)
```

receiver 也有同样问题：

```python
APP_HDR = struct.Struct("!4sHBBBQ")
magic, fid, qid, cycle_id, kind, seq, send_ns = APP_HDR.unpack(...)
```

因此 sender 和 receiver 都应该改成：

```python
APP_HDR = struct.Struct("!4sHBBBIQ")
```

字段含义：

```text
4s : magic
H  : fid
B  : qid
B  : cycle_id
B  : kind
I  : seq
Q  : send_ns
```

对应：

```python
magic, fid, qid, cycle_id, kind, seq, send_ns
```

这是当前必须先修的第一处。

## 3. 为什么交换机统计为 0

因为 sender 主线程在第一次 TSN 发包前就因为 `APP_HDR.pack` 崩溃，background 线程也因为参数错崩溃。

所以实际链路中没有有效 TSN/BG 包：

```text
sender crash
  -> receiver CSV empty
  -> switch enqueue/dequeue no useful计数
  -> Delay Analysis 空表
```

这次不应该先怀疑 P4 或 BMv2 编译是否失败。第一层就是 Python sender 没跑起来。

## 4. P4 当前状态

P4 侧的 v1 修改基本是连贯的。

### 4.1 TSN header

当前 `headers.p4`：

```p4
header tsn_t {
    bit<16> next_type;
    bit<16> fid;
    bit<8>  qid;
    bit<8>  cycle_id;
    bit<8>  flags;
}
```

### 4.2 metadata

当前 `custom_headers.p4`：

```p4
bit<1>        is_tsn;
bit<16>       fid;
bit<8>        qid;
bit<8>        cycle_id;
```

### 4.3 parser

当前 `parsers.p4`：

```p4
local_metadata.is_tsn = 1w1;
local_metadata.fid = hdr.tsn.fid;
local_metadata.qid = hdr.tsn.qid;
local_metadata.cycle_id = hdr.tsn.cycle_id;
```

### 4.4 qid + cycle_id 映射

当前 `tsn_queue.p4`：

```p4
if (local_metadata.cycle_id[0:0] == 1w0) {
    standard_metadata.priority = local_metadata.qid[2:0];
} else {
    standard_metadata.priority = local_metadata.qid[2:0] - 3w3;
}
```

这对应：

```text
cycle_id=0:
  qid=6 -> priority=6 -> queue 1
  qid=5 -> priority=5 -> queue 2
  qid=4 -> priority=4 -> queue 3

cycle_id=1:
  qid=6 -> priority=3 -> queue 4
  qid=5 -> priority=2 -> queue 5
  qid=4 -> priority=1 -> queue 6
```

所以 P4 侧不是当前空表的直接原因。

## 5. 后续会影响 CSQF 效果的问题

修完 sender 后，实验能发包，但还有两个设计点会影响结果。

### 5.1 phase 文件没有写 cycle_group

sender 当前读取：

```python
cycle_group = data.get("cycle_group", 0)
return cycle_base_ns, cycle_ns, cycle_group
```

但是 `simple_switch.cpp` 当前写 phase 文件只写了：

```text
mono_ns
bmv2_now_us
phase_us
slot_offset_us
slot_id
slot_us
cycle_us
```

没有写：

```text
cycle_group
```

所以 sender 实际永远读到默认值：

```python
cycle_group = 0
```

结果是所有 TSN 包都会写成：

```text
cycle_id=0
```

这样 P4 只会把 TSN 包放入 queue 1/2/3，不会使用 queue 4/5/6。

但 scheduler 当前会按：

```cpp
cycle_group = (now_us / cycle_us) % 2;
```

交替释放：

```text
group 0 -> queue 1/2/3
group 1 -> queue 4/5/6
```

如果所有包都进入 group 0 队列，那么 group 1 周期会没有对应 TSN 包可发，包可能额外等待，尾部时延会变差。

建议在 `write_tsn_phase_file` 中增加：

```cpp
uint64_t cycle_group
```

并写入：

```cpp
<< "cycle_group=" << cycle_group << "\n"
```

同时调用处传入当前 scheduler 计算出的 `cycle_group`。

### 5.2 scheduler 当前先释放 BG queue 0

当前 `simple_switch.cpp` 逻辑：

```cpp
// Always try BG queue 0 first
popped = egress_buffers.try_pop_back_priority(worker_id, 0, ...);

if (!popped) {
    group_start = cycle_group == 0 ? 1 : 4;
    for q in current group:
        try_pop(q)
}
```

这会导致：

```text
只要 BG queue 0 一直有包，就会先发 BG；
TSN queue 需要等 BG 为空才会被尝试。
```

这和确定性 TSN 的目标相反。建议改成：

```text
1. 先释放当前 cycle group 的 TSN queue；
2. 如果当前 group 没有 TSN 包，再释放 BG queue 0；
3. 或者只在 GCL idle slot 释放 BG。
```

伪代码：

```cpp
bool popped = false;
size_t group_start = (cycle_group == 0) ? 1 : 4;

for (size_t q = group_start; q < group_start + 3; q++) {
    popped = egress_buffers.try_pop_back_priority(worker_id, q, &port, &queue_idx, &packet);
    if (popped) break;
}

if (!popped) {
    popped = egress_buffers.try_pop_back_priority(worker_id, 0, &port, &queue_idx, &packet);
}
```

否则即使 Python 修好，BG 流也可能继续拉长 TSN 的尾部时延。

## 6. 最小修复顺序

建议先按这个顺序修：

```text
1. send_from_json.py:
   APP_HDR = struct.Struct("!4sHBBBIQ")

2. recv_from_json.py:
   APP_HDR = struct.Struct("!4sHBBBIQ")

3. send_from_json.py:
   background_sender 调用 make_pkt 时补 cycle_id=0

4. 跑一次脚本，确认：
   - send_h1.log / send_h2.log 无 Traceback
   - CSV 不再只有表头
   - switch enqueue/dequeue 不再为 0

5. 再修 simple_switch.cpp:
   - phase 文件写 cycle_group
   - scheduler 先 TSN 后 BG

6. 重新编译并跑第二次，观察：
   - cycle_id=0/1 是否都出现
   - queue 1..6 是否都有 enqueue/dequeue
   - TSN anomaly 是否下降
```

## 7. 当前判断

当前版本失败的主因是：

```text
Python sender/receiver 的 APP_HDR 格式和 cycle_id 改动没有完全对齐。
```

具体表现是：

```text
APP_HDR 仍是 6 字段，但 pack/unpack 已经按 7 字段写；
background sender 调 make_pkt 时漏传 cycle_id。
```

因此目前还没有进入真正验证 CSQF P4/BMv2 机制的阶段。先修 Python 发包路径，确认数据包重新进入链路后，再看 P4 队列映射和 scheduler 的效果。

