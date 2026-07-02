# CSQF v2 Slot Stack 实施计划（Agent 可执行版）

## 0. 本方案目标

实现一个更清晰的 CSQF v2：

```text
packet header 携带 slot_stack
hop_index 作为 slot_stack 指针
交换机读取 slot_stack[hop_index]
根据本地 slot -> TSN queue 映射入队
转发前 hop_index++
scheduler 在当前 slot 优先发送 TSN queue
如果该 TSN queue 为空，允许 BE queue 机会式补发
```

本方案不做物理意义上的 header pop。

```text
机制描述：每跳消费一个 slot 指令
实验实现：hop_index++，逻辑上消费
```

这样更接近 SR routing 的思想：

```text
SR routing: segment list + segment pointer
CSQF v2:   slot_stack + hop_index pointer
```

## 1. 最终机制定义

### 1.1 包头含义

包头只表达逐跳调度计划，不直接表达队列。

```text
fid:
  flow id

hop_index:
  当前读取 slot_stack 的指针

path_len:
  路径长度，单位为交换机跳数

slot_stack:
  逐跳 slot 指令栈，例如 [0,1,2,3]

flags:
  调试/late/drop 预留
```

示例：

```text
fid = 101
hop_index = 0
path_len = 4
slot_stack = [0, 1, 2, 3]
```

逐跳处理：

```text
s1: read slot_stack[0] = slot0 -> hop_index = 1
s2: read slot_stack[1] = slot1 -> hop_index = 2
s5: read slot_stack[2] = slot2 -> hop_index = 3
s6: read slot_stack[3] = slot3 -> hop_index = 4
```

### 1.2 队列含义

推荐先使用 4 个队列：

```text
queue 1: TSN queue A
queue 2: TSN queue B
queue 3: TSN queue C
queue 0: BE/BG queue
```

不建议让 TSN 和 BE 进入同一个 FIFO queue。

原因：

```text
如果 BE 先进同一 FIFO queue，TSN 后到，则 TSN 不能越过 BE。
这会破坏确定性时延。
```

### 1.3 slot 到 queue 的本地映射

推荐初始映射：

```text
slot0 -> queue1
slot1 -> queue2
slot2 -> queue3
slot3 -> queue1
slot4 -> queue2
slot5 -> queue3
slot6 -> queue1
slot7 -> queue0
```

含义：

```text
TSN 占 7 个 slot
BE 显式占 1 个 slot
BE 还可在 TSN queue 为空时机会式补发
```

如果需要更保守的 BE 机会：

```text
slot0 -> queue1
slot1 -> queue2
slot2 -> queue3
slot3 -> queue0
slot4 -> queue1
slot5 -> queue2
slot6 -> queue3
slot7 -> queue0
```

## 2. Agent 执行总流程

按以下顺序执行，不要跳步：

```text
1. 备份远端当前文件
2. 修改 P4 header
3. 修改 P4 metadata
4. 修改 P4 parser
5. 修改 P4 queue mapping
6. 修改 sender
7. 修改 receiver
8. 修改 BMv2 scheduler
9. 修改 run_test_simple.sh
10. 重新编译 P4
11. 重新编译/安装 BMv2
12. 运行最小测试
13. 检查日志、CSV、switch enqueue/dequeue
```

每一步完成后，都要做对应验收。

## 3. 需要修改的文件

### 3.1 P4 文件

```text
~/tsn-lab/p4src/include/headers.p4
~/tsn-lab/p4src/include/custom_headers.p4
~/tsn-lab/p4src/include/parsers.p4
~/tsn-lab/p4src/include/tsn_queue.p4
~/tsn-lab/p4src/tsn_basic.p4
```

`tsn_basic.p4` 通常只需要确认仍然 include 并调用 `tsn_queue_control`。

### 3.2 Python 流量文件

```text
~/tsn-lab/traffic/send_from_json.py
~/tsn-lab/traffic/recv_from_json.py
```

### 3.3 BMv2 文件

```text
~/Workspace/P4/behavioral-model/targets/simple_switch/simple_switch.cpp
```

### 3.4 脚本和配置

```text
~/tsn-lab/scripts/run_test_simple.sh
~/tsn-lab/configs/tsn_6sw_4host.json
~/tsn-lab/python-controller/topo_from_json_bg.py
```

