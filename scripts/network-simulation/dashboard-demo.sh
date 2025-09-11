#!/usr/bin/env bash

# Dashboard Demo Script
# Demonstrates underlay failure detection using orchestrated Pumba scenarios
# Optimized to showcase the OVS Underlay Failure Detection dashboard

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/tmp/dashboard-demo.log"
GRAFANA_URL="http://localhost:3000/d/ovs-underlay-failure/ovs-underlay-failure-detection"
METRICS_URL="http://localhost:9475/metrics"

# Demo scenarios optimized for maximum dashboard impact - AGGRESSIVE TESTING
# Format: "type:parameter:duration:interface:description"
DEMO_SCENARIOS=(
    "baseline:0:45:all:Healthy baseline - establish normal metrics"
    "packet-loss-high:50:90:eth0:Severe packet loss - dramatic TX/RX imbalance"
    "corruption:10:60:ovs-br0:High corruption - physical layer degradation"
    "bandwidth-limit:100:75:eth0:Extreme bandwidth throttling - 100kbps vs 112Mbps traffic"
    "latency:500:60:ovs-br0:High latency - 500ms delays"
    "jitter:100:60:eth0:Network jitter - 100ms variance"
    "cpu-stress:8:90:all:CPU saturation - 8 core stress test"
    "packet-loss-medium:30:60:ovs-br0:Sustained packet loss - bridge stress"
    "bandwidth-limit:50:75:ovs-br0:Severe bandwidth limit - 50kbps crawl vs 112Mbps"
    "corruption:15:45:eth0:Extreme corruption - 15% packet damage"
    "recovery:0:30:all:Brief recovery - metrics stabilization"
    "packet-loss-high:60:90:eth0:Critical packet loss - near failure"
    "cpu-stress:16:60:all:Maximum CPU stress - 16 core overload"
    "bandwidth-limit:25:60:ovs-br0:Network crawl - 25kbps vs 112Mbps = massive bottleneck"
    "recovery:0:30:all:Final recovery - return to baseline"
)

usage() {
    echo "Usage: $0 {demo|quick-demo|custom|status|help}"
    echo ""
    echo "Commands:"
    echo "  demo                              - Full dashboard demonstration (20 minutes)"
    echo "  quick-demo                       - Abbreviated demo (8 minutes)"
    echo "  custom <scenario> [duration] [interface] - Run specific scenario manually"
    echo "  status                           - Show current system status"
    echo "  help                             - Show this help"
    echo ""
    echo "Custom scenarios:"
    echo "  packet-loss-<pct>   - Packet loss (10, 25, 40, 60, 80%)"
    echo "  corruption-<pct>    - Packet corruption (5, 10, 15, 20%)"
    echo "  bandwidth-<rate>    - Bandwidth limit (25kbps, 50kbps, 100kbps, 200kbps, 500kbps) vs 112Mbps traffic"
    echo "  latency-<ms>        - Network latency (100, 300, 500, 1000ms)"
    echo "  jitter-<ms>         - Network jitter (25, 50, 100, 200ms)"
    echo "  cpu-stress-<cores>  - CPU exhaustion (2, 4, 8, 16, 32 cores)"
    echo ""
    echo "Target interfaces:"
    echo "  eth0                - External connectivity (default interface)"
    echo "  ovs-br0             - OVS bridge interface"
    echo "  all                 - Container default interface (no targeting)"
    echo ""
    echo "Examples:"
    echo "  $0 demo                                    # Full demonstration"
    echo "  $0 quick-demo                             # 8-minute version"
    echo "  $0 custom packet-loss-30                  # 30% packet loss on default interface"
    echo "  $0 custom packet-loss-30 120 ovs-br0     # 30% loss on bridge for 2 minutes"
    echo "  $0 custom bandwidth-100 180 eth0         # 100kbps limit on external interface"
    echo "  $0 custom corruption-5 90 ovs-br0        # 5% corruption on bridge for 90s"
    echo "  $0 custom cpu-stress-4 120               # 4-core CPU stress for 2 minutes"
    exit 1
}

