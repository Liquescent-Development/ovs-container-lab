# Containerized Open vSwitch Monitoring & Network Chaos Testing Stack

A fully containerized testing and monitoring environment for Open vSwitch (OVS) networking with Docker containers, featuring comprehensive monitoring, automated traffic generation, and network chaos engineering capabilities. This stack provides complete OVS bridge setup, container networking, high-volume traffic simulation, and chaos testing - all running in Docker containers without requiring any host installations.

## What This Provides

- **Open vSwitch** running in userspace datapath mode for container network virtualization
- **Compose-managed test containers** automatically connected to OVS bridge with network services
- **Professional traffic generation** using hping3, iperf3, and Scapy for 200,000+ pps load testing
- **Network chaos engineering** with Pumba integration for failure simulation
- **Comprehensive monitoring** through Prometheus and Grafana with OVS-specific dashboards
- **Automated network simulation** scripts for underlay failure detection testing
- **Custom OVS exporter** providing detailed interface and datapath metrics
- **Cross-platform compatibility** working on macOS, Linux, and Windows without host dependencies

## Quick Start

### Using Make (Recommended)
```bash
# Start the monitoring stack
make up

# Run a quick demo (10 minutes)
make demo

# Check status
make status

# Stop everything
make down
```

### Using Docker Compose Directly
```bash
# Start the core monitoring stack
docker compose up -d

# Wait for services to initialize (about 30 seconds)
docker compose ps

# Access the dashboards
# Prometheus: http://localhost:9090
# Grafana: http://localhost:3000 (admin/admin)
# OVS Metrics: http://localhost:9475/metrics
```

### Network Simulation & Chaos Testing
```bash
# Quick demo (10 minutes) - combines traffic generation and chaos
./scripts/network-simulation/demo.sh quick-demo

# Full demo (30 minutes) - comprehensive stress testing
./scripts/network-simulation/demo.sh full-demo

# Start professional traffic generation (200k+ pps)
./scripts/network-simulation/demo.sh traffic-only high

# Monitor the dashboards
# OVS Underlay Failure: http://localhost:3000/d/ovs-underlay-failure/ovs-underlay-failure-detection
# Datapath & Flow Analysis: http://localhost:3000/d/ovs-datapath-flow/ovs-datapath-flow-analysis
# Coverage & Drops: http://localhost:3000/d/ovs-coverage-drops/ovs-coverage-drops-analysis

# Run specific chaos scenarios
./scripts/network-simulation/demo.sh chaos-only packet-loss-30 180  # 30% packet loss for 3 min
./scripts/network-simulation/demo.sh chaos-only cpu-stress-8 120    # 8-core CPU stress for 2 min

# Check demo status
./scripts/network-simulation/demo.sh status

# Stop all demo components
./scripts/network-simulation/demo.sh stop
```

## Full Documentation

### Prerequisites

- Docker and Docker Compose installed
- Works on macOS, Linux, and Windows (with WSL2)
- Basic understanding of container networking

**Note**: This stack uses containerized tools exclusively, so no host dependencies like `ip` or `sudo` are required. All networking operations run inside the OVS container, making it truly cross-platform.

### Architecture Overview

The stack consists of the following containerized components organized with Docker Compose profiles:

#### Core Monitoring Stack (default profile)
- **OVS Container**: Runs Open vSwitch in userspace datapath mode with pre-configured bridge (ovs-br0)
- **OVS Exporter**: Collects and exposes OVS interface metrics (packets, bytes, errors, drops)
- **Prometheus**: Time-series database for metrics collection and storage
- **Grafana**: Visualization platform with 4 comprehensive OVS dashboards
- **Node Exporter**: Host system metrics (CPU, memory, disk, network)
- **cAdvisor**: Container resource usage and performance metrics

#### Test Containers (testing profile)
- **Test Containers (1-3)**: Alpine Linux containers with network listeners
- Pre-configured to connect to OVS bridge at 172.18.0.10-12
- Used as traffic targets for testing and demonstration

#### Professional Traffic Generation (traffic profile)
- **Traffic Generator**: Ubuntu-based container with professional tools:
  - **hping3**: TCP/UDP/ICMP flood attacks and packet crafting
  - **iperf3**: Bandwidth and performance testing
  - **netperf**: Network benchmarking
  - **Python Scapy**: Custom traffic pattern generation
- Capable of generating 200,000+ packets per second
- Multiple attack patterns: SYN floods, UDP floods, ICMP floods, fragmented packets, ARP storms

