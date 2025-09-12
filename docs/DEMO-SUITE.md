# OVS Container Lab Demo Suite

## Overview

The OVS Container Lab includes a comprehensive demo suite that showcases how Open vSwitch behaves under various stress conditions including high traffic loads, network chaos, and underlay failures. The suite combines professional traffic generation tools, Pumba chaos engineering, and orchestrated failure scenarios to demonstrate real-world network issues and their impact on OVS metrics.

## Demo Components

### 1. Demo Orchestrator (`demo.sh`)

The demo orchestrator provides a unified interface to run all demo scenarios:

```bash
# Run the full 30-minute demonstration
./scripts/network-simulation/demo.sh full-demo

# Run a quick 10-minute demo
./scripts/network-simulation/demo.sh quick-demo

# Run combined traffic + chaos scenarios
./scripts/network-simulation/demo.sh combined

# Check current demo status
./scripts/network-simulation/demo.sh status

# Stop all demo components
./scripts/network-simulation/demo.sh stop
```

**Features:**
- Professional traffic generation using hping3 and Scapy (200,000+ pps)
- Orchestrated Pumba chaos scenarios (packet loss, latency, bandwidth limits)
- Resource exhaustion simulation (CPU, memory stress)
- Real-time metrics monitoring
- Color-coded output for easy reading

### 2. Dashboard Demo (`dashboard-demo.sh`)

Focused on demonstrating the Grafana dashboards with various failure scenarios:

```bash
# Full dashboard demo (20 minutes)
./scripts/network-simulation/dashboard-demo.sh demo

# Quick demo (8 minutes)
./scripts/network-simulation/dashboard-demo.sh quick-demo

# Custom scenario
./scripts/network-simulation/dashboard-demo.sh custom packet-loss-30 120 ovs-br0
```

**Scenarios include:**
- Packet loss (10%, 30%, 50%, 60%)
- Packet corruption (5%, 10%, 15%)
- Bandwidth limiting (25kbps, 50kbps, 100kbps vs 112Mbps traffic)
- Network latency (100ms, 300ms, 500ms, 1000ms)
- Network jitter (25ms, 50ms, 100ms, 200ms)
- CPU stress (2, 4, 8, 16, 32 cores)

### 3. Underlay Failure Demo (`underlay-failure-demo.sh`)

Simulates infrastructure-level failures affecting OVS itself:

```bash
# Full underlay failure demonstration
./scripts/network-simulation/underlay-failure-demo.sh demo

# Focus on OVS stress scenarios
./scripts/network-simulation/underlay-failure-demo.sh ovs-stress

# Specific underlay failure
./scripts/network-simulation/underlay-failure-demo.sh underlay-failure
```

**Demonstrates:**
- Underlay packet loss affecting OVS control plane
- Infrastructure latency impacting OVS operations
- System-wide resource exhaustion
- Cascading failure scenarios

### 4. Container Setup (`container-setup.sh`)

Sets up the test environment with containers connected to OVS:

```bash
# Setup test containers
./scripts/network-simulation/container-setup.sh setup

# Test connectivity
./scripts/network-simulation/container-setup.sh test-connectivity

# Cleanup
./scripts/network-simulation/container-setup.sh cleanup
```

## Traffic Generation

### Professional Traffic Generator

The demo suite includes a custom Docker container with professional traffic generation tools:

**Tools included:**
- **hping3**: TCP/UDP/ICMP flood attacks, SYN floods, custom packet crafting
- **iperf3**: Bandwidth testing and sustained traffic generation
- **netperf**: Network performance benchmarking
- **Scapy (Python)**: Complex traffic patterns, fragmented packets, ARP storms
- **tcpreplay**: Replay captured traffic patterns

**Traffic patterns generated:**
- TCP SYN/ACK floods (multiple ports)
- UDP floods with varying packet sizes
- ICMP floods with 1400-byte packets
- Fragmented packet streams
- ARP broadcast storms
- Burst traffic patterns
- Sustained bandwidth saturation

