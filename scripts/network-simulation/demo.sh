#!/usr/bin/env bash

# Demo Orchestrator for OVS Container Lab
# Combines traffic generation, Pumba chaos engineering, and underlay failures
# into a comprehensive demonstration of OVS behavior under stress

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"
LOG_DIR="/tmp/ovs-demo-logs"
DEMO_LOG="${LOG_DIR}/demo.log"

# Dashboard URLs
GRAFANA_BASE="http://localhost:3000/d"
DASHBOARDS=(
    "$GRAFANA_BASE/ovs-underlay-failure/ovs-underlay-failure-detection"
    "$GRAFANA_BASE/ovs-datapath-flow/ovs-datapath-flow-analysis"
    "$GRAFANA_BASE/ovs-coverage-drops/ovs-coverage-drops-analysis"
    "$GRAFANA_BASE/ovs-system-resources/ovs-system-resources-memory"
)

# Color codes for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

usage() {
    cat << EOF
${CYAN}OVS Container Lab - Demo Orchestrator${NC}

${YELLOW}Usage:${NC} $0 [command] [options]

${GREEN}Commands:${NC}
  full-demo           Run complete demonstration (30 minutes)
  quick-demo          Quick demonstration (10 minutes)
  traffic-only        Traffic generation stress test only
  chaos-only          Pumba chaos scenarios only
  underlay-only       Underlay failure scenarios only
  combined            Combined traffic + chaos (recommended)
  stop                Stop all demo components
  status              Show current demo status
  help                Show this help

${GREEN}Options:${NC}
  --verbose           Show detailed output
  --no-cleanup        Don't cleanup after demo
  --dashboard-only    Only show dashboard URLs, don't open browser

${PURPLE}Demo Scenarios:${NC}

  ${CYAN}1. Full Demo (30 min)${NC}
     - Phase 1: Baseline with normal traffic (2 min)
     - Phase 2: Traffic stress test (5 min)
     - Phase 3: Network chaos (packet loss, latency) (8 min)
     - Phase 4: Resource exhaustion (CPU, memory) (5 min)
     - Phase 5: Combined stress (traffic + chaos) (8 min)
     - Phase 6: Recovery and stabilization (2 min)

  ${CYAN}2. Quick Demo (10 min)${NC}
     - Baseline (1 min)
     - High traffic + 30% packet loss (3 min)
     - CPU stress + bandwidth limit (3 min)
     - Extreme scenario (50% loss + floods) (2 min)
     - Recovery (1 min)

  ${CYAN}3. Combined (Recommended)${NC}
     - Professional traffic generation (200k+ pps)
     - Simultaneous Pumba chaos scenarios
     - Real-world failure simulation

${YELLOW}Dashboard Monitoring:${NC}
  - Underlay Failure Detection: Shows packet loss, latency, errors
  - Datapath & Flow Analysis: Shows flow cache performance
  - Coverage & Drops: Shows various drop reasons
  - System Resources: Shows CPU, memory impact

${BLUE}Requirements:${NC}
  - Docker and Docker Compose installed
  - OVS monitoring stack running (docker compose up -d)
  - Grafana accessible at http://localhost:3000
  - At least 4GB RAM available

EOF
}

log() {
    local level="$1"
    shift
    local message="$@"
    local timestamp="$(date '+%Y-%m-%d %H:%M:%S')"
    
    case "$level" in
        ERROR)
            echo -e "${RED}[ERROR]${NC} $message"
            ;;
        SUCCESS)
            echo -e "${GREEN}[SUCCESS]${NC} $message"
            ;;
        INFO)
            echo -e "${BLUE}[INFO]${NC} $message"
            ;;
        WARN)
            echo -e "${YELLOW}[WARN]${NC} $message"
            ;;
        *)
            echo "$message"
            ;;
    esac
    
    echo "[$timestamp] [$level] $message" >> "$DEMO_LOG"
}

setup_logging() {
    mkdir -p "$LOG_DIR"
    echo "=== Demo Started at $(date) ===" > "$DEMO_LOG"
    log INFO "Log directory: $LOG_DIR"
}

check_requirements() {
    log INFO "Checking requirements..."
    
    # Check Docker
    if ! command -v docker &> /dev/null; then
        log ERROR "Docker is not installed"
        exit 1
    fi
    
    # Check OVS container
    if ! docker ps --filter name=ovs --format "{{.Names}}" | grep -q ovs; then
        log ERROR "OVS container is not running"
        log INFO "Start with: docker compose up -d"
        exit 1
    fi
    
    # Check Grafana
    if ! curl -s http://localhost:3000 > /dev/null 2>&1; then
        log WARN "Grafana not accessible at http://localhost:3000"
    fi
    
    # Check metrics endpoint
    if ! curl -s http://localhost:9475/metrics > /dev/null 2>&1; then
        log WARN "OVS metrics not accessible at http://localhost:9475/metrics"
    fi
    
    log SUCCESS "All requirements satisfied"
}