#### Chaos Engineering (chaos profile)
- **Pumba**: Network chaos engineering tool for:
  - Packet loss (10-80%)
  - Network latency (50-1000ms)
  - Bandwidth limiting (25kbps-1Mbps)
  - Packet corruption (5-20%)
  - CPU/Memory stress testing

All components run in containers and communicate via OVS bridge or Docker networks. Test containers and traffic generators are connected to the OVS bridge (172.18.0.x network) to ensure all traffic flows through OVS for monitoring.

### Makefile Commands

The project includes a comprehensive Makefile to simplify operations:

```bash
# Core operations
make up                  # Start monitoring stack
make down                # Stop all containers
make restart             # Restart all services
make status              # Show container status

# Demo operations
make demo                # Run quick 10-minute demo
make demo-full           # Run full 30-minute demo
make demo-status         # Check demo status
make demo-stop           # Stop demo components

# Traffic generation
make traffic-high        # Start high-intensity traffic (200k+ pps)
make traffic-low         # Start low-intensity traffic (10k pps)
make traffic-stop        # Stop traffic generation

# Chaos engineering
make chaos SCENARIO=packet-loss-30 DURATION=120  # Run chaos scenario
make chaos-stop          # Stop all chaos scenarios

# Utilities
make build               # Build all custom images
make clean               # Clean up everything
make dashboard           # Open Grafana dashboards
make metrics             # Show current OVS metrics
```

### Docker Compose Profiles

The stack uses Docker Compose profiles to organize components by functionality:

```bash
# Core monitoring only (default)
docker compose up -d

# Add test containers for network simulation
docker compose --profile testing up -d

# Add professional traffic generator
docker compose --profile traffic up -d

# Add high-volume nping traffic generators
docker compose --profile traffic up -d

# Add chaos engineering capabilities
docker compose --profile chaos up -d

# Full stack with all capabilities
docker compose --profile testing --profile traffic --profile chaos up -d
```

### Getting Started

#### 1. Start the Stack

```bash
# Build custom images and start all services
docker-compose up -d --build

# Verify all containers are running
docker-compose ps

# Check logs if needed
docker-compose logs -f ovs
```

#### 2. Verify OVS is Running

```bash
# Check OVS bridge status
docker exec ovs ovs-vsctl show

# Check OVS flows
docker exec ovs ovs-ofctl -O OpenFlow13 dump-flows ovs-br0
```

#### 3. Connect Containers to OVS

The stack includes helper scripts to connect containers to the OVS bridge:

```bash
# Create a container without network
docker run -d --name myapp --net=none nginx:alpine

# Connect it to OVS with a specific IP
./scripts/ovs-docker-connect.sh myapp 172.18.0.20

# Verify connectivity
docker exec myapp ping -c 3 172.18.0.1  # Gateway
docker exec myapp ip addr show eth1      # Check interface
```

#### 4. Access Monitoring Dashboards

- **Prometheus**: http://localhost:9090
  - Check Targets: http://localhost:9090/targets
  - All targets should show as "UP"

- **Grafana**: http://localhost:3000
  - Default credentials: admin/admin
  - 5 Pre-configured dashboards (see Monitoring Dashboards section above)

### Network Simulation & Chaos Testing

This stack includes comprehensive network simulation capabilities for testing OVS underlay failure detection:

#### Automated Test Container Management

```bash
# Set up 3 test containers with automatic OVS connectivity and network services
./scripts/network-simulation/container-setup.sh setup

# Check status of test containers and OVS connections
./scripts/network-simulation/container-setup.sh status

# Test connectivity between containers through OVS bridge
./scripts/network-simulation/container-setup.sh test-connectivity

# Clean up all test containers
./scripts/network-simulation/container-setup.sh teardown

# Reset: teardown and setup fresh containers
./scripts/network-simulation/container-setup.sh reset
```

#### Professional Traffic Generation

The stack includes a professional traffic generator capable of 200,000+ pps:

```bash
# Quick start with Make commands
make traffic-high    # Start high-intensity traffic (200k+ pps)
make traffic-low     # Start low-intensity traffic (10k pps)
make traffic-stop    # Stop traffic generation

# Or use the demo script
./scripts/network-simulation/demo.sh traffic-only high

# Monitor traffic in real-time
curl -s http://localhost:9475/metrics | grep "ovs_interface_.*_packets"
```

The traffic generator uses:
- **hping3** for flood attacks (TCP SYN, UDP, ICMP)
- **iperf3** for bandwidth testing
- **Python Scapy** for complex traffic patterns

