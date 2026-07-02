# CSQF v1 代码修改清单 (Diff 风格)

> 分支: `csqf-v1` · 基于 `basic-baseline`

---

## 1. `p4src/include/headers.p4` — TSN 包头加 cycle_id

**位置**：`header tsn_t` 结构体

```diff
 header tsn_t {
     bit<16> next_type;
     bit<16> fid;
     bit<8>  qid;
+    bit<8>  cycle_id;   // 调度周期组 (0 或 1)
     bit<8>  flags;
 }
```

---

## 2. `p4src/include/custom_headers.p4` — metadata 加 cycle_id

**位置**：`struct local_metadata_t`

```diff
 struct local_metadata_t {
     bit<16> l4_src_port;
     ...
     bit<8>  qid;
+    bit<8>  cycle_id;
 }
```

---

## 3. `p4src/include/parsers.p4` — parser 提取 cycle_id

**位置**：`state parse_tsn`

```diff
 state parse_tsn {
     packet.extract(hdr.tsn);
     local_metadata.is_tsn = 1w1;
     local_metadata.fid = hdr.tsn.fid;
     local_metadata.qid = hdr.tsn.qid;
+    local_metadata.cycle_id = hdr.tsn.cycle_id;
     transition select(hdr.tsn.next_type) { ... }
 }
```

---

## 4. `p4src/include/tsn_queue.p4` — 优先级映射 (核心)

**位置**：`control tsn_queue_control` → `apply` 块

```diff
- if (local_metadata.is_tsn == 1w1) {
-     standard_metadata.priority = local_metadata.qid[2:0];
- } else {
-     standard_metadata.priority = 3w7;
- }

+ if (local_metadata.is_tsn == 1w1) {
+     // CSQF v1: cycle_id-aware queue mapping
+     // cycle_id=0 -> qid 6/5/4 -> prio 6/5/4 -> queue 1/2/3
+     // cycle_id=1 -> qid 6/5/4 -> prio 3/2/1 -> queue 4/5/6
+     if (local_metadata.cycle_id[0:0] == 1w0) {
+         standard_metadata.priority = local_metadata.qid[2:0];
+     } else {
+         standard_metadata.priority = local_metadata.qid[2:0] - 3w3;
+     }
+ } else {
+     standard_metadata.priority = 3w7;   // BG -> queue 0
+ }
```

**映射表**：

| cycle_id | qid | priority | queue_idx |
|----------|-----|----------|-----------|
| 0 | 6 | 6 | 1 |
| 0 | 5 | 5 | 2 |
| 0 | 4 | 4 | 3 |
| 1 | 6 | 3 | 4 |
| 1 | 5 | 2 | 5 |
| 1 | 4 | 1 | 6 |
| — | 7 | 7 | 0 (BG) |

---

## 5. `traffic/send_from_json.py` — 发送端 (3 处)

### 5a. Scapy TSN 类 (L5-11)

```diff
 class TSN(Packet):
     name = "TSN"
     fields_desc = [
         ShortField("next_type", 0x0800),
         ShortField("fid", 0),
         ByteField("qid", 0),
+        ByteField("cycle_id", 0),
         ByteField("flags", 0),
     ]
```

### 5b. APP_HDR 结构 + make_pkt 函数 (L46, L72, L80)

```diff
-APP_HDR = struct.Struct("!4sHBBIQ")
+APP_HDR = struct.Struct("!4sHBBBQ")

-def make_pkt(src_mac, dst_mac, src_ip, dst_ip, fid, qid, kind, seq, payload_size):
+def make_pkt(src_mac, dst_mac, src_ip, dst_ip, fid, qid, cycle_id, kind, seq, payload_size):
     send_ns = time.time_ns()
-    app = APP_HDR.pack(b"TSN1", fid, qid, kind, seq, send_ns)
+    app = APP_HDR.pack(b"TSN1", fid, qid, cycle_id, kind, seq, send_ns)
     ...
     return (
         Ether(src=src_mac, dst=dst_mac, type=0x1234)
-        / TSN(next_type=0x0800, fid=fid, qid=qid, flags=0)
+        / TSN(next_type=0x0800, fid=fid, qid=qid, cycle_id=cycle_id, flags=0)
         / IP(src=src_ip, dst=dst_ip)
         ...
     )
```

### 5c. tsn_sender 中计算 cycle_id (L96)

```diff
+            # CSQF: cycle_id = (cycle % 2)
+            cycle_id = int(cycle % 2)
+
             pkt = make_pkt(src_mac, dst_mac,
                 src_ip, dst_ip,
-                fid, qid, KIND_TSN, seq[fid],
+                fid, qid, cycle_id, KIND_TSN, seq[fid],
                 session.get("tsn_payload", 300),
             )
```

### 5d. background_sender 中 BG 流传 cycle_id=0 (L140)

```diff
         pkt = make_pkt(
             src_mac, dst_mac,
             src_ip, dst_ip,
-            bg_flow["fid"], bg_flow["qid"], KIND_BG, seq,
+            bg_flow["fid"], bg_flow["qid"], 0, KIND_BG, seq,
             session.get("bg_payload", 1200),
         )
```

---

## 6. `traffic/recv_from_json.py` — 接收端 (3 处)

### 6a. Scapy TSN 类 (与 sender 对称)