setup_test_environment() {
    log INFO "Setting up test environment..."
    
    # Setup test containers
    if ! docker ps --filter name="test-container" --format "{{.Names}}" | grep -q test-container; then
        log INFO "Starting test containers..."
        "$SCRIPT_DIR/container-setup.sh" setup
    fi
    
    # Build and setup professional traffic generator
    if ! docker ps -a --filter name=traffic-gen-pro --format "{{.Names}}" | grep -q traffic-gen-pro; then
        log INFO "Building professional traffic generator..."
        cd "$PROJECT_ROOT"
        
        if ! docker images | grep -q ovs-container-lab-traffic-generator; then
            docker compose build traffic-generator || {
                log ERROR "Failed to build traffic generator"
                exit 1
            }
        fi
        
        docker run -d --name traffic-gen-pro --network none --privileged ovs-container-lab-traffic-generator sleep 14400
        "$PROJECT_ROOT/scripts/ovs-docker-connect.sh" traffic-gen-pro 172.18.0.30
        log SUCCESS "Traffic generator ready"
    fi
    
    # Ensure Pumba is available
    if ! docker images | grep -q gaiaadm/pumba; then
        log INFO "Pulling Pumba chaos engineering tool..."
        docker pull gaiaadm/pumba
    fi
    
    log SUCCESS "Test environment ready"
}

start_traffic_generation() {
    local intensity="${1:-high}"
    
    log INFO "Starting traffic generation (intensity: $intensity)..."
    
    # Stop any existing traffic
    docker exec traffic-gen-pro pkill -f "hping3|python3" 2>/dev/null || true
    
    case "$intensity" in
        low)
            # Low intensity - ~10k pps
            docker exec -d traffic-gen-pro bash -c '
                for target in 172.18.0.10 172.18.0.11 172.18.0.12; do
                    hping3 -S -p 80 -i u10000 $target &  # 100 pps
                done
            '
            log SUCCESS "Low traffic started (~10k pps)"
            ;;
        medium)
            # Medium intensity - ~50k pps
            docker exec -d traffic-gen-pro bash -c '
                for target in 172.18.0.10 172.18.0.11 172.18.0.12; do
                    hping3 -S -p 80 -i u1000 $target &   # 1000 pps
                    hping3 --udp -p 53 -i u2000 $target & # 500 pps
                done
            '
            log SUCCESS "Medium traffic started (~50k pps)"
            ;;
        high)
            # High intensity - ~200k+ pps
            docker exec -d traffic-gen-pro bash -c '
                for target in 172.18.0.10 172.18.0.11 172.18.0.12; do
                    hping3 -S -p 80 --flood --rand-source $target &
                    hping3 -S -p 443 --flood $target &
                    hping3 --udp -p 53 --flood --rand-source $target &
                    hping3 --icmp --flood -d 1400 $target &
                done
            '
            docker exec -d traffic-gen-pro python3 /traffic-gen.py 172.18.0.10 172.18.0.11 172.18.0.12
            log SUCCESS "High traffic started (~200k+ pps)"
            ;;
        extreme)
            # Extreme intensity - Maximum possible
            docker exec -d traffic-gen-pro bash -c '
                for target in 172.18.0.10 172.18.0.11 172.18.0.12; do
                    for port in 80 443 8080 22 3306 5432; do
                        hping3 -S -p $port --flood --rand-source $target &
                    done
                    hping3 --udp --flood --rand-source $target &
                    hping3 --icmp --flood $target &
                done
            '
            docker exec -d traffic-gen-pro python3 /traffic-gen.py 172.18.0.10 172.18.0.11 172.18.0.12
            log SUCCESS "Extreme traffic started (maximum pps)"
            ;;
    esac
}