#### Chaos Engineering Scenarios

```bash
# Available chaos scenario types:
./scripts/network-simulation/dashboard-demo.sh custom <scenario> [duration] [interface]

# Packet loss scenarios (dramatic TX/RX ratio changes)
./scripts/network-simulation/dashboard-demo.sh custom packet-loss-20 120 eth0     # 20% loss
./scripts/network-simulation/dashboard-demo.sh custom packet-loss-40 120 eth0     # 40% loss

# Packet corruption scenarios (physical layer errors)
./scripts/network-simulation/dashboard-demo.sh custom corruption-5 120 ovs-br0    # 5% corruption
./scripts/network-simulation/dashboard-demo.sh custom corruption-10 120 eth0      # 10% corruption

# Bandwidth throttling scenarios (sustained stress)
./scripts/network-simulation/dashboard-demo.sh custom bandwidth-200 120 ovs-br0   # 200kbps limit
./scripts/network-simulation/dashboard-demo.sh custom bandwidth-500 120 eth0      # 500kbps limit

# Network latency scenarios
./scripts/network-simulation/dashboard-demo.sh custom latency-300 120 eth0        # 300ms latency

# Full demonstration (20 minutes of orchestrated scenarios)
./scripts/network-simulation/dashboard-demo.sh demo
./scripts/network-simulation/dashboard-demo.sh quick-demo                         # 8 minutes

# Monitor results in real-time
# Dashboard: http://localhost:3000/d/ovs-underlay-failure/ovs-underlay-failure-detection
```

#### Manual Container Network Management

For custom container setups beyond the automated test environment:

```bash
# Basic usage
./scripts/ovs-docker-connect.sh <container_name> <ip_address>

# Example: Connect multiple containers
docker run -d --name web1 --net=none nginx:alpine
docker run -d --name web2 --net=none nginx:alpine
docker run -d --name db1 --net=none postgres:alpine

./scripts/ovs-docker-connect.sh web1 172.18.0.10
./scripts/ovs-docker-connect.sh web2 172.18.0.11
./scripts/ovs-docker-connect.sh db1 172.18.0.20

# Test connectivity
docker exec web1 ping -c 3 172.18.0.11
docker exec web1 ping -c 3 172.18.0.20
```

#### Disconnecting Containers

```bash
./scripts/ovs-docker-disconnect.sh <container_name>

# Example
./scripts/ovs-docker-disconnect.sh web1
```

### Available Metrics

The OVS exporter (v2.2.0) provides comprehensive metrics across multiple categories:

#### Core OVS Metrics
- `ovs_up` - OVS service status (1 = up, 0 = down)
- `ovs_interface_*` - Interface statistics (rx/tx bytes, packets, errors, drops)
- `ovs_interface_link_state` - Link up/down status
- `ovs_interface_admin_state` - Administrative state
- `ovs_interface_mtu` - Maximum transmission unit
- `ovs_interface_link_speed` - Interface speed in Mbps

#### Datapath Flow Metrics
- `ovs_dp_flows` - Number of active flows in datapath
- `ovs_dp_lookups_hit` - Successful flow cache lookups
- `ovs_dp_lookups_missed` - Flow cache misses requiring upcall
- `ovs_dp_lookups_lost` - Packets lost before reaching userspace
- `ovs_dp_masks_hit` - Total masks visited for packet matching
- `ovs_dp_masks_hit_ratio` - Average masks per packet (efficiency metric)
- `ovs_dp_masks_total` - Total number of masks in datapath

#### Coverage Statistics
- `ovs_coverage_avg` - Event rate averages (5s, 5m, 1h intervals)
- `ovs_coverage_total` - Total count of specific events including:
  - `drop_action_of_pipeline` - Packets dropped by OpenFlow pipeline
  - `dpif_execute_error` - Datapath interface execution errors
  - `dpif_flow_put_error` - Flow installation failures
  - Various other operational events

#### System Resource Metrics
- `ovs_memory_usage` - Memory consumption by facility
- `ovs_log_file_size` - Log file sizes in bytes
- `ovs_pid` - Process IDs for OVS components
- `ovs_network_port` - Network ports used by OVS services

#### Interface Error Details
- `ovs_interface_rx_crc_err` - CRC errors on receive
- `ovs_interface_rx_frame_err` - Framing errors
- `ovs_interface_rx_over_err` - Buffer overrun errors
- `ovs_interface_rx_missed_errors` - Missed packet errors
- `ovs_interface_collisions` - Packet collisions

