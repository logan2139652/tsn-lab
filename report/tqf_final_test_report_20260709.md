# TQF Timestamp-to-Slot 确定性调度 — Final 测试报告

测试时间：2026-07-09  
分支：`tqf`  
机制：TQF timestamp-to-slot scheduling  
最终版本：TSN priority + limited BE fallback  
基线版本：`tqf-v1` tag

---

## 1. 测试配置

| 项目 | TQF-v1 d1 | TQF-v1 d2 | TQF all-slot fallback | TQF strict-BE |
|---|---|---|---|---|
| 拓扑 | 6 交换机 + 4 主机 | 同左 | 同左 | 同左 |
| 配置文件 | `tqf_pow2_d1_6sw_4host.json` | `tqf_pow2_d2_6sw_4host.json` | `tqf_pow2_d1_6sw_4host.json` | 同左 |
| 时间基准 | `standard_metadata.ingress_global_timestamp` | 同左 | 同左 | 同左 |
| slot 大小 | 8192 us | 8192 us | 8192 us | 8192 us |
| cycle 大小 | 65536 us | 65536 us | 65536 us | 65536 us |
| TSN 入队 | `arrival_slot + 1` | `arrival_slot + 2` | `arrival_slot + 1`，映射到 TSN queue | `arrival_slot + 1`，映射到 TSN queue |
| BE/BG 入队 | 同 TSN，一起进入 timestamp queue | 同 TSN，一起进入 timestamp queue | 固定进入 `queue 0` | 固定进入 `queue 0` |
| BE fallback | 无独立 BE queue | 无独立 BE queue | 所有 slot 均允许 BE fallback | 仅 slot 0/4 允许 BE fallback |
| 异常阈值 | 49152 us | 49152 us | 49152 us | 49152 us |

说明：

- TQF-v1 的目标是验证 P4 中 timestamp-to-slot 计算是否可行。
- d1 表示 `out_slot = arrival_slot + 1 mod 8`。
- d2 表示 `out_slot = arrival_slot + 2 mod 8`。
- 后续版本将 BE/BG 与 TSN 分队列，`queue 0` 固定给 BE/BG，TSN 使用 `queue 1..7`。
- strict-BE 版本只允许 slot 0 和 slot 4 使用 BE fallback，从而限制 BE/BG 对 TSN 空隙的利用。

---

## 2. TQF-v1：timestamp-to-slot 基线

### 2.1 TQF-v1 d1 结果

| Session | Kind | FID | Count | AVG(us) | P50(us) | P95(us) | P99(us) | MAX(us) | Anomaly |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| h1->h3 | BG | 200 | 454 | 19551 | 19075 | 23913 | 61021 | 154563 | 8 |
| h1->h3 | TSN | 101 | 306 | 21534 | 16360 | 72131 | 73705 | 171284 | 18 |
| h1->h3 | TSN | 102 | 305 | 17998 | 16319 | 24215 | 26614 | 108997 | 3 |
| h1->h3 | TSN | 103 | 305 | 16346 | 15982 | 24222 | 45609 | 86386 | 3 |
| h2->h4 | BG | 300 | 429 | 27510 | 27215 | 31971 | 75040 | 166436 | 10 |
| h2->h4 | TSN | 201 | 305 | 29936 | 25108 | 56098 | 74652 | 121009 | 17 |
| h2->h4 | TSN | 202 | 306 | 27946 | 25056 | 32585 | 58763 | 119506 | 5 |
| h2->h4 | TSN | 203 | 305 | 26725 | 24422 | 32475 | 67044 | 107493 | 6 |

观察：

- d1 的平均时延较低，多数 TSN flow 的 P50 位于 16-27 ms。
- FID 101/201 的 P95/P99 明显偏高，说明紧邻下一 slot 的 d1 策略存在赶窗失败。
- 该版本中 BE/BG 与 TSN 都进入 timestamp queue，机制语义不够清晰。

### 2.2 TQF-v1 d2 结果