### Traffic Intensity Levels

The demo supports multiple traffic intensity levels:

- **Low**: ~10,000 pps (baseline traffic)
- **Medium**: ~50,000 pps (moderate load)
- **High**: ~200,000+ pps (stress test)
- **Extreme**: Maximum possible (system saturation)

## Chaos Engineering with Pumba

The demo suite integrates Pumba for network chaos injection:

### Network Emulation
- **Packet Loss**: 10%, 25%, 30%, 40%, 50%, 60%, 80%
- **Latency**: 50ms, 100ms, 300ms, 500ms, 1000ms
- **Bandwidth Limiting**: 25kbps, 50kbps, 100kbps, 200kbps, 500kbps, 1Mbps
- **Packet Corruption**: 5%, 10%, 15%, 20%
- **Packet Duplication**: 10%, 25%, 50%
- **Packet Reordering**: 25%, 50%, 75%
- **Network Jitter**: 25ms, 50ms, 100ms, 200ms variance

### Resource Stress
- **CPU Stress**: 2, 4, 8, 16, 32 cores
- **Memory Stress**: 256MB, 512MB, 1GB, 2GB
- **I/O Stress**: Read/write operations

## Monitoring and Dashboards

The demo suite is designed to showcase four main Grafana dashboards:

### 1. OVS Underlay Failure Detection
- Shows packet loss, drops, and errors
- TX/RX imbalance detection
- Interface-level statistics
- Real-time failure indicators

### 2. OVS Datapath & Flow Analysis
- Flow cache hit rate (normally 99%+)
- Packet processing rate
- Flow table utilization
- Datapath performance metrics

### 3. OVS Coverage & Drop Analysis
- Drop reason breakdown
- Pipeline drops
- Execute errors
- Coverage event tracking

### 4. OVS System Resources
- CPU utilization by OVS processes
- Memory usage patterns
- I/O statistics
- Container resource metrics

## Demo Scenarios

### Full Demo (30 minutes)

Comprehensive demonstration covering all aspects:

1. **Phase 1: Baseline (2 min)**
   - Normal traffic patterns
   - Establish baseline metrics

2. **Phase 2: Traffic Stress Test (5 min)**
   - Ramp up to 200k+ pps
   - Monitor flow cache performance

3. **Phase 3: Network Chaos (8 min)**
   - Progressive packet loss (10% → 30% → 50%)
   - Latency injection (50ms → 100ms → 500ms)
   - Bandwidth constraints

4. **Phase 4: Resource Exhaustion (5 min)**
   - CPU stress (8 → 16 cores)
   - Memory pressure
   - Combined resource stress

5. **Phase 5: Combined Stress (8 min)**
   - Maximum traffic + 30% packet loss
   - CPU stress + bandwidth limits
   - Multiple simultaneous failures

6. **Phase 6: Recovery (2 min)**
   - Remove all chaos
   - Return to baseline
   - Observe metric stabilization

### Quick Demo (10 minutes)

Abbreviated version hitting key scenarios:

1. **Baseline (1 min)**: Establish normal metrics
2. **Traffic + Loss (3 min)**: High traffic with 30% packet loss
3. **Resource Stress (3 min)**: CPU stress + bandwidth limiting
4. **Extreme Scenario (2 min)**: 50% loss + flood attacks
5. **Recovery (1 min)**: Return to normal

### Combined Demo (Recommended)

Simultaneous traffic generation and chaos engineering:
- Continuous 200k+ pps traffic
- 20% packet loss
- 50ms latency
- 4-core CPU stress
- Demonstrates real-world complex failure scenarios

## Usage Examples

### Running a Full Demo

```bash
# Start the monitoring stack
docker compose up -d

# Ensure test environment is ready
./scripts/network-simulation/container-setup.sh setup

# Run the full demo
./scripts/network-simulation/demo.sh full-demo

# Monitor status in another terminal
watch -n1 './scripts/network-simulation/demo.sh status'

# View logs
tail -f /tmp/ovs-demo-logs/demo.log
```