#### Docker Container Metrics
- `docker_cpu_usage_percent` - CPU usage percentage per container
- `docker_memory_usage_bytes` - Memory usage in bytes
- `docker_memory_usage_percent` - Memory usage percentage
- `docker_network_rx_bytes` - Network bytes received
- `docker_network_tx_bytes` - Network bytes transmitted

#### System Metrics (via Node Exporter)
- `node_cpu_seconds_total` - CPU usage
- `node_memory_MemAvailable_bytes` - Available memory
- `node_network_receive_bytes_total` - Network interface statistics
- `node_disk_io_time_seconds_total` - Disk I/O metrics

### Managing the Stack

```bash
# Stop all services
docker-compose stop

# Start all services
docker-compose start

# Restart a specific service
docker-compose restart ovs

# View logs for a specific service
docker-compose logs -f ovs_exporter

# Rebuild a specific service
docker-compose build ovs
docker-compose up -d ovs

# Complete cleanup (including volumes)
docker-compose down -v

# Update all images
docker-compose pull
docker-compose up -d
```

### Advanced OVS Operations

```bash
# Add custom flows
docker exec ovs ovs-ofctl -O OpenFlow13 add-flow ovs-br0 \
  "priority=100,ip,nw_src=172.18.0.10,nw_dst=172.18.0.11,actions=normal"

# Monitor traffic
docker exec ovs ovs-ofctl -O OpenFlow13 dump-flows ovs-br0
docker exec ovs ovs-ofctl -O OpenFlow13 dump-ports ovs-br0

# Show port statistics
docker exec ovs ovs-vsctl list interface

# Add VLAN tagging
docker exec ovs ovs-vsctl add-port ovs-br0 vlan100 tag=100 \
  -- set interface vlan100 type=internal
```

### Troubleshooting

#### Containers Can't Communicate
```bash
# Check OVS bridge status
docker exec ovs ovs-vsctl show

# Verify interfaces are attached
docker exec ovs ovs-vsctl list-ports ovs-br0

# Check flows
docker exec ovs ovs-ofctl -O OpenFlow13 dump-flows ovs-br0

# Verify container has correct IP
docker exec <container> ip addr show eth1
```

#### Grafana Shows "OVS Status: 0"
```bash
# Check if OVS container is running
docker-compose ps ovs

# Check OVS exporter logs
docker-compose logs ovs_exporter

# Verify metrics endpoint
curl http://localhost:9475/metrics | grep ovs_up

# Restart OVS exporter
docker-compose restart ovs_exporter
```

#### Prometheus Can't Scrape Targets
```bash
# Check Prometheus configuration
docker-compose exec prometheus cat /etc/prometheus/prometheus.yml

# Check target status
curl http://localhost:9090/api/v1/targets

# Verify network connectivity
docker-compose exec prometheus wget -O- http://host.docker.internal:9475/metrics
```

#### General Debugging
```bash
# Check all container logs
docker-compose logs

# Check specific service
docker-compose logs -f --tail=50 ovs

# Inspect network configuration
docker network ls
docker network inspect monitoring-stack_default

# Check volumes
docker volume ls
docker volume inspect monitoring-stack_ovs-run
```

### Customization

#### Adding Custom Dashboards
1. Create new dashboard JSON in `grafana/dashboards/`
2. Restart Grafana: `docker-compose restart grafana`

#### Modifying OVS Configuration
Edit `ovs-container/start-ovs.sh` to customize:
- Bridge name
- IP ranges
- OpenFlow versions
- Additional bridges or ports

#### Adjusting Metrics Collection
Edit `prometheus.yml` to:
- Change scrape intervals
- Add new targets
- Configure alerts

### Performance Considerations

- The OVS container runs with `network_mode: host` for optimal performance
- Prometheus stores data in a Docker volume for persistence
- Consider adding resource limits in `docker-compose.yml` for production use:

```yaml
services:
  prometheus:
    mem_limit: 2g
    cpus: '1.0'
```

### Security Notes

- The OVS container runs in privileged mode to manage network interfaces
- Change default Grafana password in production
- Consider adding authentication to Prometheus endpoints
- Use firewall rules to restrict access to monitoring ports

### Contributing

To add new features or exporters:
1. Create a new directory for your exporter
2. Add Dockerfile and implementation
3. Update docker-compose.yml
4. Add dashboard to Grafana
5. Update this README

### License

This project is provided as-is for testing and educational purposes.