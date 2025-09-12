#!/usr/bin/env bash

# OVS Underlay Failure Simulation Script
# Demonstrates how underlay network issues and OVS performance problems manifest in metrics
# Shows the impact of infrastructure problems on the virtual switch itself

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_FILE="/tmp/underlay-failure-demo.log"
GRAFANA_BASE="http://localhost:3000/d"
METRICS_URL="http://localhost:9475/metrics"

# Dashboard URLs for monitoring different aspects
DASHBOARDS=(
    "$GRAFANA_BASE/ovs-underlay-failure/ovs-underlay-failure-detection"
    "$GRAFANA_BASE/ovs-datapath-flow/ovs-datapath-flow-analysis"
    "$GRAFANA_BASE/ovs-coverage-drops/ovs-coverage-drops-analysis"
    "$GRAFANA_BASE/ovs-system-resources/ovs-system-resources-memory"
)

# Underlay failure scenarios that affect OVS itself
# Format: "target:type:parameter:duration:interface:description"
UNDERLAY_SCENARIOS=(
    # Phase 1: Baseline with high traffic
    "baseline:baseline:0:60:all:Establish baseline with high traffic load"
    
    # Phase 2: OVS Infrastructure Stress
    "ovs:packet-loss:10:90:eth0:Underlay packet loss affecting OVS control plane"
    "ovs:latency:50:60:eth0:Underlay latency impacting OVS operations"
    "ovs:cpu-stress:4:90:all:OVS CPU stress - simulating overloaded host"
    
    # Phase 3: Combined OVS and Container Issues
    "both:packet-loss:25:90:eth0:Underlay loss affecting both OVS and containers"
    "ovs:bandwidth:500:75:eth0:Underlay bandwidth constraint on OVS"
    "ovs:corruption:5:60:eth0:Underlay bit errors affecting OVS packets"
    
    # Phase 4: Severe OVS Degradation
    "ovs:memory-stress:512:60:all:OVS memory pressure simulation"
    "ovs:packet-loss:40:90:eth0:Severe underlay loss - OVS struggling"
    "ovs:jitter:100:60:eth0:Underlay jitter affecting OVS timing"
    
    # Phase 5: Cascading Failures
    "both:cpu-stress:8:90:all:System-wide CPU exhaustion"
    "ovs:bandwidth:100:75:eth0:Critical bandwidth starvation"
    "both:packet-loss:50:60:eth0:Near-total underlay failure"
    
    # Recovery
    "baseline:recovery:0:45:all:Recovery phase - observe metric normalization"
)

usage() {
    echo "Usage: $0 {demo|ovs-stress|underlay-failure|custom|status|help}"
    echo ""
    echo "Commands:"
    echo "  demo                    - Full underlay failure demonstration"
    echo "  ovs-stress              - Focus on OVS performance degradation"
    echo "  underlay-failure        - Simulate specific underlay network issues"
    echo "  custom <args>           - Run custom scenario"
    echo "  status                  - Show current system status"
    echo ""
    echo "This demo shows how underlay issues affect OVS itself, not just container traffic."
    echo "Monitor all dashboards to see the full impact:"
    echo "  - OVS Underlay Failure Detection"
    echo "  - OVS Datapath & Flow Analysis"
    echo "  - OVS Coverage & Drop Analysis"
    echo "  - OVS System Resources & Memory"
    exit 1
}

log() {
    local message="[$(date '+%Y-%m-%d %H:%M:%S')] [UNDERLAY] $1"
    echo "$message"
    echo "$message" >> "$LOG_FILE"
}

