# Demo and Testing Guide

## Overview

The OVS Container Lab provides comprehensive demo and testing capabilities for the multi-VPC cloud network simulation. This guide covers all available demonstrations, stress tests, and chaos engineering scenarios.

## Quick Demos

### Basic Demo (10 minutes)
```bash
make demo
```
Runs a standard demonstration that includes:
- Phase 1: Normal traffic (2 min)
- Phase 2: Network degradation with packet loss (2 min)
- Phase 3: Combined high traffic + CPU stress (3 min)
- Phase 4: Traffic overload (2 min)
- Phase 5: Recovery testing (1 min)

### Comprehensive Demo (30 minutes)
```bash
make demo-full
```
Extended demonstration covering:
- All chaos scenarios (packet loss, CPU stress, memory stress)
- Multiple stress levels
- Recovery testing between phases
- Maximum stress testing with combined failures

## Stress Testing

### Standard Stress Test (2 minutes)
```bash
make stress
```
- Moderate CPU stress on all components
- High traffic generation
- Flow table stress

### Heavy Stress Test (5 minutes)
```bash
make stress-heavy
```
- Heavy CPU and memory stress on all components
- Network degradation (10% packet loss)
- Traffic overload (50,000+ pps)
- Flow table explosion (5000+ flows)

## Chaos Engineering

### Interactive Chaos Scenarios
```bash
make chaos
```
Select from:
1. **Packet Loss (30%)** - Simulates unreliable network
2. **CPU Stress** - Exhausts CPU resources
3. **Memory Pressure** - Creates memory exhaustion
4. **Network Partition** - Simulates split-brain scenario
5. **Cascading Failure** - Progressive component failures

### Manual Chaos Control
```bash
# Run specific scenario for custom duration
./scripts/chaos-scenario.sh 1 180  # Packet loss for 3 minutes
```

## Traffic Generation

The traffic generator (`traffic-generator` container) supports multiple intensities:

| Intensity | Packets/sec | Use Case |
|-----------|------------|----------|
| low | 10-50 | Normal application traffic |
| medium | 1,000-5,000 | Moderate load |
| high | 10,000-50,000 | Heavy load |
| overload | 50,000+ | Stress testing |

### Manual Traffic Generation
```bash
# Generate specific traffic pattern
docker exec traffic-generator python3 /vpc-traffic-gen.py high 60
```

## Monitoring During Demos

### Real-time Monitoring
```bash
# Watch traffic rates
make watch-traffic

# Watch flow tables
make watch-flows

# Check metrics
make metrics
```

### Grafana Dashboards
Access at http://localhost:3000 (admin/admin):
- **Multi-VPC Monitoring** - Overall infrastructure health
- **OVS Underlay Failure Detection** - Network failure scenarios
- **OVS Datapath & Flow Analysis** - Flow table analytics
- **OVS Coverage & Drops Analysis** - Packet drop investigation

## Demo Scenarios Explained

### Standard Demo Flow
1. **Baseline Establishment** - Normal traffic to establish baseline metrics
2. **Gradual Degradation** - Introduce failures progressively
3. **Peak Stress** - Maximum load to test limits
4. **Recovery** - Remove stress and monitor recovery

### What to Observe
- **Grafana Dashboards**: Watch for spikes in drops, latency, CPU usage
- **Inter-VPC Connectivity**: Monitor when routing fails/recovers
- **Component Health**: Check which components fail first under stress
- **Recovery Time**: Measure how quickly the system recovers

## Customizing Demos

### Modify Demo Scripts
Scripts are located in `/scripts/`:
- `run-demo.sh` - Main demo orchestrator
- `stress-test.sh` - Stress testing logic
- `chaos-scenario.sh` - Chaos scenarios

### Adjust Timing
Edit durations in scripts:
```bash
DURATION=${2:-600}  # Change default duration
```

### Add Custom Scenarios
Add new chaos scenarios to `chaos-scenario.sh`:
```bash
6)
    echo "Custom scenario..."
    # Your chaos commands here
    ;;
```

## Best Practices

1. **Start Fresh**: Always run `make clean` before important demos
2. **Monitor Resources**: Ensure Docker has enough CPU/memory allocated
3. **Check Baseline**: Run `make test` before demos to verify connectivity
4. **Watch Dashboards**: Keep Grafana open during demos for best visibility
5. **Document Results**: Note which scenarios cause failures for analysis

## Troubleshooting Demo Issues

### Demo Won't Start
```bash
make clean
make up
make test  # Verify basic connectivity
make demo
```

### Traffic Generator Not Working
```bash
docker ps | grep traffic-generator
docker logs traffic-generator
docker exec traffic-generator python3 /vpc-traffic-gen.py medium 10
```

### Chaos Not Applied
```bash
docker ps | grep pumba
docker ps | grep chaos
```

### Metrics Not Updating
```bash
curl http://localhost:9476/metrics | grep ovs_
make metrics
```