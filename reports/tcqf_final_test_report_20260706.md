# TCQF Cycle Tag 确定性调度 — Final 测试报告

测试时间：2026-07-06  
分支：`tcqf`  
机制：TCQF cycle-tag based forwarding  
对比配置：默认 TCQF 与 TCQF-strict-BE

---

## 1. 测试配置

| 项目 | 默认 TCQF | TCQF-strict-BE |
|---|---|---|
| 拓扑 | 6 交换机 + 4 主机 | 6 交换机 + 4 主机 |
| 配置文件 | `tcqf_6sw_4host.json` | `tcqf_strict_be_6sw_4host.json` |
| h1→h3 | h1 → s1 → s2 → s5 → s6 → h3 | 同左 |
| h2→h4 | h2 → s1 → s3 → s4 → s6 → h4 | 同左 |
| TSN header | `next_type, fid, kind, cycle_tag, ttl, flags` | 同左 |
| 调度语义 | packet 携带 `cycle_tag`，交换机本地 remap 到下一服务 cycle | 同左 |
| 默认 cycle remap | 跳过 BE cycle，进入下一 TSN service cycle | 同左 |
| GCL | `[1,2,3,0,1,2,3,0]` | `[1,2,3,1,2,3,1,0]` |
| BE 服务窗口 | slot 3、slot 7 | 仅 slot 7 |
| BG 初始 cycle_tag | 3 | 7 |
| 队列映射 | queue1/2/3 为 TSN，queue0 为 BG | 同左 |

说明：

- 默认 TCQF 保留两个 BE 服务窗口，因此 BG 有较多发送机会。
- TCQF-strict-BE 只保留 slot 7 给 BG，用于观察增强 BE 隔离后的副作用。
- 当前 TCQF 不再使用 CSQF 的 `slot_stack + hop_index`，而是使用 `cycle_tag` 逐跳映射。

---

## 2. 端到端延迟分析

### 2.1 默认 TCQF：`[1,2,3,0,1,2,3,0]`

| Session | Kind | FID | Count | AVG(μs) | P50(μs) | P95(μs) | P99(μs) | MAX(μs) | Anomaly |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| h1→h3 | BG | 200 | 467 | 18351 | 17293 | 34732 | 38377 | 46995 | 0 |
| h1→h3 | TSN | 101 | 250 | 46311 | 46137 | 47940 | 49319 | 73531 | 1 |
| h1→h3 | TSN | 102 | 250 | 46422 | 46256 | 47822 | 49321 | 64202 | 1 |
| h1→h3 | TSN | 103 | 250 | 46567 | 46243 | 47727 | 49407 | 92369 | 2 |
| h2→h4 | BG | 300 | 425 | 18453 | 17335 | 35339 | 37567 | 56925 | 0 |
| h2→h4 | TSN | 201 | 250 | 46464 | 46169 | 47988 | 51557 | 88755 | 2 |
| h2→h4 | TSN | 202 | 250 | 46328 | 46108 | 47524 | 48488 | 79627 | 1 |
| h2→h4 | TSN | 203 | 250 | 46380 | 46232 | 47437 | 49052 | 69891 | 1 |

默认 TCQF 总体特征：

- TSN P50 稳定在 46 ms 左右。
- TSN P95 稳定在 47-48 ms。
- TSN P99 大多低于 52 ms。
- TSN 异常包共 8/1500，异常率约 0.53%。
- BG 延迟较低，P50 约 17 ms，P95 约 35 ms，说明 BG 在 slot 3 和 slot 7 均获得服务机会。

---

### 2.2 TCQF-strict-BE：`[1,2,3,1,2,3,1,0]`

| Session | Kind | FID | Count | AVG(μs) | P50(μs) | P95(μs) | P99(μs) | MAX(μs) | Anomaly |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| h1→h3 | BG | 200 | 416 | 39784 | 38928 | 74225 | 76733 | 113044 | 95 |
| h1→h3 | TSN | 101 | 250 | 31587 | 33235 | 37452 | 39168 | 75627 | 2 |
| h1→h3 | TSN | 102 | 250 | 42202 | 44017 | 47862 | 76292 | 116989 | 7 |
| h1→h3 | TSN | 103 | 250 | 41489 | 44170 | 47584 | 51724 | 76086 | 2 |
| h2→h4 | BG | 300 | 429 | 40424 | 41398 | 74825 | 77541 | 81921 | 112 |
| h2→h4 | TSN | 201 | 250 | 31751 | 34299 | 37300 | 57001 | 78226 | 3 |
| h2→h4 | TSN | 202 | 250 | 41869 | 44391 | 47456 | 59848 | 115569 | 3 |
| h2→h4 | TSN | 203 | 250 | 41710 | 44511 | 47471 | 51154 | 87905 | 3 |