check_ovs_health() {
    log "Checking OVS health metrics..."
    
    # Check OVS process CPU usage
    local ovs_pid=$(docker exec ovs pidof ovs-vswitchd 2>/dev/null || echo "0")
    if [ "$ovs_pid" != "0" ]; then
        local cpu_usage=$(docker exec ovs top -b -n 1 -p $ovs_pid | tail -1 | awk '{print $9}')
        log "OVS CPU usage: ${cpu_usage}%"
    fi
    
    # Check datapath performance
    local lookups_hit=$(curl -s "$METRICS_URL" | grep "ovs_dp_lookups_hit{" | awk '{print $2}')
    local lookups_missed=$(curl -s "$METRICS_URL" | grep "ovs_dp_lookups_missed{" | awk '{print $2}')
    local cache_hit_rate="0"
    if [ -n "$lookups_hit" ] && [ -n "$lookups_missed" ]; then
        local total=$((lookups_hit + lookups_missed))
        if [ $total -gt 0 ]; then
            cache_hit_rate=$(echo "scale=2; $lookups_hit * 100 / $total" | bc -l)
        fi
    fi
    log "Flow cache hit rate: ${cache_hit_rate}%"
    
    # Check for drops
    local drops=$(curl -s "$METRICS_URL" | grep "ovs_coverage_total{.*drop" | awk '{sum += $2} END {print sum}')
    log "Total drop events: ${drops:-0}"
    
    # Check memory usage
    local memory=$(curl -s "$METRICS_URL" | grep "ovs_memory_usage{component=\"vswitchd" | awk '{sum += $2} END {print sum}')
    log "OVS memory usage units: ${memory:-0}"
}

generate_stress_traffic() {
    local intensity="${1:-high}"
    log "Generating $intensity intensity traffic to stress OVS datapath..."
    
    # Use iperf3 for sustained high-bandwidth traffic if available
    if docker exec test-container-1 which iperf3 >/dev/null 2>&1; then
        log "Using iperf3 for high-bandwidth stress testing..."
        
        # Start iperf3 server on container 2
        docker exec -d test-container-2 iperf3 -s -D
        sleep 2
        
        # Start clients from other containers
        docker exec -d test-container-1 iperf3 -c 172.18.0.11 -t 0 -b 10M
        docker exec -d test-container-3 iperf3 -c 172.18.0.11 -t 0 -b 10M -R
        
        log "✓ iperf3 generating 20+ Mbps bidirectional traffic"
    else
        # Fallback to aggressive nping/ping flooding
        log "Using packet flooding for stress testing..."
        
        # Start aggressive traffic from all test containers
        for container in test-container-1 test-container-2 test-container-3; do
            # TCP SYN flood
            docker exec -d $container sh -c "while true; do nc -zv 172.18.0.10-15 80 443 8080 22 2>/dev/null; done"
            
            # UDP flood
            docker exec -d $container sh -c "while true; do echo 'test' | nc -u -w0 172.18.0.10-15 53 123 2>/dev/null; done"
            
            # ICMP flood
            docker exec -d $container sh -c "while true; do for i in 10 11 12; do ping -f -c 100 -s 1400 172.18.0.\$i 2>/dev/null & done; wait; done"
        done
        
        log "✓ Packet flooding started from all containers"
    fi
    
    # Also generate traffic that causes cache misses
    log "Generating diverse flows to stress flow cache..."
    for container in test-container-1 test-container-2 test-container-3; do
        docker exec -d $container sh -c "
            while true; do
                # Random ports to create many different flows
                for port in \$(shuf -i 1024-65535 -n 50); do
                    nc -zv -w1 172.18.0.\$((10 + RANDOM % 6)) \$port 2>/dev/null &
                done
                sleep 1
            done
        "
    done
    
    log "✓ Flow diversity traffic started - stressing OVS flow tables"
}

stress_ovs_infrastructure() {
    local stress_type="$1"
    local intensity="$2"
    local duration="$3"
    
    case "$stress_type" in
        "cpu")
            log "Applying CPU stress to OVS container ($intensity cores for ${duration}s)..."
            docker run --rm -d \
                --name "ovs-cpu-stress-$$" \
                --pid="container:ovs" \
                --network="container:ovs" \
                alpine sh -c "
                    apk add --no-cache stress-ng >/dev/null 2>&1
                    stress-ng --cpu $intensity --timeout ${duration}s --metrics-brief
                "
            ;;
            
        "memory")
            log "Applying memory pressure to OVS container (${intensity}MB for ${duration}s)..."
            docker run --rm -d \
                --name "ovs-mem-stress-$$" \
                --pid="container:ovs" \
                --network="container:ovs" \
                alpine sh -c "
                    apk add --no-cache stress-ng >/dev/null 2>&1
                    stress-ng --vm 2 --vm-bytes ${intensity}M --timeout ${duration}s --metrics-brief
                "
            ;;
            
        "io")
            log "Applying I/O stress to OVS container for ${duration}s..."
            docker run --rm -d \
                --name "ovs-io-stress-$$" \
                --pid="container:ovs" \
                --network="container:ovs" \
                alpine sh -c "
                    while true; do
                        dd if=/dev/zero of=/tmp/stress bs=1M count=100 2>/dev/null
                        sync
                        rm /tmp/stress
                    done
                " &
            sleep $duration
            docker stop "ovs-io-stress-$$" 2>/dev/null || true
            ;;
    esac
}

