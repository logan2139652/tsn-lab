# TSN Lab — 拓扑配置文件

本目录存放 TSN（时间敏感网络）仿真实验的拓扑配置文件，供 `topo_from_json.py` 和 `controller_from_json.py` 读取。

---

## 配置文件一览

| 文件 | 拓扑规模 | 主机对 | 说明 |
|------|----------|--------|------|
| `tsn_2sw.json` | 2 交换机 / 2 主机 | h1 ↔ h2 | 基础单路径验证拓扑 |
| `tsn_6sw_4host.json` | 6 交换机 / 4 主机 | h1↔h3, h2↔h4 | 双路径环网拓扑，含冗余链路 |

---

## tsn_2sw.json

最简拓扑，用于单路径 TSN 功能验证。

```
h1 ── s1 ── s2 ── h2
```

- **路径**：h1 → s1 → s2 → h2（单向对称）
- **GCL**：s1 起始相位 `[1,2,3,0,...]`，s2 偏移 1 槽 `[0,1,2,3,...]`
- **流量**：3 条 TSN 流（fid 101/102/103，qid 6/5/4）+ 1 条背景流（fid 200，qid 7）
- **时隙分配**：槽 0/4 → fid101，槽 1/5 → fid102，槽 2/6 → fid103

---

## tsn_6sw_4host.json

双路径环网拓扑，两对主机并行传输，具备冗余链路。

```
h1 ─┐                           ┌─ h3
     s1 ─── s2 ─── s5 ───┐     │
h2 ─┘    │         │     s6 ───┘
         s3 ─── s4 ──────┘     │
              │    │            └─ h4
             s2──s3  s4──s5（环网冗余）
```

**路径 A（蓝）**：h1 → s1 → s2 → s5 → s6 → h3

**路径 B（粉）**：h2 → s1 → s3 → s4 → s6 → h4

**环网冗余链路**：s2↔s3、s4↔s5（当前路由未使用，备用）

### GCL 相位偏移

各交换机 GCL 依次错开 1 个时隙，形成时隙管道（pipeline），使数据包在整条链路上按时隙无碰撞转发：

| 交换机 | GCL 序列 | 相位偏移 |
|--------|----------|----------|
| s1 | `[1,2,3,0,1,2,3,0]` | +0 槽 |
| s2 | `[0,1,2,3,0,1,2,3]` | +1 槽 |
| s3 | `[0,1,2,3,0,1,2,3]` | +1 槽 |
| s4 | `[3,0,1,2,3,0,1,2]` | +2 槽 |
| s5 | `[3,0,1,2,3,0,1,2]` | +2 槽 |
| s6 | `[2,3,0,1,2,3,0,1]` | +3 槽 |

### TSN 同步参数

| 参数 | 值 | 说明 |
|------|----|------|
| `sync_switch` | s1 | 主同步源交换机 |
| `slot_us` | 10000 | 时隙宽度 10 ms |
| `cycle_us` | 80000 | 周期 80 ms（8 个时隙） |
| `lead_us` | 3000 | 前置提前量 3 ms |
| `phase_offset_us` | 0 | 全局相位偏移 |

### 流量配置（每路径）

| fid | qid | 优先级 | 时隙 | 类型 | 载荷 |
|-----|-----|--------|------|------|------|
| 101/201 | 6 | 高 | 槽 0, 4 | TSN | 300 B |
| 102/202 | 5 | 中 | 槽 1, 5 | TSN | 300 B |
| 103/203 | 4 | 中 | 槽 2, 6 | TSN | 300 B |
| 200/300 | 7 | 背景 | 无限制 | background | 1200 B @ 100 pps |

---

## JSON 字段说明

```
{
  "p4":       P4 编译产物路径（bmv2_json / p4info）
  "pipeline": P4 流表名称和 match 字段映射
  "switches": 各交换机配置（device_id / grpc_port / gcl / 临时文件路径）
  "hosts":    主机 IP 和 MAC
  "links":    拓扑连接（node1/node2/port1/port2/bw）
  "routes":   静态路由规则（in_port + src/dst_mac → out_port）
  "tsn":      TSN 时隙同步参数 + 流配置
  "traffic":  发送/接收端参数（接口/时长/CSV 输出路径）
}
```

---

## 启动方式

```bash
# 清理旧环境
sudo mn -c
sudo rm -f /tmp/s*-simple-switch-grpc.log.txt /tmp/tsn_gcl_*.txt /tmp/tsn_phase_*.txt

# 终端 1：启动 Mininet 拓扑
sudo ~/tsn-lab/python-controller/topo_from_json.py  # 默认读取 tsn_6sw_4host.json

# 终端 2/3：查看日志
tail -f /tmp/s1-simple-switch-grpc.log.txt
tail -f /tmp/s2-simple-switch-grpc.log.txt

# 终端 4：运行控制器
export P4_TUTORIALS=/home/aaa/Workspace/P4/tutorials
~/tsn-lab/python-controller/controller_from_json.py
```