run_chaos_scenario() {
    local scenario="$1"
    local duration="${2:-60}"
    local target="${3:-ovs}"
    
    log INFO "Running chaos scenario: $scenario for ${duration}s on $target"
    
    case "$scenario" in
        packet-loss-*)
            local loss="${scenario#packet-loss-}"
            docker run -d --rm \
                --name "chaos-loss-$$" \
                -v /var/run/docker.sock:/var/run/docker.sock \
                gaiaadm/pumba netem \
                --duration "${duration}s" \
                loss --percent "$loss" \
                "$target"
            log SUCCESS "Packet loss ${loss}% started"
            ;;
        latency-*)
            local delay="${scenario#latency-}"
            docker run -d --rm \
                --name "chaos-latency-$$" \
                -v /var/run/docker.sock:/var/run/docker.sock \
                gaiaadm/pumba netem \
                --duration "${duration}s" \
                delay --time "${delay}" \
                "$target"
            log SUCCESS "Latency ${delay}ms started"
            ;;
        bandwidth-*)
            local rate="${scenario#bandwidth-}"
            docker run -d --rm \
                --name "chaos-bandwidth-$$" \
                -v /var/run/docker.sock:/var/run/docker.sock \
                gaiaadm/pumba netem \
                --duration "${duration}s" \
                rate --rate "${rate}kbps" \
                "$target"
            log SUCCESS "Bandwidth limited to ${rate}kbps"
            ;;
        cpu-stress-*)
            local cores="${scenario#cpu-stress-}"
            docker run -d --rm \
                --name "chaos-cpu-$$" \
                -v /var/run/docker.sock:/var/run/docker.sock \
                gaiaadm/pumba stress \
                --duration "${duration}s" \
                --stress-cpu "$cores" \
                "$target"
            log SUCCESS "CPU stress with $cores cores started"
            ;;
    esac
}

monitor_metrics() {
    local duration="${1:-10}"
    
    log INFO "Monitoring metrics for ${duration}s..."
    
    for i in $(seq 1 $duration); do
        # Get OVS flow stats
        local packets=$(docker exec ovs ovs-ofctl -O OpenFlow13 dump-flows ovs-br0 2>/dev/null | \
                       grep -o 'n_packets=[0-9]*' | cut -d= -f2 || echo "0")
        
        # Get drop stats from metrics
        local drops=$(curl -s http://localhost:9475/metrics 2>/dev/null | \
                     grep 'ovs_interface_rx_dropped' | \
                     awk '{sum+=$2} END {print sum}' || echo "0")
        
        log INFO "Packets: $packets, Drops: $drops"
        sleep 1
    done
}

run_full_demo() {
    log INFO "Starting FULL DEMO (30 minutes)"
    log INFO "Open dashboards:"
    for dashboard in "${DASHBOARDS[@]}"; do
        echo "  - $dashboard"
    done
    echo ""
    
    setup_test_environment
    
    # Phase 1: Baseline (2 min)
    log INFO "Phase 1: Establishing baseline with normal traffic"
    start_traffic_generation low
    monitor_metrics 120
    
    # Phase 2: Traffic stress test (5 min)
    log INFO "Phase 2: Traffic stress test"
    start_traffic_generation high
    monitor_metrics 300
    
    # Phase 3: Network chaos (8 min)
    log INFO "Phase 3: Network chaos scenarios"
    run_chaos_scenario "packet-loss-30" 120
    monitor_metrics 120
    run_chaos_scenario "latency-100" 120
    monitor_metrics 120
    run_chaos_scenario "bandwidth-1000" 120
    monitor_metrics 120
    run_chaos_scenario "packet-loss-50" 120
    monitor_metrics 120
    
    # Phase 4: Resource exhaustion (5 min)
    log INFO "Phase 4: Resource exhaustion"
    run_chaos_scenario "cpu-stress-8" 150
    monitor_metrics 150
    run_chaos_scenario "cpu-stress-16" 150
    monitor_metrics 150
    
    # Phase 5: Combined stress (8 min)
    log INFO "Phase 5: Combined stress (traffic + chaos)"
    start_traffic_generation extreme
    run_chaos_scenario "packet-loss-30" 240
    run_chaos_scenario "cpu-stress-4" 240
    monitor_metrics 240
    run_chaos_scenario "bandwidth-500" 240
    monitor_metrics 240
    
    # Phase 6: Recovery (2 min)
    log INFO "Phase 6: Recovery and stabilization"
    docker kill $(docker ps -q --filter "name=chaos-") 2>/dev/null || true
    docker exec traffic-gen-pro pkill -f "hping3|python3" 2>/dev/null || true
    start_traffic_generation low
    monitor_metrics 120
    
    log SUCCESS "Full demo completed!"
}

run_quick_demo() {
    log INFO "Starting QUICK DEMO (10 minutes)"
    
    setup_test_environment
    
    # Baseline (1 min)
    log INFO "Establishing baseline"
    start_traffic_generation medium
    monitor_metrics 60
    
    # High traffic + packet loss (3 min)
    log INFO "High traffic + 30% packet loss"
    start_traffic_generation high
    run_chaos_scenario "packet-loss-30" 180
    monitor_metrics 180
    
    # CPU stress + bandwidth limit (3 min)
    log INFO "CPU stress + bandwidth limit"
    run_chaos_scenario "cpu-stress-8" 180
    run_chaos_scenario "bandwidth-1000" 180
    monitor_metrics 180
    
    # Extreme scenario (2 min)
    log INFO "Extreme scenario"
    start_traffic_generation extreme
    run_chaos_scenario "packet-loss-50" 120
    monitor_metrics 120
    
    # Recovery (1 min)
    log INFO "Recovery"
    docker kill $(docker ps -q --filter "name=chaos-") 2>/dev/null || true
    docker exec traffic-gen-pro pkill -f "hping3|python3" 2>/dev/null || true
    start_traffic_generation low
    monitor_metrics 60
    
    log SUCCESS "Quick demo completed!"
}