apply_underlay_failure() {
    local target="$1"      # ovs, containers, or both
    local failure_type="$2"
    local parameter="$3"
    local duration="$4"
    local interface="$5"
    local description="$6"
    
    log "=== UNDERLAY FAILURE: $description ==="
    log "Target: $target | Type: $failure_type | Parameter: $parameter | Duration: ${duration}s"
    
    # Start high traffic to make issues visible
    generate_stress_traffic high
    
    # Apply the failure scenario
    case "$failure_type" in
        "baseline"|"recovery")
            log "Monitoring phase - no failures applied"
            check_ovs_health
            sleep $duration
            ;;
            
        "packet-loss")
            if [ "$target" = "ovs" ] || [ "$target" = "both" ]; then
                log "Applying ${parameter}% packet loss to OVS underlay..."
                docker run --rm -d \
                    --name "pumba-ovs-loss-$$" \
                    -v /var/run/docker.sock:/var/run/docker.sock \
                    gaiaadm/pumba \
                    netem \
                    --duration ${duration}s \
                    --interface ${interface} \
                    loss --percent ${parameter} \
                    "^ovs$" &
            fi
            
            if [ "$target" = "containers" ] || [ "$target" = "both" ]; then
                log "Applying ${parameter}% packet loss to test containers..."
                docker run --rm -d \
                    --name "pumba-container-loss-$$" \
                    -v /var/run/docker.sock:/var/run/docker.sock \
                    gaiaadm/pumba \
                    netem \
                    --duration ${duration}s \
                    loss --percent ${parameter} \
                    "^test-container" &
            fi
            
            # Monitor during failure
            for i in $(seq 1 $((duration / 20))); do
                sleep 20
                check_ovs_health
            done
            ;;
            
        "latency")
            if [ "$target" = "ovs" ] || [ "$target" = "both" ]; then
                log "Applying ${parameter}ms latency to OVS underlay..."
                docker run --rm -d \
                    --name "pumba-ovs-latency-$$" \
                    -v /var/run/docker.sock:/var/run/docker.sock \
                    gaiaadm/pumba \
                    netem \
                    --duration ${duration}s \
                    --interface ${interface} \
                    delay --time ${parameter} \
                    "^ovs$" &
            fi
            
            sleep $duration
            ;;
            
        "bandwidth")
            if [ "$target" = "ovs" ] || [ "$target" = "both" ]; then
                log "Applying ${parameter}kbps bandwidth limit to OVS..."
                docker run --rm -d \
                    --name "pumba-ovs-bw-$$" \
                    -v /var/run/docker.sock:/var/run/docker.sock \
                    gaiaadm/pumba \
                    netem \
                    --duration ${duration}s \
                    --interface ${interface} \
                    rate --rate ${parameter}kbps \
                    "^ovs$" &
            fi
            
            sleep $duration
            ;;
            
        "corruption")
            if [ "$target" = "ovs" ] || [ "$target" = "both" ]; then
                log "Applying ${parameter}% packet corruption to OVS..."
                docker run --rm -d \
                    --name "pumba-ovs-corrupt-$$" \
                    -v /var/run/docker.sock:/var/run/docker.sock \
                    gaiaadm/pumba \
                    netem \
                    --duration ${duration}s \
                    --interface ${interface} \
                    corrupt --percent ${parameter} \
                    "^ovs$" &
            fi
            
            sleep $duration
            ;;
            
        "jitter")
            if [ "$target" = "ovs" ] || [ "$target" = "both" ]; then
                log "Applying ${parameter}ms jitter to OVS..."
                docker run --rm -d \
                    --name "pumba-ovs-jitter-$$" \
                    -v /var/run/docker.sock:/var/run/docker.sock \
                    gaiaadm/pumba \
                    netem \
                    --duration ${duration}s \
                    --interface ${interface} \
                    delay --time 10 --jitter ${parameter} \
                    "^ovs$" &
            fi
            
            sleep $duration
            ;;
            
        "cpu-stress")
            stress_ovs_infrastructure "cpu" "$parameter" "$duration"
            ;;
            
        "memory-stress")
            stress_ovs_infrastructure "memory" "$parameter" "$duration"
            ;;
            
        *)
            log "Unknown failure type: $failure_type"
            ;;
    esac
    
    # Clean up any remaining Pumba containers
    docker ps --filter "name=pumba-" --format "{{.Names}}" | xargs -r docker stop 2>/dev/null || true
    
    log "Scenario completed: $description"
    check_ovs_health
    echo ""
}

