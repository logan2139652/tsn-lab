#!/usr/bin/env bash
# run_test_simple.sh -- 极简全自动 TSN 测试 (v2: 含类型/P99/丢包率)
set -e

CONFIG="${1:-$HOME/tsn-lab/configs/tsn_6sw_4host.json}"
TRAFFIC_DURATION="${2:-10}"
TOPO_DURATION=120
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
RESULT_DIR="/tmp/tsn_test_${TIMESTAMP}"
mkdir -p "$RESULT_DIR"

GREEN='\033[0;32m'; RED='\033[0;31m'; BLUE='\033[0;34m'; NC='\033[0m'
ok()  { echo -e "${GREEN}[OK]${NC} $*"; }
fail(){ echo -e "${RED}[FAIL]${NC} $*"; }
step(){ echo -e "\n${BLUE}==> $*${NC}"; }

# Step 1: clean
step "Step 1/5: Clean old environment"
sudo mn -c 2>/dev/null || true
sudo pkill -9 simple_switch_grpc 2>/dev/null || true
sudo rm -f /tmp/s*-simple-switch-grpc.* /tmp/s*-stdout.log \
           /tmp/tsn_gcl_*.txt /tmp/tsn_phase_*.txt /tmp/tsn_recv_*.csv
sleep 1
ok "Environment cleaned"

# Step 2: start topology (background)
step "Step 2/5: Start topology (${TOPO_DURATION}s)"
sudo python3 ~/tsn-lab/python-controller/topo_from_json_bg.py \
    --config "$CONFIG" \
    --duration "$TOPO_DURATION" \
    > "$RESULT_DIR/topo.log" 2>&1 &
TOPO_PID=$!
ok "Topology PID: $TOPO_PID"
trap 'sudo kill $TOPO_PID 2>/dev/null; wait $TOPO_PID 2>/dev/null; sudo mn -c 2>/dev/null; sudo pkill -9 simple_switch_grpc 2>/dev/null' EXIT

# Wait for switches
step "Wait for switch gRPC ports..."
for pair in s1:50051 s2:50052 s3:50053 s4:50054 s5:50055 s6:50056; do
    name="${pair%%:*}"; port="${pair##*:}"
    for i in $(seq 1 60); do
        nc -z 127.0.0.1 "$port" 2>/dev/null && break
        sleep 1
    done
    ok "$name ready (:${port})"
done

# Wait for host netns
step "Wait for host netns..."
for host in h1 h2 h3 h4; do
    for i in $(seq 1 30); do
        sudo ip netns exec "$host" true 2>/dev/null && break
        sleep 1
    done
    ok "$host netns ready"
done
sleep 2

# Step 3: controller
step "Step 3/5: Program flows (controller)"
export P4_TUTORIALS=/home/aaa/Workspace/P4/tutorials
python3 ~/tsn-lab/python-controller/controller_from_json.py \
    --config "$CONFIG" \
    > "$RESULT_DIR/controller.log" 2>&1
ok "Controller done"
sleep 1

# Step 4: traffic
step "Step 4/5: Start receivers (h3, h4)"
sudo ip netns exec h3 python3 ~/tsn-lab/traffic/recv_from_json.py \
    --config "$CONFIG" --session h1_h3 \
    --duration $((TRAFFIC_DURATION + 10)) \
    --csv /tmp/tsn_recv_h1_h3.csv \
    > "$RESULT_DIR/recv_h3.log" 2>&1 &
RECV_H3=$!
ok "h3 recv PID=$RECV_H3"

sudo ip netns exec h4 python3 ~/tsn-lab/traffic/recv_from_json.py \
    --config "$CONFIG" --session h2_h4 \
    --duration $((TRAFFIC_DURATION + 10)) \
    --csv /tmp/tsn_recv_h2_h4.csv \
    > "$RESULT_DIR/recv_h4.log" 2>&1 &
RECV_H4=$!
ok "h4 recv PID=$RECV_H4"
sleep 2

step "Start senders (h1, h2)"
sudo ip netns exec h1 python3 ~/tsn-lab/traffic/send_from_json.py \
    --config "$CONFIG" --session h1_h3 \
    --duration "$TRAFFIC_DURATION" \
    > "$RESULT_DIR/send_h1.log" 2>&1 &
SEND_H1=$!
ok "h1 send PID=$SEND_H1"

sudo ip netns exec h2 python3 ~/tsn-lab/traffic/send_from_json.py \
    --config "$CONFIG" --session h2_h4 \
    --duration "$TRAFFIC_DURATION" \
    > "$RESULT_DIR/send_h2.log" 2>&1 &
SEND_H2=$!
ok "h2 send PID=$SEND_H2"

# Wait for traffic
step "Wait for traffic to complete..."
wait $SEND_H1 $SEND_H2 2>/dev/null || true
ok "Senders done"
sleep 2
wait $RECV_H3 $RECV_H4 2>/dev/null || true
ok "Receivers done"

