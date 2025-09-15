# Chaos Testing Guide for OVS Container Lab

## Overview

This lab uses **Pumba** (a chaos testing tool for Docker) to simulate various network failures and test the resilience of the OVS/OVN overlay network. The chaos testing framework helps validate how well the overlay network handles underlay failures, network partitions, and various degraded conditions.

## Architecture Context

```
┌─────────────────────────────────────────────────────────────┐
│                         OVERLAY NETWORK                        │
│                    (GENEVE Tunnels via OVN)                   │
├─────────────────────────────────────────────────────────────┤
│                         UNDERLAY NETWORK                       │
│              (OVS Bridges + Docker Networking)                │
└─────────────────────────────────────────────────────────────┘
```

- **Underlay**: Physical network infrastructure (OVS instances, Docker networks)
- **Overlay**: Logical network built on top (OVN logical switches, GENEVE tunnels)

## Quick Start

```bash
# Start the environment
make vpc-up

# Generate traffic to observe during chaos
make traffic-chaos

# Run a simple chaos test
make chaos-loss

# Test underlay resilience
make chaos-underlay
```

## Chaos Scenarios

### Basic Network Chaos

#### 1. Packet Loss (`make chaos-loss`)
**What it does**: Introduces 30% packet loss on all VPC containers
**Duration**: 60 seconds
**Target**: All containers matching `vpc-.*`
**Use case**: Test application retry logic and timeout handling
**Expected behavior**:
- Traffic should continue but with degraded performance
- TCP should retransmit lost packets
- Applications should handle intermittent failures

#### 2. Network Latency (`make chaos-delay`)
**What it does**: Adds 100ms delay with 20ms jitter
**Duration**: 60 seconds
**Target**: All VPC containers
**Use case**: Test application behavior under high latency conditions
**Expected behavior**:
- Increased response times
- Possible timeout issues for latency-sensitive applications
- Connection pooling may become exhausted

#### 3. Bandwidth Limitation (`make chaos-bandwidth`)
**What it does**: Limits network bandwidth to 1 Mbit/s
**Duration**: 60 seconds
**Target**: All VPC containers
**Use case**: Test application behavior under constrained bandwidth
**Expected behavior**:
- Slower data transfers
- Possible request queuing
- Streaming applications may buffer or downgrade quality

#### 4. Network Partition (`make chaos-partition`)
**What it does**: Creates network isolation by pausing containers
**Duration**: 30 seconds
**Target**: Web tier containers (`vpc-.*-web`)
**Use case**: Test split-brain scenarios and partition tolerance
**Expected behavior**:
- Affected containers become unreachable
- Health checks should fail
- Traffic should failover to healthy containers

#### 5. Packet Corruption (`make chaos-corruption`)
**What it does**: Corrupts 5% of network packets
**Duration**: 60 seconds
**Target**: All VPC containers
**Use case**: Test checksum validation and error detection
**Expected behavior**:
- TCP should detect and retransmit corrupted packets
- UDP traffic may experience data corruption
- Application-level checksums should catch errors

#### 6. Packet Duplication (`make chaos-duplication`)
**What it does**: Duplicates 10% of network packets
**Duration**: 60 seconds
**Target**: All VPC containers
**Use case**: Test idempotency and duplicate handling
**Expected behavior**:
- TCP should handle duplicates transparently
- Applications should handle duplicate requests properly
- Possible out-of-order packet delivery

### Advanced Chaos Scenarios

#### 7. Underlay Chaos (`make chaos-underlay`)
**What it does**: Targets OVS/OVN infrastructure components
**Duration**: 60 seconds
**Targets**:
- `ovs-vpc-a` - OVS instance for VPC-A
- `ovs-vpc-b` - OVS instance for VPC-B
- `ovn-central` - OVN control plane

**How it works**:
1. Applies 20% packet loss to each infrastructure component
2. Runs all chaos simultaneously to stress the underlay
3. Tests whether overlay traffic continues despite underlay issues

**Expected behavior**:
- GENEVE tunnels should handle packet loss
- OVN should maintain logical network state
- Some performance degradation but overlay should remain functional
- Control plane (OVN) issues may delay network changes but shouldn't affect existing flows

**Monitoring focus**:
- Watch `ovn_failed_requests_total` metric
- Monitor GENEVE tunnel status
- Check if overlay traffic continues between VPCs

#### 8. Overlay Resilience Test (`make chaos-overlay-test`)
**What it does**: Combined stress test with multiple simultaneous failures
**Duration**: 90 seconds
**Simultaneous failures**:
- 15% packet loss on VPC-A containers
- 50ms delay with 10ms jitter on VPC-B containers
- 2% packet corruption on traffic generators

**Use case**: Comprehensive resilience testing under multiple failure modes
**Expected behavior**:
- System should remain operational despite multiple issues
- Performance will be degraded but not failed
- Tests the overall system resilience

### Direct Container Actions

#### Kill Container (`make chaos-kill`)
**What it does**: Sends SIGKILL to a random web container
**Target**: One container matching `vpc-.*-web`
**Use case**: Test sudden container failure
**Expected behavior**:
- Container should be restarted by Docker
- Traffic should failover to other containers
- Brief service interruption for affected connections

#### Pause Containers (`make chaos-pause`)
**What it does**: Freezes container execution for 30 seconds
**Target**: 2 random VPC containers
**Use case**: Test container unresponsiveness
**Expected behavior**:
- Containers become unresponsive but don't disappear
- Health checks timeout
- Traffic should route around paused containers

## Monitoring During Chaos

### Key Dashboards