log() {
    local message="[$(date '+%Y-%m-%d %H:%M:%S')] [DEMO] $1"
    echo "$message"
    echo "$message" >> "$LOG_FILE"
}

check_dependencies() {
    log "Checking demo prerequisites..."

    # Check if OVS container is running
    if ! docker ps --filter name=ovs --format "{{.Names}}" | grep -q ovs; then
        log "ERROR: OVS container is not running"
        log "Start the monitoring stack: docker compose up -d"
        exit 1
    fi

    # Check if test containers exist
    local test_container_count=$(docker ps --filter name="test-" --format "{{.Names}}" | wc -l)
    if [ $test_container_count -lt 2 ]; then
        log "Setting up test containers for demo..."
        "$SCRIPT_DIR/container-setup.sh" setup
    else
        log "Found $test_container_count test containers"
    fi

    # Check if metrics are accessible
    if ! curl -s "$METRICS_URL" > /dev/null; then
        log "ERROR: OVS metrics not accessible at $METRICS_URL"
        exit 1
    fi

    log "All prerequisites satisfied"
}

get_baseline_metrics() {
    local tx_packets=$(curl -s "$METRICS_URL" | grep "ovs_interface_tx_packets" | awk '{sum += $2} END {print sum}')
    local rx_packets=$(curl -s "$METRICS_URL" | grep "ovs_interface_rx_packets" | awk '{sum += $2} END {print sum}')
    local ratio="N/A"

    if [ "$rx_packets" -gt 0 ]; then
        ratio=$(echo "scale=1; $tx_packets / $rx_packets" | bc -l 2>/dev/null || echo "N/A")
    fi

    log "Current metrics: TX=$tx_packets, RX=$rx_packets, Ratio=$ratio"
}

generate_high_volume_traffic() {
    log "Generating high-volume traffic using dedicated nping containers..."

    # Navigate to monitoring stack directory for compose commands
    local compose_dir="$(dirname "$(dirname "$SCRIPT_DIR")")"
    cd "$compose_dir"
    
    # Start dedicated nping traffic generator containers
    log "Starting nping traffic generators with profile 'traffic'..."
    docker compose --profile traffic up -d traffic-gen-tcp traffic-gen-udp traffic-gen-icmp
    
    # Wait for containers to start
    sleep 2
    
    # Connect nping containers to OVS bridge for internal-only traffic
    log "Connecting nping containers to OVS bridge..."
    "${compose_dir}/scripts/ovs-docker-connect.sh" traffic-gen-tcp 172.18.0.20
    "${compose_dir}/scripts/ovs-docker-connect.sh" traffic-gen-udp 172.18.0.21  
    "${compose_dir}/scripts/ovs-docker-connect.sh" traffic-gen-icmp 172.18.0.22
    
    log "✓ MASSIVE traffic generators started (5000 TCP, 3000 UDP, 2000 ICMP pps = 10,000 pps total) - OVS internal only"
    log "✓ Traffic payload: 1400 bytes per packet = ~112 Mbps theoretical maximum"
}