for csv in /tmp/tsn_recv_*.csv; do
    [[ -f "$csv" ]] && cp "$csv" "$RESULT_DIR/"
done

# Step 5: analysis
step "Step 5/5: Delay Analysis"

echo ""
echo "SESSION    KIND    FID   COUNT    AVG(us)   P50(us)   P95(us)   P99(us)   MAX(us)   ANOMALY"
echo "-------------------------------------------------------------------------------------------"

for csv in "$RESULT_DIR"/tsn_recv_*.csv; do
    [[ -f "$csv" ]] || continue
    session=$(basename "$csv" | sed 's/tsn_recv_//;s/\.csv//')
    python3 << PYEOF
import csv, statistics, json, sys

csv_path = "$csv"
sess = "$session"
config_path = "$CONFIG"

# Load config to get expected counts
with open(config_path) as f:
    cfg = json.load(f)

# Determine src/dst MAC for this session
sessions_cfg = cfg.get("traffic", {}).get("sessions", {})
src_mac = None
dst_mac = None
if sess in sessions_cfg:
    src_host = sessions_cfg[sess]["sender"]["host"]
    dst_host = sessions_cfg[sess]["receiver"]["host"]
    src_mac = cfg["hosts"][src_host]["mac"]
    dst_mac = cfg["hosts"][dst_host]["mac"]

# Get expected packets from config
expected = {}
session_cfg = cfg.get("traffic", {}).get("sessions", {}).get(sess, {})
duration = session_cfg.get("duration", 10)
tsn_cfg = cfg.get("tsn", {})
slot_us = tsn_cfg.get("slot_us", 10000)
cycle_us = tsn_cfg.get("cycle_us", 80000)

# Calculate expected TSN packets per flow
for flow in session_cfg.get("flows", []):
    if flow.get("type") == "background":
        continue
    slots = flow.get("slots", [])
    fid = flow["fid"]
    # packets = duration * 1e6 / cycle_us * len(slots)
    packets = int(duration * 1e6 / cycle_us * len(slots))
    expected[fid] = packets

with open(csv_path) as f:
    reader = csv.DictReader(f)
    groups = {}
    for row in reader:
        key = (row['kind'], int(row['fid']))
        groups.setdefault(key, []).append(float(row['delay_us']))

# Compute hop count from JSON routes
hops = 0
routes = cfg.get("routes", {})
for sw_name, sw_routes in routes.items():
    for r in sw_routes:
        if r.get("src_mac", "") == src_mac and r.get("dst_mac", "") == dst_mac:
            hops += 1
            break
# threshold = (hops+2) * slot_us = (H+1)*slot where H=total hops
threshold_us = (hops + 2) * slot_us

for (kind, fid), delays in sorted(groups.items()):
    delays.sort()
    avg = statistics.mean(delays)
    p50 = delays[int((len(delays)-1)*0.50)]
    p95 = delays[int((len(delays)-1)*0.95)]
    p99 = delays[int((len(delays)-1)*0.99)]
    mx  = max(delays)
    
    # Count anomaly packets: delay > threshold
    anomaly = sum(1 for d in delays if d > threshold_us)
    anomaly_str = f"{anomaly}(>{threshold_us}us)"
    
    print(f"{sess:8s}  {kind:>6s}  {fid:>4d}  {len(delays):>6d}  "
          f"{avg:>8.0f}  {p50:>8.0f}  {p95:>8.0f}  {p99:>8.0f}  {mx:>8.0f}   {anomaly_str}")
PYEOF
done

# TSN header summary
step "TSN Header Summary"
python3 ~/tsn-lab/scripts/slot_stack_summary.py "$RESULT_DIR"
echo ""

# Switch logs
step "Switch Scheduling Stats"
echo "SW      ENQUEUE    DEQUEUE"
echo "--------------------------"
for sw in s1 s2 s3 s4 s5 s6; do
    log="/tmp/${sw}-simple-switch-grpc.log.txt"
    [[ -f "$log" ]] || log="/tmp/${sw}-simple-switch-grpc.log"
    if [[ -f "$log" ]]; then
        cp "$log" "$RESULT_DIR/"
        enq=$(grep -c 'TQF_ENQUEUE\|TCQF_ENQUEUE\|CSQF_ENQUEUE\|TSN_QUEUE.*enqueue' "$log" 2>/dev/null || echo 0)
        deq=$(grep -c 'TQF_DEQUEUE\|TCQF_DEQUEUE\|CSQF_DEQUEUE\|TSN_GCL.*dequeue\|CSQF dequeue' "$log" 2>/dev/null || echo 0)
        printf "%-6s  %8s  %8s\n" "$sw" "$enq" "$deq"
    else
        printf "%-6s  %8s  %8s\n" "$sw" "-" "-"
    fi
done

echo ""
echo "Results: $RESULT_DIR"
ok "Test complete"