run_full_demo() {
    log "Starting OVS Underlay Failure Demonstration"
    log "This demo shows how infrastructure problems affect OVS itself"
    log ""
    log "📊 Monitor these dashboards:"
    for dashboard in "${DASHBOARDS[@]}"; do
        log "  - $dashboard"
    done
    log ""
    log "🎯 Focus areas:"
    log "  1. Flow cache hit rates dropping during stress"
    log "  2. Datapath lookup misses increasing"
    log "  3. Coverage events showing drops and errors"
    log "  4. OVS memory and CPU usage spikes"
    log "  5. Interface error counters incrementing"
    log ""
    
    # Check prerequisites
    log "Checking prerequisites..."
    if ! docker ps --filter name=ovs --format "{{.Names}}" | grep -q ovs; then
        log "ERROR: OVS container not running"
        exit 1
    fi
    
    # Setup test containers if needed
    local test_count=$(docker ps --filter name="test-container" --format "{{.Names}}" | wc -l)
    if [ $test_count -lt 3 ]; then
        log "Setting up test containers..."
        "$SCRIPT_DIR/container-setup.sh" setup
    fi
    
    # Run through all scenarios
    for scenario in "${UNDERLAY_SCENARIOS[@]}"; do
        IFS=':' read -r target type param duration interface desc <<< "$scenario"
        apply_underlay_failure "$target" "$type" "$param" "$duration" "$interface" "$desc"
        sleep 5  # Brief pause between scenarios
    done
    
    log "✅ Demonstration complete!"
    log "Review the dashboards to see how underlay issues manifested in OVS metrics"
}

run_ovs_stress_test() {
    log "Running focused OVS stress test"
    log "This specifically targets OVS performance degradation"
    
    # High intensity scenarios focused on OVS
    local stress_scenarios=(
        "ovs:cpu-stress:8:120:all:Heavy CPU load on OVS"
        "ovs:memory-stress:1024:90:all:Memory pressure on OVS"
        "ovs:packet-loss:30:90:eth0:Significant underlay packet loss"
        "ovs:bandwidth:200:120:eth0:Severe bandwidth constraint"
    )
    
    for scenario in "${stress_scenarios[@]}"; do
        IFS=':' read -r target type param duration interface desc <<< "$scenario"
        apply_underlay_failure "$target" "$type" "$param" "$duration" "$interface" "$desc"
        sleep 10
    done
    
    log "✅ OVS stress test complete!"
}

show_status() {
    log "System Status Check"
    echo ""
    
    check_ovs_health
    echo ""
    
    log "Test containers:"
    docker ps --filter name="test-container" --format "  {{.Names}}: {{.Status}}"
    echo ""
    
    log "Active chaos scenarios:"
    docker ps --filter name="pumba" --format "  {{.Names}}: {{.Command}}" || echo "  None"
    echo ""
    
    log "Recent OVS log entries:"
    docker exec ovs tail -5 /var/log/openvswitch/ovs-vswitchd.log | sed 's/^/  /'
}

# Main execution
case "${1:-help}" in
    "demo")
        run_full_demo
        ;;
    "ovs-stress")
        run_ovs_stress_test
        ;;
    "underlay-failure")
        # Quick underlay failure test
        apply_underlay_failure "ovs" "packet-loss" "25" "60" "eth0" "Quick underlay packet loss test"
        ;;
    "custom")
        shift
        apply_underlay_failure "$@"
        ;;
    "status")
        show_status
        ;;
    *)
        usage
        ;;
esac