### Custom Chaos Scenario

```bash
# Start high traffic
./scripts/network-simulation/demo.sh traffic-only high

# In another terminal, inject 30% packet loss for 2 minutes
./scripts/network-simulation/dashboard-demo.sh custom packet-loss-30 120

# Add CPU stress
./scripts/network-simulation/dashboard-demo.sh custom cpu-stress-8 120

# Stop everything
./scripts/network-simulation/demo.sh stop
```

### Testing Specific Failures

```bash
# Test bandwidth limiting impact
./scripts/network-simulation/demo.sh traffic-only high
./scripts/network-simulation/dashboard-demo.sh custom bandwidth-100 180 ovs-br0

# Test extreme packet loss
./scripts/network-simulation/demo.sh traffic-only extreme
./scripts/network-simulation/dashboard-demo.sh custom packet-loss-60 120
```

## Best Practices

1. **Start with Baseline**: Always establish baseline metrics before introducing chaos
2. **Monitor Dashboards**: Keep Grafana dashboards open during demos
3. **Progressive Chaos**: Start with mild scenarios and progressively increase severity
4. **Allow Recovery Time**: Give the system time to recover between scenarios
5. **Check Logs**: Monitor logs for detailed information about what's happening
6. **Resource Monitoring**: Watch system resources (CPU, memory) during demos

## Troubleshooting

### Traffic Generator Issues

```bash
# Check if traffic generator is running
docker ps | grep traffic-gen-pro

# View traffic generator logs
docker logs traffic-gen-pro

# Restart traffic generator
docker restart traffic-gen-pro

# Check active traffic processes
docker exec traffic-gen-pro ps aux | grep -E "hping3|python3"
```

### Pumba/Chaos Issues

```bash
# List active chaos containers
docker ps --filter "name=chaos-"

# Stop all chaos containers
docker kill $(docker ps -q --filter "name=chaos-")

# Check Pumba logs
docker logs <chaos-container-name>
```

### OVS Metrics Issues

```bash
# Check OVS is running
docker exec ovs ovs-vsctl show

# Check metrics endpoint
curl -s http://localhost:9475/metrics | grep ovs_

# Check flow statistics
docker exec ovs ovs-ofctl -O OpenFlow13 dump-flows ovs-br0
```

## Performance Considerations

- The professional traffic generator can produce 200,000+ pps
- This may consume significant CPU resources
- Monitor system resources during demos
- Adjust traffic intensity if system becomes unresponsive
- Use `traffic-only medium` for resource-constrained systems

## Integration with CI/CD

The demo scripts can be integrated into CI/CD pipelines for automated testing:

```yaml
# Example GitHub Actions workflow
- name: Run OVS stress test
  run: |
    docker compose up -d
    ./scripts/network-simulation/demo.sh quick-demo
    # Check for failures
    docker exec ovs ovs-ofctl -O OpenFlow13 dump-ports ovs-br0 | grep drop
```

## Future Enhancements

Planned improvements for the demo suite:

1. **Automated metric validation**: Check if metrics match expected patterns
2. **Scenario recording/replay**: Record demo runs for consistent replay
3. **Multi-node simulation**: Extend to multiple OVS instances
4. **BGP/OSPF integration**: Add routing protocol failures
5. **Security scenarios**: DDoS attack simulation
6. **Performance benchmarking**: Automated performance regression testing

## Contributing

To add new demo scenarios:

1. Add scenario to the appropriate array in the demo scripts
2. Implement the scenario logic
3. Test thoroughly with all dashboards
4. Document the scenario in this file
5. Submit a pull request

## Support

For issues or questions about the demo suite:

1. Check the troubleshooting section above
2. Review logs in `/tmp/ovs-demo-logs/`
3. Open an issue on GitHub with:
   - Demo command used
   - Error messages
   - System specifications
   - Docker and OVS versions