| Session | Kind | FID | Count | AVG(us) | P50(us) | P95(us) | P99(us) | MAX(us) | Anomaly |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| h1->h3 | BG | 200 | 424 | 44838 | 45293 | 52187 | 54605 | 83402 | 120 |
| h1->h3 | TSN | 101 | 305 | 40830 | 45027 | 53279 | 54702 | 103054 | 36 |
| h1->h3 | TSN | 102 | 305 | 44629 | 45334 | 53592 | 55154 | 95839 | 67 |
| h1->h3 | TSN | 103 | 305 | 45884 | 45494 | 47423 | 52090 | 88650 | 7 |
| h2->h4 | BG | 300 | 446 | 47728 | 47758 | 58529 | 60502 | 64306 | 175 |
| h2->h4 | TSN | 201 | 305 | 47872 | 45586 | 54540 | 62396 | 111754 | 72 |
| h2->h4 | TSN | 202 | 305 | 46040 | 45597 | 58890 | 61684 | 87900 | 103 |
| h2->h4 | TSN | 203 | 305 | 47682 | 45877 | 54149 | 55744 | 80130 | 77 |

观察：

- d2 提供了更大的赶窗余量，但每跳额外等待一个 slot。
- 4-hop 路径上额外等待累计明显，P50 普遍上升到约 45 ms。
- d2 的异常数明显高于 d1，因此不适合作为主版本。

---

## 3. TQF 分队列版本

### 3.1 All-slot BE fallback

该版本将 BE/BG 固定进入 `queue 0`，TSN 进入 `queue 1..7`。出队时当前 slot 先服务 TSN queue，若为空，则所有 slot 都允许 BE fallback。

| Session | Kind | FID | Count | AVG(us) | P50(us) | P95(us) | P99(us) | MAX(us) | Anomaly |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| h1->h3 | BG | 200 | 428 | 5276 | 4781 | 7681 | 11782 | 54013 | 1 |
| h1->h3 | TSN | 101 | 305 | 27226 | 31629 | 32948 | 34253 | 51063 | 1 |
| h1->h3 | TSN | 102 | 305 | 24540 | 24192 | 25878 | 31545 | 72946 | 1 |
| h1->h3 | TSN | 103 | 306 | 21224 | 17176 | 32425 | 33951 | 81314 | 2 |
| h2->h4 | BG | 300 | 472 | 5616 | 4819 | 7563 | 25965 | 84502 | 4 |
| h2->h4 | TSN | 201 | 305 | 21772 | 23353 | 24847 | 38264 | 73418 | 1 |
| h2->h4 | TSN | 202 | 305 | 22164 | 16490 | 40339 | 42632 | 94340 | 2 |
| h2->h4 | TSN | 203 | 305 | 26114 | 29080 | 33992 | 35551 | 87761 | 2 |

观察：

- TSN 异常数显著下降，FID 101/201 的长尾问题基本消失。
- BG/BG 平均时延约 5 ms，说明 all-slot fallback 过于宽松，BE 几乎可以利用所有 TSN 空隙。
- 该版本适合证明 BE fallback 机制有效，但不适合作为最终 strict-BE 结果。

### 3.2 Strict-BE / limited BE fallback

最终版本进一步限制 BE fallback：仅 slot 0 和 slot 4 允许 BE/BG 在 TSN queue 为空时补发。

| Session | Kind | FID | Count | AVG(us) | P50(us) | P95(us) | P99(us) | MAX(us) | Anomaly |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| h1->h3 | BG | 200 | 489 | 53572 | 53818 | 67730 | 71901 | 123288 | 313 |
| h1->h3 | TSN | 101 | 305 | 29100 | 30717 | 37025 | 38216 | 72852 | 1 |
| h1->h3 | TSN | 102 | 306 | 25678 | 27597 | 29894 | 30671 | 67253 | 1 |
| h1->h3 | TSN | 103 | 305 | 24730 | 20886 | 36172 | 38527 | 67860 | 3 |
| h2->h4 | BG | 300 | 418 | 52945 | 52969 | 66738 | 68551 | 105403 | 259 |
| h2->h4 | TSN | 201 | 305 | 25448 | 27065 | 28526 | 29494 | 82210 | 2 |
| h2->h4 | TSN | 202 | 306 | 24865 | 20258 | 44196 | 44965 | 74564 | 1 |
| h2->h4 | TSN | 203 | 305 | 30409 | 35266 | 37030 | 38131 | 76261 | 2 |