配置和拓扑脚本不一定必须大改，先确保 GCL 能表达新 slot->queue 映射。

## 4. Step 1：备份文件

Agent 执行前先备份：

```bash
mkdir -p ~/tsn-lab/backups/csqf_v2_slot_stack_$(date +%Y%m%d_%H%M%S)
```

备份这些文件：

```bash
cp ~/tsn-lab/p4src/include/headers.p4 <backup_dir>/
cp ~/tsn-lab/p4src/include/custom_headers.p4 <backup_dir>/
cp ~/tsn-lab/p4src/include/parsers.p4 <backup_dir>/
cp ~/tsn-lab/p4src/include/tsn_queue.p4 <backup_dir>/
cp ~/tsn-lab/traffic/send_from_json.py <backup_dir>/
cp ~/tsn-lab/traffic/recv_from_json.py <backup_dir>/
cp ~/tsn-lab/scripts/run_test_simple.sh <backup_dir>/
cp ~/Workspace/P4/behavioral-model/targets/simple_switch/simple_switch.cpp <backup_dir>/
```

验收：

```bash
ls -l <backup_dir>
```

## 5. Step 2：修改 headers.p4

文件：

```text
~/tsn-lab/p4src/include/headers.p4
```

目标：将 TSN header 改为 slot stack 结构。

推荐 header：

```p4
header tsn_t {
    bit<16> next_type;
    bit<16> fid;
    bit<8>  hop_index;
    bit<8>  path_len;
    bit<8>  slot0;
    bit<8>  slot1;
    bit<8>  slot2;
    bit<8>  slot3;
    bit<8>  flags;
}
```

说明：

```text
slot0-slot3 是固定长度 slot stack。
hop_index 是指针。
path_len 当前为 4。
```

不要再保留旧核心字段：

```text
qid
cycle_id
cycle0/slot0 ... cycle3/slot3
```

除非临时为了兼容调试，但核心逻辑不要依赖它们。

验收：

```bash
grep -n "header tsn_t" -A20 ~/tsn-lab/p4src/include/headers.p4
```

## 6. Step 3：修改 custom_headers.p4

文件：

```text
~/tsn-lab/p4src/include/custom_headers.p4
```

目标 metadata：

```p4
struct local_metadata_t {
    bit<16>       l4_src_port;
    bit<16>       l4_dst_port;
    next_hop_id_t next_hop_id;

    bit<1>        is_tsn;
    bit<16>       fid;
    bit<8>        hop_index;
    bit<8>        target_slot;
    bit<8>        base_queue;
}
```

字段含义：

```text
target_slot:
  当前交换机根据 hop_index 读取到的本跳 slot。

base_queue:
  target_slot 映射出的 TSN/BE queue。
```

验收：

```bash
grep -n "struct local_metadata_t" -A25 ~/tsn-lab/p4src/include/custom_headers.p4
```

## 7. Step 4：修改 parsers.p4

文件：

```text
~/tsn-lab/p4src/include/parsers.p4
```

目标：parser 只做解析和 metadata 初始化，不在 parser 中做复杂映射。

在 `state start` 中初始化：

```p4
local_metadata.is_tsn = 1w0;
local_metadata.fid = 0;
local_metadata.hop_index = 0;
local_metadata.target_slot = 0;
local_metadata.base_queue = 0;
```

在 `parse_tsn` 中：

```p4
state parse_tsn {
    packet.extract(hdr.tsn);

    local_metadata.is_tsn = 1w1;
    local_metadata.fid = hdr.tsn.fid;
    local_metadata.hop_index = hdr.tsn.hop_index;

    transition select(hdr.tsn.next_type) {
        ETH_TYPE_IPV4: parse_ipv4;
        default: accept;
    }
}
```

不要在 parser 中写：

```p4
if hop_index == 0 ...
```

这部分放到 `tsn_queue.p4`。

验收：

```bash
grep -n "state parse_tsn" -A25 ~/tsn-lab/p4src/include/parsers.p4
```

## 8. Step 5：修改 tsn_queue.p4

文件：

```text
~/tsn-lab/p4src/include/tsn_queue.p4
```

这是 P4 核心逻辑。

### 8.1 选择 target_slot

伪代码：

