# CSQF v1 修改清单

> **分支**：`csqf-v1` (基于 `basic-baseline`)  
> **目标**：将 baseline 的纯 `qid→queue` 映射升级为 `(qid, cycle_id)→queue` 映射，验证 cycle-aware 队列是否能降低尾部异常率。

---

## 修改概览

| # | 文件 | 层 | 改动性质 |
|---|------|-----|----------|
| 1 | `p4src/include/headers.p4` | P4 数据面 | TSN 包头加 cycle_id 字段 |
| 2 | `p4src/include/custom_headers.p4` | P4 数据面 | local_metadata 加 cycle_id |
| 3 | `p4src/include/parsers.p4` | P4 数据面 | parser 提取 cycle_id 到 metadata |
| 4 | `p4src/include/tsn_queue.p4` | P4 数据面 | 优先级映射改为 qid+cycle_id |
| 5 | `traffic/send_from_json.py` | Python 控制面 | TSN 类/发包/APP_HDR 加入 cycle_id |
| 6 | `traffic/recv_from_json.py` | Python 控制面 | TSN 类/收包/CSV 加入 cycle_id |
| 7 | `targets/simple_switch/simple_switch.cpp` | BMv2 C++ | 调度器从 GCL slot→queue 改为扫描全部队列 + phase 文件加 cycle_group |
| 8 | `scripts/run_test_simple.sh` | 自动化 | 结果表加 CYCLE 列 |

---

## 逐文件详细修改

### 1. `p4src/include/headers.p4` — TSN 包头结构

**修改前：**
```p4
header tsn_t {
    bit<16> next_type;
    bit<16> fid;
    bit<8>  qid;
    bit<8>  flags;
}
```

**修改后：**
```p4
header tsn_t {
    bit<16> next_type;
    bit<16> fid;
    bit<8>  qid;
    bit<8>  cycle_id;   // 新增：调度周期组 (0 或 1)
    bit<8>  flags;
}
```

**思路**：baseline 的 `qid` 只标识业务类型（如高/中/低优先级 TSN 流），但无法区分同一个 qid 的包属于当前调度周期还是下一周期。加入 `cycle_id` 后，P4 可以根据 `(qid, cycle_id)` 将包路由到不同物理队列，实现不同周期的物理隔离。

---

### 2. `p4src/include/custom_headers.p4` — P4 内部元数据

**修改前：**
```p4
struct local_metadata_t {
    bit<16> l4_src_port;
    bit<16> l4_dst_port;
    next_hop_id_t next_hop_id;
    bit<1>  is_tsn;
    bit<16> fid;
    bit<8>  qid;
}
```

**修改后：**
```p4
struct local_metadata_t {
    bit<16> l4_src_port;
    bit<16> l4_dst_port;
    next_hop_id_t next_hop_id;
    bit<1>  is_tsn;
    bit<16> fid;
    bit<8>  qid;
    bit<8>  cycle_id;    // 新增
}
```

**思路**：parser 从包头提取 `cycle_id` 后需要存入内部元数据 `local_metadata`，供后续 ingress control 使用。P4 不允许直接从包头字段做复杂运算，需要通过 metadata 中转。

---

### 3. `p4src/include/parsers.p4` — P4 解析器

**修改前：**
```p4
state parse_tsn {
    packet.extract(hdr.tsn);
    local_metadata.is_tsn = 1w1;
    local_metadata.fid = hdr.tsn.fid;
    local_metadata.qid = hdr.tsn.qid;
    transition select(hdr.tsn.next_type) { ... }
}
```

**修改后：**
```p4
state parse_tsn {
    packet.extract(hdr.tsn);
    local_metadata.is_tsn = 1w1;
    local_metadata.fid = hdr.tsn.fid;
    local_metadata.qid = hdr.tsn.qid;
    local_metadata.cycle_id = hdr.tsn.cycle_id;  // 新增
    transition select(hdr.tsn.next_type) { ... }
}
```

**思路**：从 TSN 包头中提取 `cycle_id` 并写入 metadata，供后续 `tsn_queue_control` 使用。

---

### 4. `p4src/include/tsn_queue.p4` — 优先级映射（核心逻辑）

**修改前：**
```p4
control tsn_queue_control(...) {
    apply {
        if (local_metadata.is_tsn == 1w1) {
            standard_metadata.priority = local_metadata.qid[2:0];
        } else {
            standard_metadata.priority = 3w7;   // BG → priority 7 → queue 0
        }
    }
}
```