---

## 4. 异常包统计

| 版本 | 类型 | 总包数 | 异常数 | 异常率 |
|---|---|---:|---:|---:|
| TQF-v1 d1 | TSN | 1832 | 52 | 2.84% |
| TQF-v1 d1 | BG | 883 | 18 | 2.04% |
| TQF-v1 d2 | TSN | 1830 | 362 | 19.78% |
| TQF-v1 d2 | BG | 870 | 295 | 33.91% |
| All-slot fallback | TSN | 1831 | 9 | 0.49% |
| All-slot fallback | BG | 900 | 5 | 0.56% |
| Strict-BE fallback | TSN | 1832 | 10 | 0.55% |
| Strict-BE fallback | BG | 907 | 572 | 63.07% |

分路径统计：

| 版本 | 路径 | 类型 | 总包数 | 异常数 | 异常率 |
|---|---|---|---:|---:|---:|
| Strict-BE fallback | h1->h3 | TSN | 916 | 5 | 0.55% |
| Strict-BE fallback | h2->h4 | TSN | 916 | 5 | 0.55% |
| Strict-BE fallback | h1->h3 | BG | 489 | 313 | 64.01% |
| Strict-BE fallback | h2->h4 | BG | 418 | 259 | 61.96% |

---

## 5. 关键发现

1. P4 timestamp-to-slot 机制可行：通过 `standard_metadata.ingress_global_timestamp[15:13]` 可以得到 8192 us 粒度下的 arrival slot，并在 BMv2 中完成基于 slot 的出队调度。

2. P4 与 C++ 必须使用同一时间基准：早期版本中 P4 使用 BMv2 ingress timestamp，而 C++ 使用系统 monotonic time，导致整体时隙相位错位。修复为 C++ 使用 `get_ts().count()` 后，整体时延从 130-200 ms 回落到可分析范围。

3. 固定 d1 与 d2 都不是最终最优策略：d1 延迟低但有赶窗失败，d2 余量更大但多跳等待累计过高。

4. TSN/BE 分队列是必要的：当 BE/BG 与 TSN 共同进入 timestamp queue 时，机制语义混合；分离后可以清楚表达 TSN priority。

5. All-slot fallback 保护 BE 过强：BE 平均延迟约 5 ms，说明 BE 几乎利用了所有 TSN 空隙，不适合作为 strict-BE 主结果。

6. Strict-BE fallback 达到目标：只允许 slot 0/4 fallback 后，TSN 异常率保持在 0.55%，BG 异常率上升至 63.07%，形成了明确的 TSN 优先语义。

---

## 6. 最终结论

本轮 TQF 实验证明，timestamp-to-slot 调度可以在 P4 + BMv2 中实现，并且通过 TSN/BE 分队列与受限 BE fallback，可以得到较清晰的确定性转发效果。

推荐采用以下版本作为 TQF 最终对比结果：

```text
TQF strict-BE:
  TSN: arrival_slot -> out_slot(d1) -> TSN queue 1..7
  BE : fixed queue 0
  Dequeue: current TSN queue first
  BE fallback: only slot 0 and slot 4
```

该版本的主要表现：

- TSN 总异常率：0.55%
- TSN P95：约 28-44 ms
- BG 总异常率：63.07%
- BG P50：约 53 ms

因此，TQF strict-BE 版本既保留了 TQF 的时间戳驱动调度特征，又通过 BE fallback 限制体现了 TSN 对背景流的调度保护。