```p4
action select_target_slot() {
    if (hdr.tsn.hop_index == 8w0) {
        local_metadata.target_slot = hdr.tsn.slot0;
    } else if (hdr.tsn.hop_index == 8w1) {
        local_metadata.target_slot = hdr.tsn.slot1;
    } else if (hdr.tsn.hop_index == 8w2) {
        local_metadata.target_slot = hdr.tsn.slot2;
    } else {
        local_metadata.target_slot = hdr.tsn.slot3;
    }
}
```

### 8.2 slot -> queue 映射

推荐映射：

```text
slot0 -> queue1
slot1 -> queue2
slot2 -> queue3
slot3 -> queue1
slot4 -> queue2
slot5 -> queue3
slot6 -> queue1
slot7 -> queue0
```

P4 伪代码：

```p4
action set_base_queue() {
    if (local_metadata.target_slot[2:0] == 3w0 ||
        local_metadata.target_slot[2:0] == 3w3 ||
        local_metadata.target_slot[2:0] == 3w6) {
        local_metadata.base_queue = 8w1;
    } else if (local_metadata.target_slot[2:0] == 3w1 ||
               local_metadata.target_slot[2:0] == 3w4) {
        local_metadata.base_queue = 8w2;
    } else if (local_metadata.target_slot[2:0] == 3w2 ||
               local_metadata.target_slot[2:0] == 3w5) {
        local_metadata.base_queue = 8w3;
    } else {
        local_metadata.base_queue = 8w0;
    }
}
```

### 8.3 queue -> priority 映射

BMv2 当前关系：

```text
queue_idx = 7 - priority
```

所以：

```text
queue0 -> priority7
queue1 -> priority6
queue2 -> priority5
queue3 -> priority4
```

P4 伪代码：

```p4
action set_priority_from_queue() {
    if (local_metadata.base_queue == 8w1) {
        standard_metadata.priority = 3w6;
    } else if (local_metadata.base_queue == 8w2) {
        standard_metadata.priority = 3w5;
    } else if (local_metadata.base_queue == 8w3) {
        standard_metadata.priority = 3w4;
    } else {
        standard_metadata.priority = 3w7;
    }
}
```

### 8.4 hop_index++

必须先选择 target_slot，再前移指针。

```p4
action advance_hop_index() {
    if (hdr.tsn.hop_index < hdr.tsn.path_len) {
        hdr.tsn.hop_index = hdr.tsn.hop_index + 8w1;
    }
}
```

注意：

```text
如果 path_len=4，最后一跳 s6 处理时 hop_index=3。
s6 处理完后 hop_index=4。
接收端看到 hop_index=4，说明 4 跳都处理过。
```

### 8.5 完整 apply 结构

```p4
apply {
    if (hdr.tsn.isValid()) {
        select_target_slot();
        set_base_queue();
        set_priority_from_queue();
        advance_hop_index();
    } else {
        standard_metadata.priority = 3w7;
    }
}
```

### 8.6 Debug egress

可以把当前 slot 写入 flags：

```p4
hdr.tsn.flags = local_metadata.target_slot;
```

但注意接收端看到的 flags 可能是最后一跳写入值。

验收：

```bash
p4c-bm2-ss --p4v 16 -o /tmp/tsn_basic_test.json ~/tsn-lab/p4src/tsn_basic.p4
```

如果编译失败，优先检查：

```text
bit width 不匹配
metadata 字段未定义
hdr.tsn 字段名不一致
action 中局部变量位置不合法
```

## 9. Step 6：修改 send_from_json.py

文件：

```text
~/tsn-lab/traffic/send_from_json.py
```

### 9.1 Scapy TSN header

必须与 P4 header 完全一致：

```python
class TSN(Packet):
    name = "TSN"
    fields_desc = [
        ShortField("next_type", 0x0800),
        ShortField("fid", 0),
        ByteField("hop_index", 0),
        ByteField("path_len", 4),
        ByteField("slot0", 0),
        ByteField("slot1", 0),
        ByteField("slot2", 0),
        ByteField("slot3", 0),
        ByteField("flags", 0),
    ]
```

### 9.2 APP_HDR

应用层统计头不要再引用 `qid/cycle_id`。

推荐：

```python
APP_HDR = struct.Struct("!4sHBIQ")
```

字段：

```text
magic   4s
fid     H
kind    B
seq     I
send_ns Q
```