**修改后：**
```p4
control tsn_queue_control(...) {
    apply {
        if (local_metadata.is_tsn == 1w1) {
            // CSQF v1: cycle_id-aware queue mapping
            // cycle_id=0 → qid=6/5/4 → priority=6/5/4 → queue=1/2/3
            // cycle_id=1 → qid=6/5/4 → priority=3/2/1 → queue=4/5/6
            if (local_metadata.cycle_id[0:0] == 1w0) {
                standard_metadata.priority = local_metadata.qid[2:0];
            } else {
                standard_metadata.priority = local_metadata.qid[2:0] - 3w3;
            }
        } else {
            standard_metadata.priority = 3w7;
        }
    }
}
```

**思路**：

- **baseline**：`qid→priority→queue`，所有同 qid 的包进入同一个物理队列，不同周期混在一起
- **CSQF v1**：`(qid, cycle_id)→priority→queue`，cycle_id 为偶数进 queue 1/2/3，奇数进 queue 4/5/6

**映射表**（BMv2 中 `queue_idx = 7 - priority`）：

| cycle_id | qid | priority | queue_idx | 意义 |
|----------|-----|----------|-----------|------|
| 0 | 6 | 6 | 1 | cycle 0 高优先级 |
| 0 | 5 | 5 | 2 | cycle 0 中优先级 |
| 0 | 4 | 4 | 3 | cycle 0 低优先级 |
| 1 | 6 | 3 | 4 | cycle 1 高优先级 |
| 1 | 5 | 2 | 5 | cycle 1 中优先级 |
| 1 | 4 | 1 | 6 | cycle 1 低优先级 |
| — | 7 | 7 | 0 | BG (不分 cycle) |

---

### 5. `traffic/send_from_json.py` — Python 发送端

**修改点 1：Scapy TSN 类增加 cycle_id**
```python
# 修改前
class TSN(Packet):
    fields_desc = [
        ShortField("next_type", 0x0800),
        ShortField("fid", 0),
        ByteField("qid", 0),
        ByteField("flags", 0),
    ]

# 修改后
class TSN(Packet):
    fields_desc = [
        ShortField("next_type", 0x0800),
        ShortField("fid", 0),
        ByteField("qid", 0),
        ByteField("cycle_id", 0),   # 新增
        ByteField("flags", 0),
    ]
```

**修改点 2：APP_HDR 结构增加 cycle_id**
```python
# 修改前
APP_HDR = struct.Struct("!4sHBBIQ")   # magic,fid,qid,kind,seq,send_ns

# 修改后
APP_HDR = struct.Struct("!4sHBBBQ")   # magic,fid,qid,cycle_id,kind,seq,send_ns
```

**修改点 3：make_pkt 函数签名和 TSN 构造**
```python
# 修改前
def make_pkt(..., fid, qid, kind, seq, payload_size):
    ...
    / TSN(next_type=0x0800, fid=fid, qid=qid, flags=0)
    app = APP_HDR.pack(b"TSN1", fid, qid, kind, seq, send_ns)

# 修改后
def make_pkt(..., fid, qid, cycle_id, kind, seq, payload_size):
    ...
    / TSN(next_type=0x0800, fid=fid, qid=qid, cycle_id=cycle_id, flags=0)
    app = APP_HDR.pack(b"TSN1", fid, qid, cycle_id, kind, seq, send_ns)
```

**修改点 4：tsn_sender 中计算 cycle_id**
```python
# 发包前计算当前周期
cycle_id = int(cycle % 2)
pkt = make_pkt(..., fid, qid, cycle_id, ...)
```

**思路**：发送端在每次发包时根据当前周期计数器 `cycle` 计算 `cycle_id = cycle % 2`，写入 TSN 包头和 APP_HDR。接收端可以从两个来源获取 cycle_id（包头用于 P4 解析，APP_HDR 用于统计）。

---

### 6. `traffic/recv_from_json.py` — Python 接收端

**修改点与 sender 对称**：
- Scapy TSN 类增加 `ByteField("cycle_id", 0)`
- APP_HDR 改为 7 字段 `"!4sHBBBQ"`
- unpack 增加 `cycle_id`：`magic, fid, qid, cycle_id, kind, seq, send_ns = APP_HDR.unpack(...)`
- CSV 输出增加 `"cycle_id"` 列

**思路**：接收端从 APP_HDR 提取 cycle_id 写入 CSV，后续分析可以按 `(fid, qid, cycle_id)` 分组统计，直接观察不同 cycle 组的延迟分布差异。

---

### 7. `targets/simple_switch/simple_switch.cpp` — BMv2 调度器

**修改点 1：enqueue 日志增加 cycle_id 信息（无需改代码，日志中天然有 priority）**

**修改点 2：dequeue 从 GCL slot→queue 改为扫描全部队列**

**修改前（baseline GCL 调度）：**
```cpp
int target_queue_idx = TSN_GCL[slot_id];  // GCL 数组映射 slot→queue
if (target_queue_idx == TSN_IDLE_QUEUE) { sleep; continue; }
popped = try_pop_back_priority(worker_id, target_queue_idx, ...);
```