```diff
 class TSN(Packet):
     fields_desc = [
         ShortField("next_type", 0x0800),
         ShortField("fid", 0),
         ByteField("qid", 0),
+        ByteField("cycle_id", 0),
         ByteField("flags", 0),
     ]
```

### 6b. APP_HDR unpack (L33, L57)

```diff
-APP_HDR = struct.Struct("!4sHBBIQ")
+APP_HDR = struct.Struct("!4sHBBBQ")

-    magic, fid, qid, kind, seq, send_ns = APP_HDR.unpack(raw[:APP_HDR.size])
+    magic, fid, qid, cycle_id, kind, seq, send_ns = APP_HDR.unpack(raw[:APP_HDR.size])
```

### 6c. CSV 输出 (L76, L103)

```diff
     rows.append({
         "recv_ns": recv_ns,
         "kind": kind_name,
         "fid": fid,
         "qid": qid,
+        "cycle_id": cycle_id,
         "seq": seq,
         "delay_us": f"{delay_us:.3f}",
     })

-    fieldnames=["recv_ns", "kind", "fid", "qid", "seq", "delay_us"],
+    fieldnames=["recv_ns", "kind", "fid", "qid", "cycle_id", "seq", "delay_us"],
```

---

## 7. `targets/simple_switch/simple_switch.cpp` — BMv2 调度器 (2 处)

### 7a. 删除 GCL slot 调度，改为全队列扫描 (L715-830)

```diff
-    static constexpr int TSN_IDLE_QUEUE = -1;
+    // static constexpr int TSN_IDLE_QUEUE = -1;  // CSQF: unused

     static const std::array<int, ...> TSN_GCL = []() { ... }();  // 保留但 unused

     while (true) {
         ...

-        int target_queue_idx = TSN_GCL[slot_id];
-
-        if (target_queue_idx == TSN_IDLE_QUEUE) {
-            std::this_thread::sleep_for(std::chrono::microseconds(100));
-            continue;
-        }
-
-        bool popped = egress_buffers.try_pop_back_priority(
-            worker_id,
-            static_cast<size_t>(target_queue_idx),
-            &port, &queue_idx, &packet);

+        // CSQF v1-A: P4 already mapped cycle→queue; scan all queues
+        // BG queue 0 first, then TSN queues 1..6 in priority order
+        bool popped = false;
+        popped = egress_buffers.try_pop_back_priority(
+            worker_id, static_cast<size_t>(0), &port, &queue_idx, &packet);
+
+        if (!popped) {
+            for (size_t q = 1; q < SSWITCH_PRIORITY_QUEUEING_NB_QUEUES; q++) {
+                popped = egress_buffers.try_pop_back_priority(
+                    worker_id, q, &port, &queue_idx, &packet);
+                if (popped) break;
+            }
+        }
```

### 7b. phase 文件增加 cycle_group (L85, write_tsn_phase_file 函数)

```diff
     out << "mono_ns=" << mono_ns << "\n"
         << "bmv2_now_us=" << now_us << "\n"
         ...
         << "cycle_us=" << cycle_us << "\n";
+    uint64_t total_cycle = now_us / cycle_us;
+    size_t cycle_group = static_cast<size_t>(total_cycle % 2);
+    out << "cycle_group=" << cycle_group << "\n";
```

---

## 8. `scripts/run_test_simple.sh` — 分析输出加 CYCLE 列

### 8a. 表头 (L117)

```diff
- echo "SESSION    KIND    FID   QID     COUNT    AVG(us)   ...   ANOMALY"
+ echo "SESSION    KIND    FID   QID  CYCLE   COUNT    AVG(us)   ...   ANOMALY"
```

### 8b. 分组键 (L131)

```diff
- key = (row['kind'], int(row['fid']), int(row['qid']))
+ key = (row['kind'], int(row['fid']), int(row['qid']), int(row.get('cycle_id', 0)))
```

### 8c. 循环解包 + 打印 (L138, L140)

```diff
- for (kind, fid, qid), delays in sorted(groups.items()):
+ for (kind, fid, qid, cyc), delays in sorted(groups.items()):

- print(f"{sess:8s}  {kind:>6s}  {fid:>4d}  {qid:>4d}  {len(delays):>6d}  ..."
+ print(f"{sess:8s}  {kind:>6s}  {fid:>4d}  {qid:>4d}  {cyc:>5d}  {len(delays):>6d}  ..."
```

---

## 数据流总览

```
Sender (Python)                  BMv2 Switch                     Receiver (Python)
─────────────────                ──────────────                  ─────────────────
                                 
cycle_id = cycle % 2
  ↓
make_pkt(
  fid, qid, cycle_id, ...)
  ↓
TSN header {qid, cycle_id}       P4 parser                         sniff()
  ↓                                 ↓                                ↓
Ethernet packet ──────────────→  extract hdr.tsn                  TSN.next_type
                                   ↓                                ↓
                                 ingress:                         cycle_id from
                                 if cycle_id==0:                  APP_HDR.unpack()
                                   prio = qid                       ↓
                                 else:                            CSV:
                                   prio = qid - 3                kind,fid,qid,cycle_id,delay_us
                                   ↓
                                 queue_idx = 7 - prio
                                 (cycle0→1,2,3 / cycle1→4,5,6)
                                   ↓
                                 scheduler:
                                 扫描 queue 0→1→2→3→4→5→6→7
                                   ↓
                                 出队 → 下一跳
```