run_pumba_scenario() {
    local scenario_type="$1"
    local parameter="$2"
    local duration="$3"
    local target_interface="$4"
    local description="$5"

    log "=== SCENARIO: $description ==="

    if [ "$scenario_type" = "baseline" ] || [ "$scenario_type" = "recovery" ]; then
        log "Monitoring baseline for ${duration}s..."
        # Generate background traffic during baseline/recovery for better metrics
        generate_high_volume_traffic
        for i in $(seq 1 $((duration / 15))); do
            get_baseline_metrics
            sleep 15
        done
        return 0
    fi

    # Map scenario types to Pumba commands
    local pumba_cmd=""
    local interface_param=""
    local pumba_action="netem"
    local extra_params=""

    case "$scenario_type" in
        "packet-loss-high"|"packet-loss-medium")
            pumba_cmd="loss --percent $parameter"
            ;;
        "corruption")
            pumba_cmd="corrupt --percent $parameter"
            ;;
        "bandwidth-limit")
            pumba_cmd="rate --rate ${parameter}kbps"
            ;;
        "latency")
            pumba_cmd="delay --time $parameter"
            ;;
        "jitter")
            pumba_cmd="delay --time 50 --jitter $parameter"
            ;;
        "cpu-stress")
            pumba_action="stress"
            pumba_cmd="--stressors '--cpu $parameter --timeout ${duration}s'"
            log "CPU stress: $parameter cores for ${duration}s"
            ;;
        *)
            log "ERROR: Unknown scenario type: $scenario_type"
            return 1
            ;;
    esac

    # Add interface targeting if specified (only for netem scenarios)
    if [ "$pumba_action" = "netem" ]; then
        if [ "$target_interface" != "all" ] && [ "$target_interface" != "default" ]; then
            interface_param="--interface $target_interface"
            log "Targeting interface: $target_interface"
        else
            log "Targeting container default interface"
        fi
        extra_params="--tc-image ghcr.io/alexei-led/pumba-alpine-nettools:latest"
    fi

    log "Starting Pumba: $pumba_action $pumba_cmd $interface_param for ${duration}s"
    log "Monitor dashboard: $GRAFANA_URL"

    # Get baseline before chaos
    get_baseline_metrics

    # Generate high-volume traffic during chaos for dramatic dashboard impact
    generate_high_volume_traffic

    # Run Pumba in background
    if [ "$pumba_action" = "stress" ]; then
        docker run --rm \
            --name "demo-pumba-$$" \
            -v /var/run/docker.sock:/var/run/docker.sock \
            gaiaadm/pumba \
            stress \
            --duration ${duration}s \
            $pumba_cmd \
            "ovs" &
    else
        docker run --rm \
            --name "demo-pumba-$$" \
            -v /var/run/docker.sock:/var/run/docker.sock \
            gaiaadm/pumba \
            netem \
            $extra_params \
            --duration ${duration}s \
            $interface_param \
            $pumba_cmd \
            "ovs" &
    fi

    local pumba_pid=$!

    # Monitor metrics during chaos
    local elapsed=0
    while [ $elapsed -lt $duration ]; do
        sleep 15
        elapsed=$((elapsed + 15))
        get_baseline_metrics

        # Check if Pumba is still running
        if ! kill -0 $pumba_pid 2>/dev/null; then
            log "Pumba completed early"
            break
        fi
    done

    # Ensure Pumba is stopped
    if kill -0 $pumba_pid 2>/dev/null; then
        log "Stopping Pumba..."
        kill $pumba_pid 2>/dev/null || true
        wait $pumba_pid 2>/dev/null || true
    fi

    log "Scenario completed: $description"
}

run_full_demo() {
    log "Starting AGGRESSIVE dashboard demonstration"
    log "Total duration: ~18 minutes"
    log "Dashboard URL: $GRAFANA_URL"
    log ""
    log "🚀 AGGRESSIVE DEMO FLOW:"
    log "  1. Baseline (45s) → 50% packet loss (1.5m) → 10% corruption (1m)"
    log "  2. Extreme throttling 100kbps vs 112Mbps (1.25m) → 500ms latency (1m)"
    log "  3. Network jitter 100ms (1m) → CPU saturation 8 cores (1.5m)"
    log "  4. Sustained packet loss 30% (1m) → Severe throttling 50kbps vs 112Mbps (1.25m)"
    log "  5. Extreme corruption 15% (45s) → Brief recovery (30s)"
    log "  6. Critical 60% packet loss (1.5m) → MAX CPU 16 cores (1m)"
    log "  7. Network crawl 25kbps vs 112Mbps = 4480x bottleneck (1m) → Final recovery (30s)"
    log ""
    log "🔥 FEATURES: 112 Mbps traffic vs kbps limits = MASSIVE visible bottlenecks"
    log ""

    check_dependencies

    # Initialize log
    echo "=== Dashboard Demo Started at $(date) ===" >> "$LOG_FILE"

    for scenario in "${DEMO_SCENARIOS[@]}"; do
        IFS=':' read -r type param duration interface desc <<< "$scenario"
        run_pumba_scenario "$type" "$param" "$duration" "$interface" "$desc"
        echo ""
    done

    log "🎉 Full demonstration completed!"
    log "Check dashboard: $GRAFANA_URL"
    log "Check log file: $LOG_FILE"
}