run_combined_demo() {
    log INFO "Starting COMBINED DEMO (traffic + chaos)"
    
    setup_test_environment
    
    # Start high traffic
    start_traffic_generation high
    
    # Run multiple chaos scenarios simultaneously
    log INFO "Running combined chaos scenarios..."
    run_chaos_scenario "packet-loss-20" 300
    run_chaos_scenario "latency-50" 300
    run_chaos_scenario "cpu-stress-4" 300
    
    # Monitor for 5 minutes
    monitor_metrics 300
    
    log SUCCESS "Combined demo completed!"
}

stop_all() {
    log INFO "Stopping all demo components..."
    
    # Stop traffic generation
    docker exec traffic-gen-pro pkill -f "hping3|python3" 2>/dev/null || true
    
    # Stop all chaos containers
    docker kill $(docker ps -q --filter "name=chaos-") 2>/dev/null || true
    docker kill $(docker ps -q --filter "name=demo-pumba-") 2>/dev/null || true
    
    # Stop traffic generator containers
    docker stop traffic-gen-pro 2>/dev/null || true
    docker rm traffic-gen-pro 2>/dev/null || true
    
    log SUCCESS "All demo components stopped"
}

show_status() {
    echo -e "${CYAN}=== OVS Demo Status ===${NC}"
    echo ""
    
    # Check OVS
    if docker ps --filter name=ovs --format "{{.Names}}" | grep -q ovs; then
        echo -e "${GREEN}✓${NC} OVS container running"
    else
        echo -e "${RED}✗${NC} OVS container not running"
    fi
    
    # Check traffic generator
    if docker ps --filter name=traffic-gen-pro --format "{{.Names}}" | grep -q traffic-gen-pro; then
        echo -e "${GREEN}✓${NC} Traffic generator running"
        local procs=$(docker exec traffic-gen-pro ps aux | grep -E "hping3|python3" | wc -l)
        echo "  Active processes: $procs"
    else
        echo -e "${RED}✗${NC} Traffic generator not running"
    fi
    
    # Check chaos containers
    local chaos_count=$(docker ps --filter "name=chaos-" --format "{{.Names}}" | wc -l)
    if [ "$chaos_count" -gt 0 ]; then
        echo -e "${GREEN}✓${NC} Chaos scenarios active: $chaos_count"
        docker ps --filter "name=chaos-" --format "table {{.Names}}\t{{.Status}}"
    else
        echo -e "${YELLOW}○${NC} No chaos scenarios active"
    fi
    
    # Check metrics
    echo ""
    echo -e "${CYAN}Current Metrics:${NC}"
    local packets=$(docker exec ovs ovs-ofctl -O OpenFlow13 dump-flows ovs-br0 2>/dev/null | \
                   grep -o 'n_packets=[0-9]*' | cut -d= -f2 || echo "0")
    echo "  Total packets: $packets"
    
    # Calculate packet rate
    sleep 2
    local packets2=$(docker exec ovs ovs-ofctl -O OpenFlow13 dump-flows ovs-br0 2>/dev/null | \
                    grep -o 'n_packets=[0-9]*' | cut -d= -f2 || echo "0")
    local rate=$(( (packets2 - packets) / 2 ))
    echo "  Packet rate: ~${rate} pps"
    
    echo ""
    echo -e "${CYAN}Dashboards:${NC}"
    for dashboard in "${DASHBOARDS[@]}"; do
        echo "  $dashboard"
    done
}

# Main execution
setup_logging

case "${1:-help}" in
    full-demo)
        check_requirements
        run_full_demo
        ;;
    quick-demo)
        check_requirements
        run_quick_demo
        ;;
    traffic-only)
        check_requirements
        setup_test_environment
        start_traffic_generation "${2:-high}"
        log INFO "Traffic generation started. Press Ctrl+C to stop"
        trap stop_all INT
        while true; do sleep 1; done
        ;;
    chaos-only)
        check_requirements
        setup_test_environment
        run_chaos_scenario "${2:-packet-loss-30}" "${3:-300}"
        ;;
    underlay-only)
        check_requirements
        "$SCRIPT_DIR/underlay-failure-demo.sh" demo
        ;;
    combined)
        check_requirements
        run_combined_demo
        ;;
    stop)
        stop_all
        ;;
    status)
        show_status
        ;;
    help|*)
        usage
        ;;
esac