pack：

```python
app = APP_HDR.pack(b"TSN1", fid, kind, seq, send_ns)
```

禁止出现：

```python
qid
cycle_id
```

在 `make_pkt()` 中未定义仍引用会导致：

```text
NameError: name 'qid' is not defined
```

### 9.3 make_pkt 伪代码

```python
def make_pkt(src_mac, dst_mac, src_ip, dst_ip,
             fid, path_len, slot0, slot1, slot2, slot3,
             kind, seq, payload_size):
    send_ns = time.time_ns()
    app = APP_HDR.pack(b"TSN1", fid, kind, seq, send_ns)
    payload = app + b"x" * max(0, payload_size - len(app))

    return (
        Ether(src=src_mac, dst=dst_mac, type=0x1234)
        / TSN(
            next_type=0x0800,
            fid=fid,
            hop_index=0,
            path_len=path_len,
            slot0=slot0,
            slot1=slot1,
            slot2=slot2,
            slot3=slot3,
            flags=0,
        )
        / IP(src=src_ip, dst=dst_ip)
        / UDP(sport=10000 + fid, dport=4321)
        / Raw(payload)
    )
```

### 9.4 slot stack 生成

默认 4 跳：

```python
path_len = session.get("path_len", 4)
slots_per_cycle = cfg["tsn"].get("slots_per_cycle", 8)
hop_slot_offsets = session.get("hop_slot_offsets", [0, 1, 2, 3])

slot_list = [
    (event["slot"] + offset) % slots_per_cycle
    for offset in hop_slot_offsets
]

slot0, slot1, slot2, slot3 = slot_list[:4]
```

示例：

```text
event slot = 0
hop_slot_offsets = [0,1,2,3]
slot_stack = [0,1,2,3]
```

### 9.5 TSN 调用

```python
pkt = make_pkt(
    src_mac, dst_mac,
    src_ip, dst_ip,
    fid,
    path_len,
    slot0, slot1, slot2, slot3,
    KIND_TSN,
    seq[fid],
    session.get("tsn_payload", 300),
)
```

### 9.6 BE/BG 调用

推荐 BE 仍进入 queue0。

方案 A：BE 不带 TSN header。

方案 B：BE 带 TSN header，slot_stack 全部填 BE slot：

```python
pkt = make_pkt(
    src_mac, dst_mac,
    src_ip, dst_ip,
    bg_flow["fid"],
    0,
    7, 7, 7, 7,
    KIND_BG,
    seq,
    session.get("bg_payload", 1200),
)
```

如果走方案 B，P4 仍会解析为 TSN header，并根据 slot7 映射到 queue0。

验收：

```bash
python3 -m py_compile ~/tsn-lab/traffic/send_from_json.py
```

## 10. Step 7：修改 recv_from_json.py

文件：

```text
~/tsn-lab/traffic/recv_from_json.py
```

### 10.1 Scapy TSN header

必须与 sender/P4 一致。

### 10.2 APP_HDR

```python
APP_HDR = struct.Struct("!4sHBIQ")
```

unpack：

```python
magic, fid, kind, seq, send_ns = APP_HDR.unpack(raw[:APP_HDR.size])
```

统计 key：

```python
key = (kind_name, fid)
```

不要使用旧字段：

```python
qid
cycle_id
```

### 10.3 CSV 字段

建议：

```python
fieldnames=[
    "recv_ns",
    "kind",
    "fid",
    "hop_index",
    "path_len",
    "slot0",
    "slot1",
    "slot2",
    "slot3",
    "flags",
    "seq",
    "delay_us",
]
```

rows：

```python
rows.append({
    "recv_ns": recv_ns,
    "kind": kind_name,
    "fid": fid,
    "hop_index": tsn_hdr.hop_index if tsn_hdr else -1,
    "path_len": tsn_hdr.path_len if tsn_hdr else -1,
    "slot0": tsn_hdr.slot0 if tsn_hdr else -1,
    "slot1": tsn_hdr.slot1 if tsn_hdr else -1,
    "slot2": tsn_hdr.slot2 if tsn_hdr else -1,
    "slot3": tsn_hdr.slot3 if tsn_hdr else -1,
    "flags": tsn_hdr.flags if tsn_hdr else -1,
    "seq": seq,
    "delay_us": f"{delay_us:.3f}",
})
```