1. **OVS Docker Monitoring** (`http://localhost:3000`)
   - Watch for spikes in:
     - Interface errors & drops
     - Packet loss indicators
     - Flow misses

2. **OVN SLA Performance**
   - Monitor:
     - Error rates
     - Failed requests
     - Response times

3. **OVS Underlay Failure Detection**
   - Observe:
     - Link state changes
     - Datapath flow statistics
     - Coverage events

### Key Metrics to Watch

```prometheus
# Packet loss and errors
rate(ovs_interface_rx_dropped_total[1m])
rate(ovs_interface_tx_errors_total[1m])

# OVN health
ovn_failed_requests_total
ovn_chassis_info

# Flow statistics
ovs_dp_flows
rate(ovs_dp_lookups_missed_total[1m])

# Tunnel status (for overlay monitoring)
ovn_logical_switch_tunnel_key
```

## Testing Methodology

### 1. Baseline Establishment
```bash
# Start normal traffic
make traffic-run

# Observe normal metrics for 2-3 minutes
# Note baseline values for latency, throughput, error rates
```

### 2. Chaos Introduction
```bash
# While traffic is running, introduce chaos
make chaos-loss  # or other scenario

# Observe:
# - How quickly the issue is detected
# - Impact on traffic flow
# - Recovery mechanisms activation
```

### 3. Recovery Validation
```bash
# After chaos ends, verify:
# - System returns to baseline performance
# - No lingering effects
# - All connections re-established
```

## Underlay vs Overlay Testing Strategy

### Testing Underlay Impact on Overlay

1. **Start overlay traffic between VPCs**:
   ```bash
   make traffic-chaos  # High-volume inter-VPC traffic
   ```

2. **Target underlay infrastructure**:
   ```bash
   make chaos-underlay  # Affects OVS/OVN components
   ```

3. **Observe overlay behavior**:
   - Does GENEVE tunnel traffic continue?
   - Are logical flows maintained?
   - Is there automatic failover?

### Expected Resilience Behaviors

✅ **Good resilience indicators**:
- Overlay traffic continues despite underlay packet loss
- OVN logical flows remain programmed
- Automatic path selection around failures
- Graceful degradation rather than complete failure

❌ **Poor resilience indicators**:
- Complete traffic stoppage
- Logical flows disappearing
- Unable to establish new connections
- Cascading failures across VPCs

## Custom Chaos Scenarios

### Using Orchestrator Directly

```bash
# Custom packet loss percentage
sudo python3 orchestrator.py chaos packet-loss --duration 120 --target "vpc-a-.*"

# Target specific containers
sudo python3 orchestrator.py chaos latency --duration 30 --target "traffic-gen-.*"

# Longer duration tests
sudo python3 orchestrator.py chaos bandwidth --duration 300 --target "vpc-b-.*"
```

### Using Pumba Directly

```bash
# Custom packet loss with specific percentage
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock gaiaadm/pumba \
  netem --duration 60s --tc-image gaiadocker/iproute2 \
  loss --percent 50 re2:"^vpc-"

# Reorder packets (out-of-order delivery)
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock gaiaadm/pumba \
  netem --duration 60s --tc-image gaiadocker/iproute2 \
  reorder --percent 25 --gap 5 re2:"^vpc-"

# Combined effects
docker run --rm -v /var/run/docker.sock:/var/run/docker.sock gaiaadm/pumba \
  netem --duration 60s --tc-image gaiadocker/iproute2 \
  loss --percent 10 \
  delay --time 50 --jitter 10 \
  re2:"^vpc-"
```

## Troubleshooting

### Common Issues

1. **"Container not found" errors**
   - Ensure containers are running: `docker ps | grep vpc`
   - Check container names match the regex patterns

2. **No visible impact during chaos**
   - Verify traffic is running: `make traffic-status`
   - Check Pumba is executing: `docker ps | grep pumba`
   - Ensure target pattern matches containers

3. **System becomes unresponsive**
   - Stop all chaos: `docker stop $(docker ps -q --filter "ancestor=gaiaadm/pumba")`
   - Reset networking: `make clean-all && make vpc-up`

### Cleanup Commands

```bash
# Stop all Pumba chaos containers
docker stop $(docker ps -q --filter "ancestor=gaiaadm/pumba")

# Reset all network rules (if manual chaos was applied)
for container in $(docker ps --format "{{.Names}}" | grep "^vpc-"); do
  docker exec $container tc qdisc del dev eth0 root 2>/dev/null || true
done

# Full reset
make clean-all
make vpc-up
```

## Best Practices

1. **Always establish baseline** before chaos testing
2. **Monitor during chaos** to understand impact
3. **Start with small durations** (30s) before longer tests
4. **Use traffic generation** to have observable impact
5. **Document observations** for each scenario
6. **Test recovery** after chaos ends
7. **Gradually increase intensity** rather than starting with extreme scenarios

## Integration with CI/CD

```yaml
# Example GitHub Actions workflow
chaos-test:
  runs-on: ubuntu-latest
  steps:
    - name: Setup environment
      run: make vpc-up

    - name: Generate baseline traffic
      run: make traffic-run &

    - name: Run chaos test
      run: |
        make chaos-loss
        sleep 60

    - name: Validate recovery
      run: make test-connectivity
```

## Further Reading

- [Pumba Documentation](https://github.com/alexei-led/pumba)
- [OVN Architecture Guide](http://www.openvswitch.org/support/dist-docs/ovn-architecture.7.html)
- [Chaos Engineering Principles](https://principlesofchaos.org/)
- [Network Emulation with tc/netem](https://man7.org/linux/man-pages/man8/tc-netem.8.html)