#!/bin/sh

# Traffic Generator Script for Test Containers
# Runs inside containers to generate meaningful network traffic

CONTAINER_NAME="${HOSTNAME}"
LOG_PREFIX="[${CONTAINER_NAME}]"

log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') ${LOG_PREFIX} $1"
}

# Install required tools
install_tools() {
    log "Installing network tools..."
    apk add --no-cache curl wget iputils bind-tools nmap-ncat >/dev/null 2>&1 || {
        log "Failed to install tools, trying without package manager"
        return 1
    }
    
    # Check if nping is available
    if command -v nping >/dev/null 2>&1; then
        log "✓ nping available for controlled traffic generation"
    else
        log "! nping not available, using basic tools only"
    fi
}

# Test external connectivity
test_external() {
    local random_index=$(( $(date +%s) % 3 ))
    local site=""
    case $random_index in
        0) site="google.com" ;;
        1) site="cloudflare.com" ;;
        2) site="github.com" ;;
    esac
    
    if curl -s --max-time 5 --connect-timeout 3 "https://${site}" >/dev/null 2>&1; then
        log "✓ External connectivity OK (${site})"
        return 0
    else
        log "✗ External connectivity FAILED (${site})"
        return 1
    fi
}

# Test DNS resolution
test_dns() {
    if nslookup google.com >/dev/null 2>&1; then
        log "✓ DNS resolution OK"
        return 0
    else
        log "✗ DNS resolution FAILED"
        return 1
    fi
}

# Ping other containers in the OVS network
ping_peers() {
    local base_ip="172.18.0"
    local my_ip=$(ip addr show | grep "${base_ip}" | head -1 | awk '{print $2}' | cut -d'/' -f1)
    local my_last_octet=$(echo $my_ip | cut -d'.' -f4)
    
    if [ -z "$my_ip" ]; then
        log "✗ Could not determine my IP address"
        return 1
    fi
    
    log "My IP: $my_ip"
    
    # Ping other likely container IPs
    local success=0
    for octet in 10 11 12 13 14 15; do
        if [ "$octet" != "$my_last_octet" ]; then
            local target_ip="${base_ip}.${octet}"
            if ping -c 1 -W 2 "$target_ip" >/dev/null 2>&1; then
                log "✓ Ping to ${target_ip} OK"
                success=1
            else
                log "✗ Ping to ${target_ip} FAILED"
            fi
        fi
    done
    
    return $((1 - success))
}

# Generate HTTP traffic between containers
http_test() {
    # Simple HTTP server simulation - try to connect to other containers on port 8080
    local base_ip="172.18.0"
    local tested=0
    local success=0
    
    for octet in 10 11 12 13 14 15; do
        local target_ip="${base_ip}.${octet}"
        if timeout 3 nc -z "$target_ip" 8080 2>/dev/null; then
            log "✓ HTTP connection to ${target_ip}:8080 OK"
            success=1
            tested=1
        elif [ $tested -eq 0 ]; then
            # Only log failures if we haven't found any successful connections
            log "✗ HTTP connection to ${target_ip}:8080 FAILED (service may not be running)"
        fi
    done
    
    return $((1 - success))
}

# Run bandwidth test
bandwidth_test() {
    # Simple bandwidth test using dd and timing
    local test_size="1M"
    local start_time=$(date +%s)
    
    # Create and transfer a test file to measure throughput
    if dd if=/dev/zero of=/tmp/bw_test bs=1024 count=1024 >/dev/null 2>&1; then
        local end_time=$(date +%s)
        local duration=$((end_time - start_time))
        if [ $duration -gt 0 ]; then
            local throughput=$((1024 / duration))
            log "✓ Local I/O throughput: ${throughput} KB/s"
        else
            log "✓ Local I/O test completed quickly"
        fi
        rm -f /tmp/bw_test
    else
        log "✗ Local I/O test failed"
    fi
}

# Generate controlled internal traffic using nping
nping_internal_traffic() {
    if ! command -v nping >/dev/null 2>&1; then
        return 1
    fi
    
    local base_ip="172.18.0"
    local my_ip=$(ip addr show | grep "$base_ip" | head -1 | awk '{print $2}' | cut -d'/' -f1)
    
    log "Starting controlled nping traffic generation..."
    
    # Target other containers with controlled traffic
    for octet in 10 11 12 13 14 15; do
        local target_ip="${base_ip}.${octet}"
        if [ "$target_ip" != "$my_ip" ]; then
            # TCP SYN packets at controlled rate (10 pps for 5 seconds)
            nping --tcp -p 8080,22,80 --rate 10 --count 50 "$target_ip" >/dev/null 2>&1 &
            
            # UDP packets at controlled rate (5 pps for 5 seconds)  
            nping --udp -p 53,123 --rate 5 --count 25 "$target_ip" >/dev/null 2>&1 &
            
            # ICMP packets at controlled rate (2 pps for 10 seconds)
            nping --icmp --rate 2 --count 20 "$target_ip" >/dev/null 2>&1 &
        fi
    done
    
    # Generate loopback traffic
    nping --tcp -p 22,80,443 --rate 15 --count 30 127.0.0.1 >/dev/null 2>&1 &
    nping --icmp --rate 5 --count 25 127.0.0.1 >/dev/null 2>&1 &
    
    log "✓ nping traffic generation started (controlled rates)"
}