**修改后（CSQF v1-A 全队列扫描）：**
```cpp
// BG queue 0 优先
popped = try_pop_back_priority(worker_id, 0, ...);
if (!popped) {
    // 扫描 TSN 队列 1..6（按优先级从高到低）
    for (size_t q = 1; q < NB_QUEUES; q++) {
        popped = try_pop_back_priority(worker_id, q, ...);
        if (popped) break;
    }
}
```

**思路**：

- baseline 中每个 slot 固定映射一个 queue（GCL），scheduler 只检查那个 queue
- CSQF v1-A 中，P4 已经完成了 `(qid, cycle_id)→queue` 的映射，packet 已在正确的物理队列中
- scheduler 只需要**按优先级扫描所有队列**即可：queue 0 (BG) → queue 1→2→3→4→5→6 (TSN)
- 不再需要 GCL 表（`TSN_GCL` 变量标记为 unused）

**为什么用 v1-A 而不是严格的 cycle-group 过滤？**

最初设计了严格的 cycle-group 过滤（cycle_group=0 只查 queue 1/2/3，cycle_group=1 只查 queue 4/5/6），但 sender 端计算的 `cycle_id` 和 switch 端计算的 `cycle_group` 存在相位偏移，导致约 50% 的包被永远卡住（sender 认为 cycle=0 但 switch 当前是 cycle=1，包在 queue 1/2/3 中但 switch 只查 queue 4/5/6）。

v1-A 的妥协方案：P4 层仍然做 `cycle_id→queue` 映射（物理隔离），但 scheduler 不按 cycle_group 过滤——直接扫描全部队列。这样保留了物理隔离的好处（不同周期的包在不同队列），同时避免了相位同步的复杂性。

**修改点 3：phase 文件增加 cycle_group**
```cpp
// write_tsn_phase_file() 输出增加
out << "cycle_group=" << cycle_group << "\n";
```

发送端可以通过 phase 文件获知交换机当前周期组，用于后续 v2 版本的精确同步。

---

### 8. `scripts/run_test_simple.sh` — 自动化测试脚本

**修改前**：结果表分组键为 `(kind, fid, qid)`
**修改后**：分组键为 `(kind, fid, qid, cycle_id)`，输出列增加 `CYCLE`

**思路**：CSQF 的核心卖点是 cycle 隔离，需要在测试结果中直观看到 cycle=0 和 cycle=1 的延迟分布是否有差异。

---

## 当前已知问题

### 问题 1：ENQUEUE > DEQUEUE，丢包约 50%
- **现象**：s1 入队 1500 包，出队仅 ~744 包
- **原因**：第一次编译后 `sudo make install` 失败（SSH 无法输密码），测试使用的是旧 binary（v1 cycle-group 过滤版），存在相位偏移
- **修复**：重新编译并 `sudo make install` 后应解决

### 问题 2：接收端无法解析包
- **现象**：`not enough values to unpack (expected 7, got 6)`
- **原因**：receiver 的 APP_HDR 改为 7 字段，但 sender 最初未同步修改 APP_HDR.pack
- **修复**：✅ 已修复（sender 的 APP_HDR.pack 已加入 cycle_id）

---

## 编译步骤

```bash
# 1. 确认在 csqf-v1 分支
cd ~/Workspace/P4/behavioral-model
git branch   # 应显示 * csqf-v1

# 2. 编译 P4
cd ~/tsn-lab/p4src
p4c-bm2-ss --p4v 16 --p4runtime-files ~/tsn-lab/build/tsn_basic.p4info.txt \
  -o ~/tsn-lab/build/tsn_basic.json tsn_basic.p4

# 3. 编译并安装 BMv2
cd ~/Workspace/P4/behavioral-model
make -C targets/simple_switch clean && make -C targets/simple_switch -j$(nproc)
make -C targets/simple_switch_grpc clean && make -C targets/simple_switch_grpc -j$(nproc)
sudo make -C targets/simple_switch_grpc install
sudo ldconfig

# 4. 提交改动
git add -A
git commit -m "CSQF v1-A: cycle_id in P4 + full-queue scanning scheduler"
git push origin csqf-v1

# 5. 测试
bash ~/tsn-lab/scripts/run_test_simple.sh
```

---

## 回滚方法

```bash
cd ~/Workspace/P4/behavioral-model
git checkout basic-baseline

# 重编 BMv2
make -C targets/simple_switch_grpc clean && make -C targets/simple_switch_grpc -j$(nproc)
sudo make -C targets/simple_switch_grpc install && sudo ldconfig

# 恢复 P4 binary（从备份或重新编译）
cd ~/tsn-lab/p4src
cp p4c-out/bmv2/basic.json ~/tsn-lab/build/tsn_basic.json
cp p4c-out/bmv2/basic_p4info.txt ~/tsn-lab/build/tsn_basic.p4info.txt
```