strict-BE 总体特征：

- BG P50 从默认 TCQF 的约 17 ms 上升到约 39-41 ms。
- BG P95 从约 35 ms 上升到约 74-75 ms。
- BG 异常包显著增加，说明 slot7-only 的 BE 限制已经生效。
- TSN 中 queue1 对应的 FID 101/201 明显变好，P50 降至约 33-34 ms。
- FID 102/202 与 FID 103/203 的尾延迟更不稳定，尤其 FID 102 的 P99 与 MAX 明显升高。

---

## 3. TCQF Header / Cycle 统计

### 3.1 默认 TCQF

默认 TCQF 本次未记录完整 `TSN Header Summary` 表，但从延迟结果看：

- 所有 TSN flow 均完整接收，单流 Count = 250。
- BG 无异常包，说明 BG 在两个 BE 服务窗口中获得了充足转发机会。
- TSN 异常包数量较低，说明 cycle-tag remap 机制整体稳定。

### 3.2 TCQF-strict-BE

| Session | FID | Cycle Tag | Count | Anomaly |
|---|---:|---:|---:|---:|
| h1→h3 | 101 | 0 | 125 | 2 |
| h1→h3 | 101 | 4 | 125 | 0 |
| h1→h3 | 102 | 1 | 125 | 6 |
| h1→h3 | 102 | 5 | 125 | 1 |
| h1→h3 | 103 | 2 | 125 | 2 |
| h1→h3 | 103 | 6 | 125 | 0 |
| h2→h4 | 201 | 0 | 125 | 3 |
| h2→h4 | 201 | 4 | 125 | 0 |
| h2→h4 | 202 | 1 | 125 | 2 |
| h2→h4 | 202 | 5 | 125 | 1 |
| h2→h4 | 203 | 2 | 125 | 2 |
| h2→h4 | 203 | 6 | 125 | 1 |

观察：

- 每个 TSN flow 被稳定分布到两个 cycle tag，每组 125 包。
- cycle tag 分布与发送 slot 一致，说明 TCQF header 解析与 cycle remap 机制工作正常。
- 异常主要集中在部分 cycle tag 上，如 h1→h3 的 FID 102 / cycle 1。

---

## 4. 异常包分析

### 4.1 异常包总览

| 配置 | 类型 | 总包数 | 异常数 | 异常率 |
|---|---|---:|---:|---:|
| 默认 TCQF | TSN | 1500 | 8 | 0.53% |
| 默认 TCQF | BG | 892 | 0 | 0.00% |
| TCQF-strict-BE | TSN | 1500 | 20 | 1.33% |
| TCQF-strict-BE | BG | 845 | 207 | 24.50% |

### 4.2 默认 TCQF 的异常特征

默认 TCQF 的 TSN 异常率较低：

- h1→h3：4/750，约 0.53%。
- h2→h4：4/750，约 0.53%。
- 两条路径异常率一致，说明机制不存在明显路径偏置。
- BG 无异常，说明 `[1,2,3,0,1,2,3,0]` 对 BG 较友好。

默认 TCQF 的主要特点是：

```text
TSN 延迟稳定，但整体等待时延较高；
BG 延迟较低，因为每周期有两个 BE 服务窗口。
```

### 4.3 strict-BE 的异常特征

strict-BE 的 BG 异常显著增加：

- h1→h3 BG：95/416，约 22.84%。
- h2→h4 BG：112/429，约 26.11%。

这是预期结果，因为 BG 只能在 slot 7 出队。

TSN 异常也从默认 TCQF 的 8 个增加到 20 个。主要原因不是 BG 抢占 TSN，而是 GCL 资源分配发生变化：

```text
strict-BE GCL = [1,2,3,1,2,3,1,0]

queue1: slot 0, slot 3, slot 6  -> 3/8 服务窗口
queue2: slot 1, slot 4          -> 2/8 服务窗口
queue3: slot 2, slot 5          -> 2/8 服务窗口
queue0: slot 7                  -> 1/8 服务窗口
```

因此：

- FID 101/201 对应 queue1，获得更多服务窗口，P50/P95 明显改善。
- FID 102/202 对应 queue2，没有获得额外服务窗口，且在新的 GCL 相位下尾延迟变差。
- FID 103/203 对应 queue3，也存在一定尾延迟波动。

---

## 5. 两种 TCQF 配置对比