run_quick_demo() {
    log "Starting INTENSE quick demonstration"
    log "Total duration: ~6 minutes"
    log "Dashboard URL: $GRAFANA_URL"

    check_dependencies

    local quick_scenarios=(
        "baseline:0:30:all:Quick baseline"
        "packet-loss-high:60:90:eth0:Extreme packet loss - 60% drops"
        "cpu-stress:8:75:all:Heavy CPU saturation - 8 cores"
        "bandwidth-limit:75:60:ovs-br0:Severe bandwidth throttling - 75kbps vs 112Mbps"
        "corruption:12:60:eth0:High corruption - 12% packet damage"
        "packet-loss-medium:35:45:ovs-br0:Sustained bridge stress"
        "recovery:0:20:all:Brief recovery"
    )

    for scenario in "${quick_scenarios[@]}"; do
        IFS=':' read -r type param duration interface desc <<< "$scenario"
        run_pumba_scenario "$type" "$param" "$duration" "$interface" "$desc"
    done

    log "🎉 Quick demonstration completed!"
}

run_custom_scenario() {
    local scenario="$1"
    local duration="${2:-180}"
    local interface="${3:-all}"

    check_dependencies

    case "$scenario" in
        packet-loss-*)
            local pct=$(echo "$scenario" | cut -d'-' -f3)
            run_pumba_scenario "packet-loss-high" "$pct" "$duration" "$interface" "Custom packet loss ${pct}% on $interface"
            ;;
        corruption-*)
            local pct=$(echo "$scenario" | cut -d'-' -f2)
            run_pumba_scenario "corruption" "$pct" "$duration" "$interface" "Custom corruption ${pct}% on $interface"
            ;;
        bandwidth-*)
            local rate=$(echo "$scenario" | cut -d'-' -f2)
            run_pumba_scenario "bandwidth-limit" "${rate%kbps}" "$duration" "$interface" "Custom bandwidth limit $rate on $interface"
            ;;
        latency-*)
            local ms=$(echo "$scenario" | cut -d'-' -f2)
            run_pumba_scenario "latency" "${ms%ms}" "$duration" "$interface" "Custom latency ${ms} on $interface"
            ;;
        jitter-*)
            local ms=$(echo "$scenario" | cut -d'-' -f2)
            run_pumba_scenario "jitter" "${ms%ms}" "$duration" "$interface" "Custom jitter ${ms} on $interface"
            ;;
        cpu-stress-*)
            local cores=$(echo "$scenario" | cut -d'-' -f3)
            run_pumba_scenario "cpu-stress" "$cores" "$duration" "all" "Custom CPU stress ${cores} cores"
            ;;
        *)
            log "ERROR: Unknown custom scenario: $scenario"
            usage
            ;;
    esac
}

show_status() {
    log "Dashboard demo system status:"

    check_dependencies

    echo ""
    echo "  📊 Dashboard URL: $GRAFANA_URL"
    echo "  📈 Metrics URL: $METRICS_URL"
    echo ""

    # Show current metrics
    get_baseline_metrics

    echo ""
    echo "  🐳 Test containers:"
    docker ps --filter name="test-" --format "    {{.Names}}: {{.Status}}"

    echo ""
    echo "  📋 Recent demo activity:"
    if [ -f "$LOG_FILE" ]; then
        tail -5 "$LOG_FILE" | sed 's/^/    /'
    else
        echo "    No demo log found"
    fi
}

# Initialize log file
mkdir -p "$(dirname "$LOG_FILE")"

case "${1:-help}" in
    "demo")
        run_full_demo
        ;;
    "quick-demo")
        run_quick_demo
        ;;
    "custom")
        if [ -z "$2" ]; then
            log "ERROR: Custom scenario required"
            usage
        fi
        run_custom_scenario "$2" "$3" "$4"
        ;;
    "status")
        show_status
        ;;
    "help")
        usage
        ;;
    *)
        log "ERROR: Unknown command: $1"
        usage
        ;;
esac