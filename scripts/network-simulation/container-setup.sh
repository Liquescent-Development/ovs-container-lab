#!/usr/bin/env bash

# Container Setup for OVS Testing
# Creates test containers and connects them to OVS for network simulation testing

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OVS_SCRIPT="${SCRIPT_DIR}/../ovs-docker-connect.sh"
SIMULATION_NAME="Container Setup"

# Default test configuration
DEFAULT_CONTAINERS=("test-client" "test-server" "test-monitor")
DEFAULT_IPS=("172.18.0.10" "172.18.0.11" "172.18.0.12")
DEFAULT_IMAGE="alpine:latest"

usage() {
    echo "Usage: $0 {setup|teardown|status|test-connectivity|reset|logs|stop-traffic|start-traffic}"
    echo ""
    echo "Commands:"
    echo "  setup              - Create and connect test containers to OVS with traffic generation"
    echo "  teardown           - Remove test containers"  
    echo "  status             - Show current test container status"
    echo "  test-connectivity  - Test network connectivity between containers"
    echo "  reset              - Teardown and setup fresh containers"
    echo "  logs [container]   - Show traffic generation logs (all containers or specific one)"
    echo "  stop-traffic       - Stop traffic generation in all containers"
    echo "  start-traffic      - Start traffic generation in all containers"
    echo ""
    echo "Options (set as environment variables):"
    echo "  CONTAINER_COUNT=N  - Number of containers to create (default: 3)"
    echo "  IMAGE_NAME=image   - Docker image to use (default: alpine:latest)"
    echo "  BASE_IP=172.18.0   - IP base for container addressing (default: 172.18.0)"
    echo ""
    echo "Examples:"
    echo "  $0 setup                           # Create 3 default containers"
    echo "  CONTAINER_COUNT=5 $0 setup        # Create 5 containers"
    echo "  IMAGE_NAME=httpd:alpine $0 setup  # Use different image"
    exit 1
}

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] [$SIMULATION_NAME] $1"
}

check_docker_network() {
    if ! docker network ls | grep -q "monitoring-stack_default"; then
        log "ERROR: monitoring-stack_default network not found"
        log "Make sure the monitoring stack is running: docker compose up -d"
        exit 1
    fi
}

check_ovs_container() {
    if ! docker ps --filter name=ovs --format "{{.Names}}" | grep -q ovs; then
        log "ERROR: OVS container is not running"
        log "Start the monitoring stack first: docker compose up -d"
        exit 1
    fi
}

get_container_config() {
    CONTAINER_COUNT_CONFIG=${CONTAINER_COUNT:-3}
    IMAGE_NAME_CONFIG=${IMAGE_NAME:-$DEFAULT_IMAGE}
    BASE_IP_CONFIG=${BASE_IP:-"172.18.0"}
    
    # Generate container names and IPs
    CONTAINERS=()
    IPS=()
    
    for i in $(seq 1 $CONTAINER_COUNT_CONFIG); do
        CONTAINERS+=("test-container-$i")
        IPS+=("${BASE_IP_CONFIG}.$((9 + i))")  # Start from .10, .11, .12, etc.
    done
    
    log "Configuration: $CONTAINER_COUNT_CONFIG containers using image $IMAGE_NAME_CONFIG"
    log "IP range: ${IPS[0]} to ${IPS[$((${#IPS[@]} - 1))]}"
}

setup_containers() {
    log "Setting up test containers for OVS network simulation using Docker Compose"
    
    check_docker_network
    check_ovs_container
    
    # Remove any existing manual test containers
    teardown_containers >/dev/null 2>&1 || true
    
    # Navigate to monitoring stack directory for compose commands
    local compose_dir="$(dirname "$SCRIPT_DIR")"
    cd "$compose_dir"
    
    log "Starting test containers with compose profile 'testing'..."
    docker compose --profile testing up -d test-container-1 test-container-2 test-container-3
    
    # Wait for containers to start
    sleep 3
    
    # Connect each test container to OVS bridge
    local containers=("test-container-1" "test-container-2" "test-container-3")
    local ips=("172.18.0.10" "172.18.0.11" "172.18.0.12")
    
    for i in "${!containers[@]}"; do
        local container_name="${containers[$i]}"
        local container_ip="${ips[$i]}"
        
        log "Connecting $container_name to OVS bridge with IP $container_ip"
        "$OVS_SCRIPT" "$container_name" "$container_ip"
        
        log "Container $container_name connected to OVS bridge with traffic generation active"
    done
    
    log "All compose-managed containers connected to OVS bridge"
    
    # Wait a moment for network to stabilize
    sleep 2
    
    # Show final status
    show_status
}

teardown_containers() {
    log "Tearing down test containers"
    
    # Navigate to monitoring stack directory for compose commands
    local compose_dir="$(dirname "$SCRIPT_DIR")"
    cd "$compose_dir"
    
    # Stop compose-managed test containers
    log "Stopping compose-managed test containers..."
    docker compose --profile testing down test-container-1 test-container-2 test-container-3 >/dev/null 2>&1 || true
    
    # Also clean up any manually created test containers that might exist
    local manual_containers=$(docker ps -a --filter name="test-" --format "{{.Names}}" 2>/dev/null)
    
    if [ -n "$manual_containers" ]; then
        log "Cleaning up manual test containers: $(echo $manual_containers | tr '\n' ' ')"
        echo "$manual_containers" | while read container; do
            if [ -n "$container" ]; then
                docker rm -f "$container" >/dev/null 2>&1 || true
            fi
        done
    fi
    
    log "Test containers removed"
}

