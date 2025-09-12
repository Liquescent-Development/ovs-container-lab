# Network Simulation Scripts

This directory contains sophisticated network simulation and chaos engineering scripts for testing OVS behavior under various stress conditions. The scripts combine professional traffic generation, Pumba chaos engineering, and orchestrated failure scenarios.

## Quick Start

```bash
# Run a quick 10-minute demo
./demo.sh quick-demo

# Check demo status
./demo.sh status

# Stop all demo components
./demo.sh stop
```

For even simpler usage, use the Makefile from the project root:
```bash
make demo          # Run quick demo
make demo-full     # Run full 30-minute demo
make demo-status   # Check status
make demo-stop     # Stop everything
```

## Scripts Overview

### 1. demo.sh - Main Orchestrator
The primary demo orchestrator that combines all testing capabilities.

```bash
# Available commands
./demo.sh help                      # Show all options
./demo.sh full-demo                 # Full 30-minute demonstration
./demo.sh quick-demo                # Quick 10-minute demo
./demo.sh combined                  # Traffic + chaos simultaneously
./demo.sh traffic-only [intensity]  # Just traffic generation
./demo.sh chaos-only [scenario]     # Just chaos scenarios
./demo.sh status                    # Show current status
./demo.sh stop                      # Stop all components
```

**Traffic Intensities:**
- `low`: ~10,000 pps (baseline)
- `medium`: ~50,000 pps (moderate)
- `high`: ~200,000+ pps (stress test)
- `extreme`: Maximum possible (saturation)

**Chaos Scenarios:**
- `packet-loss-N`: N% packet loss (10, 20, 30, 40, 50, 60)
- `latency-N`: N ms latency (50, 100, 300, 500, 1000)
- `bandwidth-N`: N kbps bandwidth limit (25, 50, 100, 500, 1000)
- `cpu-stress-N`: N cores CPU stress (2, 4, 8, 16)

### 2. dashboard-demo.sh - Dashboard-Focused Demo
Specifically designed to showcase Grafana dashboard capabilities.

```bash
# Full dashboard demo (20 minutes)
./dashboard-demo.sh demo

# Quick demo (8 minutes)
./dashboard-demo.sh quick-demo

# Custom scenario
./dashboard-demo.sh custom [scenario] [duration] [interface]

# Examples
./dashboard-demo.sh custom packet-loss-30 120 eth0
./dashboard-demo.sh custom bandwidth-100 180 ovs-br0
./dashboard-demo.sh custom cpu-stress-8 120
```

### 3. underlay-failure-demo.sh - Infrastructure Failure Simulation
Simulates underlay network issues affecting OVS itself.

```bash
# Full underlay failure demonstration
./underlay-failure-demo.sh demo

# Focus on OVS stress
./underlay-failure-demo.sh ovs-stress

# Specific underlay failure
./underlay-failure-demo.sh underlay-failure
```

### 4. container-setup.sh - Container Management
Manages test containers connected to OVS bridge.

```bash
# Set up test containers
./container-setup.sh setup

# Remove test containers
./container-setup.sh teardown

# Show status
./container-setup.sh status

# Test connectivity
./container-setup.sh test-connectivity

# Reset everything
./container-setup.sh reset
```

**Note:** Traffic generation is now handled by the professional traffic-generator container, not the test containers.

## Traffic Generation

### Professional Traffic Generator
The project includes a dedicated traffic generator container with:
- **hping3**: TCP/UDP/ICMP flood attacks
- **iperf3**: Bandwidth testing
- **netperf**: Network benchmarking
- **Python Scapy**: Complex traffic patterns

### Traffic Capabilities
- **200,000+ packets per second** sustained
- Multiple attack patterns (SYN floods, UDP floods, ICMP floods)
- Fragmented packets and ARP storms
- Burst traffic patterns
- Configurable intensity levels

### Starting Traffic Generation
```bash
# Via demo script
./demo.sh traffic-only high

# Via Make (from project root)
make traffic-high
make traffic-low
make traffic-stop

# Manual control
docker exec traffic-generator pkill -f "hping3|python3"  # Stop
docker exec -d traffic-generator hping3 --flood ...       # Start custom
```

## Chaos Engineering with Pumba

The scripts integrate Pumba for network chaos injection:

### Network Chaos Types
- **Packet Loss**: 10-80% loss rates
- **Latency**: 50-1000ms delays
- **Bandwidth Limiting**: 25kbps to 1Mbps
- **Packet Corruption**: 5-20% corruption
- **Jitter**: 25-200ms variance
- **CPU/Memory Stress**: System resource exhaustion