验收：

```bash
python3 -m py_compile ~/tsn-lab/traffic/recv_from_json.py
```

## 11. Step 8：修改 simple_switch.cpp

文件：

```text
~/Workspace/P4/behavioral-model/targets/simple_switch/simple_switch.cpp
```

目标：实现 TSN 优先、BE 空隙补发。

### 11.1 GCL 推荐

使用：

```text
[1, 2, 3, 1, 2, 3, 1, 0]
```

含义：

```text
slot0 -> queue1
slot1 -> queue2
slot2 -> queue3
slot3 -> queue1
slot4 -> queue2
slot5 -> queue3
slot6 -> queue1
slot7 -> queue0
```

### 11.2 Scheduler 伪代码

替换原有 group scan 逻辑。

```cpp
int base_queue = TSN_GCL[slot_id];
bool popped = false;

if (base_queue >= 1 && base_queue <= 3) {
    popped = egress_buffers.try_pop_back_priority(
        worker_id,
        static_cast<size_t>(base_queue),
        &port,
        &queue_idx,
        &packet);

    if (!popped) {
        popped = egress_buffers.try_pop_back_priority(
            worker_id,
            static_cast<size_t>(0),
            &port,
            &queue_idx,
            &packet);
    }
} else if (base_queue == 0) {
    popped = egress_buffers.try_pop_back_priority(
        worker_id,
        static_cast<size_t>(0),
        &port,
        &queue_idx,
        &packet);
}

if (popped) {
    break;
}

std::this_thread::sleep_for(std::chrono::microseconds(100));
```

### 11.3 日志建议

输出：

```text
now_us
slot_id
base_queue
queue_idx
priority
egress_port
```

日志格式示例：

```cpp
bm::Logger::get()->info(
    "CSQF dequeue now_us={} slot_id={} base_queue={} "
    "egress_port={} queue_idx={} priority={}",
    now_us,
    slot_id,
    base_queue,
    port,
    queue_idx,
    SSWITCH_PRIORITY_QUEUEING_NB_QUEUES - 1 - queue_idx);
```

验收：

```bash
grep -n "CSQF dequeue" ~/Workspace/P4/behavioral-model/targets/simple_switch/simple_switch.cpp
```

## 12. Step 9：修改 GCL 生成

文件：

```text
~/tsn-lab/python-controller/topo_from_json_bg.py
```

或配置：

```text
~/tsn-lab/configs/tsn_6sw_4host.json
```

当前建议所有交换机先使用统一 GCL：

```text
[1, 2, 3, 1, 2, 3, 1, 0]
```

这样更容易验证：

```text
slot_stack 指令是否被正确解释。
```

先不要为每个交换机设置不同 offset，避免多变量干扰。

验收：

运行脚本后确认：

```bash
cat /tmp/tsn_gcl_s1.txt
cat /tmp/tsn_gcl_s2.txt
...
```

应看到统一 GCL。

## 13. Step 10：修改 run_test_simple.sh

文件：

```text
~/tsn-lab/scripts/run_test_simple.sh
```

### 13.1 CSV 字段

新字段：

```text
recv_ns,kind,fid,hop_index,path_len,slot0,slot1,slot2,slot3,flags,seq,delay_us
```

### 13.2 延迟分析表

推荐：

```text
SESSION KIND FID COUNT AVG(us) P50(us) P95(us) P99(us) MAX(us) ANOMALY
```

不再显示：

```text
QID
CYCLE
```

### 13.3 DROP 统计

按：

```text
session + kind + fid
```

汇总计算。

不要按：

```text
slot
hop
cycle
```

单独计算 DROP。

### 13.4 Slot 统计

增加：

```text
SESSION FID SLOT_STACK COUNT ANOMALY
```

示例：

```text
h1_h3 101 [0,1,2,3] 250 0
```

## 14. Step 11：编译

### 14.1 编译 P4

命令示例：

```bash
cd ~/tsn-lab/p4src
p4c-bm2-ss --p4v 16 \
  --p4runtime-files ~/tsn-lab/build/tsn_basic.p4info.txt \
  -o ~/tsn-lab/build/tsn_basic.json \
  tsn_basic.p4
```

验收：

