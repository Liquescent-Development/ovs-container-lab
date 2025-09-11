# Network Simulation Scripts

This directory contains scripts to simulate various network failures and issues for testing OVS monitoring and alerting systems.

## Quick Start

The scripts can automatically set up test containers or work with existing ones:

```bash
# Automatic setup (recommended)
./chaos-orchestrator.sh start 10 30    # Automatically creates containers and runs tests

# Manual setup
./container-setup.sh setup             # Create test containers first
./chaos-orchestrator.sh start 10 30    # Then run simulations

# Cleanup when done
./chaos-orchestrator.sh cleanup        # Remove containers and stop simulations
```

## Individual Simulation Scripts

### 1. docker-isolation.sh
Simulates switch port failures by manipulating Docker network connectivity.
```bash
# Disconnect OVS from networks (simulate switch port down)
./docker-isolation.sh start

# Reconnect to networks  
./docker-isolation.sh stop

# Check status
./docker-isolation.sh status
```

### 2. traffic-control.sh
Uses Linux traffic control (tc) to simulate various network conditions.
```bash
# 75% packet loss
./traffic-control.sh packet-loss 75

# 2000ms latency with jitter
./traffic-control.sh high-latency 2000

# Bandwidth limitation to 10kbit/s
./traffic-control.sh bandwidth-limit 10kbit

# Remove all restrictions
./traffic-control.sh stop

# Show current rules
./traffic-control.sh status
```

### 3. firewall-rules.sh
Simulates switch ACL changes and firewall issues using iptables.
```bash
# Block all traffic
./firewall-rules.sh block-all

# Block only HTTP/HTTPS
./firewall-rules.sh block-http

# Block outbound traffic (upstream issues)
./firewall-rules.sh block-outbound

# Allow only local network traffic
./firewall-rules.sh allow-only-local

# Restore normal rules
./firewall-rules.sh stop

# Show current firewall status
./firewall-rules.sh status
```

### 4. interface-control.sh
Simulates physical interface failures and VLAN issues.
```bash
# Bring interface down (cable unplugged)
./interface-control.sh interface-down

# Create VLAN configuration problems
./interface-control.sh vlan-issues

# Set problematic MTU size
./interface-control.sh mtu-problems

# Change MAC address (NIC replacement)
./interface-control.sh mac-change

# Restore interface to normal
./interface-control.sh stop

# Show interface status
./interface-control.sh status
```

## Container Setup Script

### container-setup.sh
Manages test containers for network simulation testing.

```bash
# Create test containers and connect to OVS
./container-setup.sh setup

# Remove all test containers
./container-setup.sh teardown

# Show container status
./container-setup.sh status

# Test connectivity between containers
./container-setup.sh test-connectivity

# Reset (teardown + setup)
./container-setup.sh reset

# Customize container setup
CONTAINER_COUNT=5 ./container-setup.sh setup           # Create 5 containers
IMAGE_NAME=httpd:alpine ./container-setup.sh setup     # Use different image
BASE_IP=192.168.1 ./container-setup.sh setup          # Different IP range
```

## Orchestration Script

### chaos-orchestrator.sh
Runs multiple failure simulations over time for comprehensive testing.

```bash
# Start 30-minute chaos test with 120-second intervals (auto-creates containers)
./chaos-orchestrator.sh start

# Start 60-minute test with 90-second intervals  
./chaos-orchestrator.sh start 60 90

# Start 10-minute test with 30-second intervals
./chaos-orchestrator.sh start 10 30

# Set up containers only
./chaos-orchestrator.sh setup

# Stop all running simulations
./chaos-orchestrator.sh stop

# Clean up everything (stop simulations + remove containers)
./chaos-orchestrator.sh cleanup

# Show current status
./chaos-orchestrator.sh status

# Test each simulation briefly (5 seconds each)
./chaos-orchestrator.sh test-all

# List available simulations
./chaos-orchestrator.sh list-simulations
```

## Usage Examples

### Quick Individual Test
```bash
# Test packet loss simulation
./traffic-control.sh packet-loss 50
sleep 30
./traffic-control.sh stop
```

### Comprehensive Testing
```bash
# Run chaos testing for 1 hour
./chaos-orchestrator.sh start 60 120
```

### Monitor During Testing
```bash
# In one terminal - start simulation
./chaos-orchestrator.sh start 30 60

# In another terminal - watch metrics
watch -n 5 'curl -s localhost:9475/metrics | grep ovs_up'

# Or watch Grafana dashboard at http://localhost:3000
```

## Monitoring Impact

These simulations will affect various OVS metrics:

- **ovs_up**: Goes to 0 during severe failures
- **ovs_bridge_ports**: Changes when interfaces are affected
- **ovs_datapath_flows**: Varies with traffic control
- **Network connectivity**: Container-to-container ping tests will fail

## Safety Notes

- All scripts include proper cleanup (`stop` command)
- Original configurations are backed up when possible
- Scripts check for container existence before running
- Use `chaos-orchestrator.sh stop` to immediately stop all simulations

## Log Files

- Chaos orchestrator logs: `/tmp/chaos-orchestrator.log`
- Individual script state files: `/tmp/*_simulation_state`
- Backup files: `/tmp/*_backup*`

Clean up with: `rm -f /tmp/*simulation* /tmp/*backup*`