### Running Chaos Scenarios
```bash
# Via demo script
./demo.sh chaos-only packet-loss-30 180  # 30% loss for 3 minutes
./demo.sh chaos-only cpu-stress-8 120    # 8-core stress for 2 minutes

# Via Make (from project root)
make chaos SCENARIO=packet-loss-30 DURATION=120
make chaos-stop

# Via dashboard-demo
./dashboard-demo.sh custom packet-loss-40 120 eth0
```

## Demo Scenarios

### Quick Demo (10 minutes)
1. Baseline with medium traffic (1 min)
2. High traffic + 30% packet loss (3 min)
3. CPU stress + bandwidth limit (3 min)
4. Extreme scenario (50% loss + floods) (2 min)
5. Recovery (1 min)

### Full Demo (30 minutes)
1. **Phase 1**: Baseline (2 min)
2. **Phase 2**: Traffic stress test (5 min)
3. **Phase 3**: Network chaos (8 min)
4. **Phase 4**: Resource exhaustion (5 min)
5. **Phase 5**: Combined stress (8 min)
6. **Phase 6**: Recovery (2 min)

### Combined Demo (Recommended)
Runs traffic generation and chaos scenarios simultaneously:
- 200k+ pps traffic
- 20% packet loss
- 50ms latency
- 4-core CPU stress

## Monitoring

### Grafana Dashboards
Access at http://localhost:3000 (admin/admin)

- **OVS Underlay Failure Detection**: Packet loss, drops, errors
- **OVS Datapath & Flow Analysis**: Flow cache performance
- **OVS Coverage & Drop Analysis**: Drop reasons and coverage events
- **OVS System Resources**: CPU, memory, I/O statistics

### Real-time Monitoring
```bash
# Watch packet rate
watch -n1 './demo.sh status'

# Monitor OVS metrics
curl -s http://localhost:9475/metrics | grep ovs_

# Check flow statistics
docker exec ovs ovs-ofctl -O OpenFlow13 dump-flows ovs-br0

# Watch for drops
docker exec ovs ovs-ofctl -O OpenFlow13 dump-ports ovs-br0 | grep drop
```

## Logs and Output

- Demo logs: `/tmp/ovs-demo-logs/demo.log`
- Dashboard demo: `/tmp/dashboard-demo.log`
- Underlay demo: `/tmp/underlay-failure-demo.log`

Monitor logs:
```bash
tail -f /tmp/ovs-demo-logs/demo.log
```

## Integration with CI/CD

```yaml
# GitHub Actions example
- name: Run OVS stress test
  run: |
    docker compose up -d
    ./scripts/network-simulation/demo.sh quick-demo
    # Check for failures
    docker exec ovs ovs-ofctl -O OpenFlow13 dump-ports ovs-br0 | grep drop
```

## Troubleshooting

### Traffic Generator Not Working
```bash
# Check if running
docker ps | grep traffic-generator

# Rebuild if needed
docker compose build traffic-generator

# Check logs
docker logs traffic-generator

# Manually start
./demo.sh traffic-only high
```

### Chaos Scenarios Not Applied
```bash
# List active chaos containers
docker ps --filter "name=chaos-"

# Stop all chaos
docker kill $(docker ps -q --filter "name=chaos-")

# Check Pumba logs
docker logs <chaos-container-name>
```

### Containers Not Connected to OVS
```bash
# Check OVS bridge
docker exec ovs ovs-vsctl show

# Reconnect containers
./container-setup.sh reset

# Manual connection
../ovs-docker-connect.sh <container> <ip>
```

## Best Practices

1. **Always start with baseline**: Establish normal metrics first
2. **Monitor dashboards**: Keep Grafana open during tests
3. **Progressive testing**: Start mild, increase severity
4. **Allow recovery time**: Give system time between scenarios
5. **Check logs**: Review logs for detailed information
6. **Resource monitoring**: Watch CPU/memory during tests

## Safety Features

- All scripts include proper cleanup commands
- Automatic stop on script interruption (Ctrl+C)
- Resource limits on chaos scenarios
- Timeout protection on long-running operations
- State tracking to prevent duplicate operations

## Advanced Usage

### Custom Traffic Patterns
Edit `/traffic-generator/traffic-gen.py` to create custom Scapy patterns.

### Extended Chaos Scenarios
Modify scenario arrays in demo scripts to add new test cases.

### Multi-Node Testing
Scripts can be extended to test multiple OVS instances by modifying target IPs.

## Files Generated

- Container metadata: Embedded in OVS port descriptions
- Metrics data: Stored in Prometheus (retention as configured)
- Grafana dashboards: Persisted in grafana-data volume
- Logs: Temporary files in /tmp (cleaned on reboot)

## Contributing

To add new scenarios:
1. Add to scenario arrays in demo scripts
2. Implement handler functions
3. Test with all dashboards
4. Document in this README
5. Submit pull request