```bash
ls -lh ~/tsn-lab/build/tsn_basic.json
ls -lh ~/tsn-lab/build/tsn_basic.p4info.txt
```

### 14.2 编译 BMv2

命令示例：

```bash
cd ~/Workspace/P4/behavioral-model
make -C targets/simple_switch -j$(nproc)
make -C targets/simple_switch_grpc -j$(nproc)
sudo make -C targets/simple_switch_grpc install
sudo ldconfig
```

注意：

```text
如果需要 sudo 密码，应由用户在 VM 终端输入。
```

## 15. Step 12：最小测试

运行：

```bash
bash ~/tsn-lab/scripts/run_test_simple.sh
```

第一轮只看是否跑通：

```text
send_h1.log 无 Traceback
send_h2.log 无 Traceback
recv CSV 非空
s1-s6 enqueue/dequeue 非 0
```

如果出现空表，优先检查：

```text
1. sender 是否 NameError；
2. APP_HDR sender/receiver 是否一致；
3. Scapy header 与 P4 header 是否一致；
4. P4 是否重新编译；
5. simple_switch_grpc 是否安装了新版本；
6. hop_index 是否越界。
```

## 16. Step 13：验收标准

### 16.1 基本跑通

必须满足：

```text
Delay Analysis 非空
switch enqueue/dequeue 非 0
send logs 无 Traceback
recv CSV 有数据
```

### 16.2 hop_index 验收

4 跳路径接收端应看到：

```text
hop_index = 4
```

如果为：

```text
0:
  说明 hop_index 未前移

1/2/3:
  说明路径中某处未处理或转发异常
```

### 16.3 slot_stack 验收

对于 fid=101，预期：

```text
slot_stack = [0,1,2,3]
```

对于 fid=102，如果 base slot 为 1：

```text
slot_stack = [1,2,3,4]
```

对于 fid=103，如果 base slot 为 2：

```text
slot_stack = [2,3,4,5]
```

### 16.4 BE 空隙补发验收

日志中应能看到：

```text
当前 slot 对应 TSN queue；
如果 TSN queue 有包，dequeue TSN；
如果 TSN queue 空，dequeue queue0。
```

BE 延迟可能比之前上升，这是正常的。

## 17. 常见错误与定位

### 17.1 Delay Analysis 空

优先看：

```bash
cat <result_dir>/send_h1.log
cat <result_dir>/send_h2.log
```

常见错误：

```text
NameError: qid is not defined
struct.error: pack expected ...
Scapy field name mismatch
```

### 17.2 交换机 enqueue/dequeue 为 0

说明没有有效包进入交换机。

检查：

```text
sender 是否崩溃；
netns 是否存在；
P4 parser 是否接受 EtherType 0x1234；
Scapy header 与 P4 header 字段顺序是否一致。
```

### 17.3 接收端 hop_index 不是 4

检查：

```text
tsn_queue.p4 是否执行 advance_hop_index；
advance 是否发生在 deparser 前；
是否每个交换机都加载了新 P4 JSON。
```

### 17.4 TSN 延迟仍然高

检查：

```text
slot_stack 是否落入 BE slot；
slot -> queue 映射是否一致；
simple_switch.cpp scheduler 是否仍在 group scan；
BE 是否仍然抢占 TSN；
TSN 包是否早到/晚到。
```

## 18. Agent 最终汇报格式

Agent 完成修改后，应汇报：

```text
已修改文件：
- headers.p4
- custom_headers.p4
- parsers.p4
- tsn_queue.p4
- send_from_json.py
- recv_from_json.py
- simple_switch.cpp
- run_test_simple.sh

已完成验证：
- P4 编译通过 / 未通过
- Python py_compile 通过 / 未通过
- BMv2 编译安装完成 / 未完成
- run_test_simple.sh 结果目录
- send logs 是否有 Traceback
- CSV 是否非空
- switch enqueue/dequeue 是否非 0
```

如果有失败，不要只说失败，要给出：

```text
失败文件
失败日志
下一步修复点
```

## 19. 最终一句话

本方案实现：

```text
slot_stack + hop_index 指针式逐跳调度；
交换机本地 slot -> queue 映射；
TSN queue 优先发送；
BE queue 仅在 TSN queue 为空时机会式补发。
```

它是当前 CSQF v2 最适合实验落地的版本。