show_status() {
    log "Test container status:"
    
    check_ovs_container
    
    # Show running test containers
    local running_containers=$(docker ps --filter name="test-" --format "table {{.Names}}\t{{.Status}}\t{{.Image}}")
    
    if echo "$running_containers" | grep -q "test-"; then
        echo "  Running test containers:"
        echo "$running_containers" | grep -v "NAMES" | sed 's/^/    /'
        
        echo ""
        echo "  Docker network status:"
        docker network inspect monitoring-stack_default --format '{{len .Containers}} containers connected' | sed 's/^/    /'
        
    else
        echo "  No test containers currently running"
    fi
    
    # Show network connectivity summary
    echo ""
    echo "  Network summary:"
    local container_count=$(docker ps --filter name="test-" --format "{{.Names}}" | wc -l)
    echo "    Active test containers: $container_count"
    
    if [ $container_count -gt 0 ]; then
        echo "    OVS bridge: ovs-br0"
        echo "    Test containers routing traffic through OVS"
    fi
}

test_connectivity() {
    log "Testing network connectivity between containers"
    
    local test_containers=($(docker ps --filter name="test-" --format "{{.Names}}"))
    
    if [ ${#test_containers[@]} -lt 2 ]; then
        log "ERROR: Need at least 2 containers for connectivity testing"
        log "Run '$0 setup' first to create test containers"
        exit 1
    fi
    
    log "Found ${#test_containers[@]} containers for testing"
    
    # Get IP addresses of test containers from Docker
    local container_ips=()
    for container in "${test_containers[@]}"; do
        local ip=$(docker inspect "$container" --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')
        if [ -n "$ip" ]; then
            container_ips+=("$ip")
            log "Container $container has IP: $ip"
        fi
    done
    
    if [ ${#container_ips[@]} -lt 2 ]; then
        log "ERROR: Could not determine container IP addresses"
        exit 1
    fi
    
    # Test connectivity between first two containers
    local source_container="${test_containers[0]}"
    local target_ip="${container_ips[1]}"
    
    log "Testing connectivity: $source_container -> $target_ip"
    
    if docker exec "$source_container" ping -c 3 -W 2 "$target_ip" >/dev/null 2>&1; then
        log "SUCCESS: Connectivity test passed"
        return 0
    else
        log "FAILED: Connectivity test failed"
        
        # Show debugging info
        log "Debugging information:"
        log "Source container network config:"
        docker exec "$source_container" ip addr show | sed 's/^/    /'
        
        log "OVS bridge flows:"
        docker exec ovs ovs-ofctl dump-flows ovs-br0 | sed 's/^/    /'
        
        return 1
    fi
}

reset_containers() {
    log "Resetting test environment - removing and recreating containers"
    teardown_containers
    sleep 2
    setup_containers
}

show_logs() {
    local target_container="$1"
    
    if [ -n "$target_container" ]; then
        if docker ps --filter name="$target_container" --format "{{.Names}}" | grep -q "$target_container"; then
            log "Traffic logs from $target_container (last 20 lines):"
            docker logs --tail 20 "$target_container" | sed 's/^/    /'
        else
            log "Container $target_container not found or not running"
        fi
    else
        log "Traffic logs from all test containers (last 10 lines each):"
        local containers=$(docker ps --filter name="test-" --format "{{.Names}}")
        for container in $containers; do
            if [ -n "$container" ]; then
                echo "  === $container ==="
                docker logs --tail 10 "$container" | sed 's/^/    /'
                echo ""
            fi
        done
    fi
}

stop_traffic() {
    log "Stopping traffic generation in all test containers"
    local containers=$(docker ps --filter name="test-" --format "{{.Names}}")
    for container in $containers; do
        if [ -n "$container" ]; then
            docker exec "$container" pkill -f traffic-generator.sh >/dev/null 2>&1 || true
            log "Traffic stopped in $container"
        fi
    done
}

start_traffic() {
    log "Starting traffic generation in all test containers"
    local containers=$(docker ps --filter name="test-" --format "{{.Names}}")
    for container in $containers; do
        if [ -n "$container" ]; then
            # Check if traffic generator exists in container
            if docker exec "$container" test -f /traffic-generator.sh; then
                # Kill any existing traffic generators first
                docker exec "$container" pkill -f traffic-generator.sh >/dev/null 2>&1 || true
                # Start new traffic generator
                docker exec -d "$container" /traffic-generator.sh loop
                log "Traffic started in $container"
            else
                log "Traffic generator script not found in $container"
            fi
        fi
    done
}

case "$1" in
    setup)
        setup_containers
        ;;
    teardown)
        teardown_containers
        ;;
    status)
        show_status
        ;;
    test-connectivity)
        test_connectivity
        ;;
    reset)
        reset_containers
        ;;
    logs)
        show_logs "$2"
        ;;
    stop-traffic)
        stop_traffic
        ;;
    start-traffic)
        start_traffic
        ;;
    *)
        usage
        ;;
esac