| 指标 | 默认 TCQF | TCQF-strict-BE | 结论 |
|---|---:|---:|---|
| GCL | `[1,2,3,0,1,2,3,0]` | `[1,2,3,1,2,3,1,0]` | strict-BE 压缩 BG 服务窗口 |
| BG 服务窗口 | 2/8 | 1/8 | strict-BE 显著削弱 BG |
| BG P50 | 约 17 ms | 约 39-41 ms | strict-BE 下 BG 排队更明显 |
| BG P95 | 约 35 ms | 约 74-75 ms | strict-BE 下 BG 尾延迟显著升高 |
| BG 异常率 | 0% | 约 24.5% | strict-BE 达到隔离效果 |
| TSN P50 | 约 46 ms | 约 33-44 ms | strict-BE 对不同队列影响不均 |
| TSN P95 | 约 47-48 ms | 约 37-48 ms | 部分 flow 改善，部分 flow 持平 |
| TSN 异常率 | 0.53% | 1.33% | strict-BE 尾延迟更不稳定 |
| 适合作为主结果 | 是 | 否，适合作补充实验 | 默认 TCQF 更均衡 |

---

## 6. 关键发现

1. TCQF cycle-tag 机制验证通过：数据包头部仅维护 `cycle_tag`，交换机根据本地映射将其 remap 到下一个服务 cycle，并映射到本地 queue。测试结果中 TSN 单流 Count 均为 250，说明转发链路完整工作。

2. 默认 TCQF 延迟稳定性较好：TSN P50 集中在 46 ms 左右，P95 集中在 47-48 ms，P99 大多低于 52 ms。TSN 异常率约 0.53%，与 CSQF v2 final 的异常率接近。

3. 默认 TCQF 对 BG 较友好：由于 GCL 中 slot 3 和 slot 7 都服务 queue0，BG P50 仅约 17 ms，P95 约 35 ms，没有出现 >60 ms 异常。这说明默认 TCQF 不是强 BE 隔离配置。

4. strict-BE 成功压制 BG：将 GCL 改为 `[1,2,3,1,2,3,1,0]` 后，BG P95 上升到约 74-75 ms，异常率约 24.5%。这说明 BG 只在 slot 7 出队的限制确实生效。

5. strict-BE 不适合作为主 TCQF 结果：虽然 queue1 对应的 FID 101/201 明显改善，但 FID 102/202 和 FID 103/203 的尾延迟更不稳定，TSN 总异常率从 0.53% 上升到 1.33%。其根因是 GCL 对 TSN queue 的服务窗口分配不均。

6. 默认 TCQF 更适合作为论文/报告主版本：它在两条路径上表现均衡，TSN P95/P99 稳定，异常率低；strict-BE 更适合作为“增强 BE 隔离的副作用分析”。

---

## 7. 与 CSQF v2 的关系

| 指标 | CSQF v2 slot stack | 默认 TCQF | 说明 |
|---|---:|---:|---|
| 包头机制 | `slot_stack + hop_index` | `cycle_tag` | TCQF 头部更简洁 |
| 调度控制 | 源端写入逐跳 slot | 交换机本地 cycle remap | TCQF 控制权更偏逐跳本地 |
| TSN P50 | 约 36-37 ms | 约 46 ms | TCQF 引入更固定的周期等待 |
| TSN P95 | 约 37-40 ms | 约 47-48 ms | TCQF 时延更高但分布集中 |
| TSN 异常率 | 约 0.47% | 约 0.53% | 两者接近 |
| BG 表现 | P50 约 39-45 ms | P50 约 17 ms | 默认 TCQF 的 BG 服务窗口更多 |
| 机制定位 | 源路由式 slot 调度 | tagged cycle remapping | 二者可形成清晰机制对比 |

结论：

```text
CSQF v2 更适合展示 source-routed slot scheduling；
TCQF 更适合展示 local cycle remapping；
默认 TCQF 是主对比版本；
TCQF-strict-BE 是补充隔离实验。
```

---

## 8. 最终结论

本轮 TCQF 测试验证了 cycle-tag based forwarding 原型的可行性。默认 TCQF 使用 `[1,2,3,0,1,2,3,0]` GCL，在两条 4-hop 路径上均获得稳定的 TSN 延迟分布，TSN 异常率约 0.53%，具备作为最终对比机制的条件。

TCQF-strict-BE 使用 `[1,2,3,1,2,3,1,0]` GCL，将 BG 限制到 slot 7，成功提高 BG 延迟与异常率，证明 BE 隔离增强有效。但由于 TSN queue 服务窗口分配不均，部分 TSN flow 的尾延迟变差，因此不建议作为主版本，只建议作为补充实验用于说明 BE 隔离与 TSN queue 公平性之间的权衡。

推荐采用：

```text
主结果：默认 TCQF [1,2,3,0,1,2,3,0]
补充结果：TCQF-strict-BE [1,2,3,1,2,3,1,0]
```