# Burst traffic generation for testing
nping_traffic_burst() {
    if ! command -v nping >/dev/null 2>&1; then
        log "! nping not available for burst traffic"
        return 1
    fi
    
    local base_ip="172.18.0"
    local target_found=0
    
    # Find one target container for concentrated traffic
    for octet in 10 11 12 13 14 15; do
        local target_ip="${base_ip}.${octet}"
        if ping -c 1 -W 1 "$target_ip" >/dev/null 2>&1; then
            target_found=1
            log "Generating traffic burst to $target_ip"
            
            # Short, intense burst (safe rates)
            nping --tcp -p 80,443,8080,22 --rate 25 --count 50 "$target_ip" >/dev/null 2>&1 &
            nping --udp -p 53,123,161 --rate 15 --count 30 "$target_ip" >/dev/null 2>&1 &
            nping --icmp --rate 10 --count 20 "$target_ip" >/dev/null 2>&1 &
            
            break
        fi
    done
    
    if [ $target_found -eq 0 ]; then
        log "! No target containers found for burst traffic"
        return 1
    fi
    
    log "✓ Traffic burst initiated (25 TCP, 15 UDP, 10 ICMP pps)"
}

# Enhanced main traffic generation loop
main_loop() {
    log "Starting ENHANCED traffic generation (PID: $$)"
    log "Mode: Safe internal traffic with controlled nping bursts"
    
    # Install tools first
    install_tools
    
    local iteration=0
    while true; do
        iteration=$((iteration + 1))
        log "=== Enhanced Traffic Iteration $iteration ==="
        
        # Original connectivity tests (reduced frequency for external)
        if [ $((iteration % 3)) -eq 0 ]; then
            # External tests every 3rd iteration only (every ~45s)
            test_external
            test_dns
        fi
        
        # Always do internal connectivity tests
        ping_peers
        http_test
        bandwidth_test
        
        # Enhanced traffic generation with nping
        if [ $((iteration % 2)) -eq 0 ]; then
            # Every other iteration: controlled internal traffic
            nping_internal_traffic
        else
            # Alternate iterations: traffic bursts
            nping_traffic_burst
        fi
        
        # Wait for nping processes to complete
        sleep 5
        
        log "=== Iteration $iteration complete, sleeping 10s ==="
        sleep 10
    done
}

# Handle different modes
case "${1:-loop}" in
    "install")
        install_tools
        ;;
    "external")
        test_external
        ;;
    "dns")
        test_dns
        ;;
    "ping")
        ping_peers
        ;;
    "http")
        http_test
        ;;
    "bandwidth")
        bandwidth_test
        ;;
    "nping-internal")
        install_tools
        nping_internal_traffic
        ;;
    "nping-burst")
        install_tools
        nping_traffic_burst
        ;;
    "traffic-test")
        # High-traffic mode for testing dashboard impact - AGGRESSIVE TRAFFIC
        install_tools
        log "=== AGGRESSIVE HIGH TRAFFIC TEST MODE ==="
        
        # Start continuous background traffic generators
        log "Starting continuous high-rate traffic generators..."
        
        # Very aggressive rates for dramatic dashboard impact
        for target_octet in 10 11 12; do
            local target_ip="172.18.0.$target_octet"
            if [ "$target_ip" != "$(ip addr show | grep '172.18.0' | head -1 | awk '{print $2}' | cut -d'/' -f1)" ]; then
                # High-rate TCP traffic (100 pps continuous)
                nping --tcp -p 80,443,8080,22,21,25,53,110,143,993,995 --rate 100 --count 0 "$target_ip" >/dev/null 2>&1 &
                
                # High-rate UDP traffic (80 pps continuous)  
                nping --udp -p 53,123,161,162,514,1194,5060 --rate 80 --count 0 "$target_ip" >/dev/null 2>&1 &
                
                # ICMP flood (50 pps continuous)
                nping --icmp --rate 50 --count 0 "$target_ip" >/dev/null 2>&1 &
                
                log "Started aggressive traffic to $target_ip (100 TCP, 80 UDP, 50 ICMP pps)"
            fi
        done
        
        # Also flood loopback for internal traffic
        nping --tcp -p 22,80,443,8080 --rate 150 --count 0 127.0.0.1 >/dev/null 2>&1 &
        nping --udp -p 53,123 --rate 100 --count 0 127.0.0.1 >/dev/null 2>&1 &
        nping --icmp --rate 75 --count 0 127.0.0.1 >/dev/null 2>&1 &
        
        log "✓ AGGRESSIVE traffic generators started - sustained high rates for dashboard testing"
        
        # Keep running for traffic test duration (script will be killed by parent)
        while true; do
            sleep 10
            log "Aggressive traffic generation active..."
        done
        ;;
    "once")
        install_tools
        test_external
        test_dns
        ping_peers
        http_test
        bandwidth_test
        ;;
    "loop"|*)
        main_loop
        ;;
esac