# OVS Container Lab

**A Software-Defined Networking (SDN) lab** using Open vSwitch (OVS) data plane and Open Virtual Network (OVN) control plane, running in a Lima VM. Demonstrates enterprise multi-VPC cloud architectures with full external connectivity - **complete SDN implementation** with NAT Gateway for internet access.

## Quick Start

```bash
# Install Lima (lightweight VM for macOS)
brew install lima

# Start everything (VM + containers + networking)
make up
# First time: Lima will prompt you to confirm VM creation
# Select "Proceed with the current configuration" and press Enter
# Initial setup takes ~5 minutes to download Ubuntu and install everything

# Verify everything is working
make check
# Runs comprehensive diagnostics: OVS, OVN, containers, NAT gateway

# Generate traffic
make traffic-run      # Normal traffic patterns
make traffic-chaos    # Heavy stress testing with network failures
make traffic-stop     # Stop all traffic generation

# Access Grafana from your Mac
open http://localhost:3000
# Or use: make dashboard

# Clean up everything
make clean
```

### First Time Setup

When you run `make up` for the first time, Lima will show:
```
? Creating an instance "ovs-lab"
> Proceed with the current configuration
  Open an editor to review or modify the current configuration
  Choose another template (docker, podman, archlinux, fedora, ...)
  Exit
```

**Just press Enter** to accept the default configuration. The initial setup will:
1. Download Ubuntu 22.04 (~500MB)
2. Create the VM
3. Install Docker, OVS, and OVN
4. Configure networking
5. Start all containers

This takes about 5 minutes on first run. Subsequent starts take only seconds.

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                     macOS Host                           │
│  Make commands → Lima VM → Full Linux Networking        │
│  (Native Apple Virtualization.framework - Fast!)         │
└─────────────┬───────────────────────────────────────────┘
              │ Port forwards: 3000, 9090, 9475
┌─────────────▼───────────────────────────────────────────┐
│                   Lima VM (Ubuntu)                       │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │              OVN Central (Control Plane)          │  │
│  │      • Northbound DB  • Southbound DB             │  │
│  └────────────────────┬──────────────────────────────┘  │
│                       │                                  │
│  ┌──────────┐  ┌─────▼─────┐  ┌──────────┐            │
│  │   NAT    │  │    OVS     │  │  Docker  │            │
│  │ Gateway  │◄─┤  br-int    ├─►│ Containers│           │
│  │ ↓Internet│  └────────────┘  │  (VPCs)  │            │
│  └──────────┘                   └──────────┘            │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │     VPC Networks: 10.0.0.0/16, 10.1.0.0/16       │  │
│  │     Transit: 192.168.100.0/24                     │  │
│  │     External: via NAT Gateway → Internet          │  │
│  └──────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

## Core Commands (Run from macOS)

| Command | Description |
|---------|------------|
| `make up` | Complete setup: VM, containers, OVN topology, monitoring |
| `make down` | Stop containers (VM stays running) |
| `make status` | Show VM, container, and OVS/OVN status |
| `make check` | Run comprehensive network diagnostics |
| `make test` | Run connectivity tests between containers |
| `make clean` | Delete VM and everything |

## Traffic Generation & Chaos Engineering

| Command | Description |
|---------|------------|
| `make traffic-run` | Generate normal traffic patterns |
| `make traffic-chaos` | Heavy traffic + network failures (5 min) |
| `make traffic-stop` | Stop all traffic generation |
| `make chaos-loss` | Simulate 30% packet loss (1 min) |
| `make chaos-delay` | Add 100ms network delay (1 min) |
| `make chaos-bandwidth` | Limit bandwidth to 1mbit (1 min) |
| `make chaos-partition` | Create network partition (30s) |
| `make chaos-corruption` | Introduce packet corruption (1 min) |
| `make chaos-duplication` | Introduce packet duplication (1 min) |

## Configuration

The lab supports multiple network configurations via YAML files:

```bash
# Use default configuration (network-config.yaml)
make up

# Use a specific configuration
NETWORK_CONFIG=network-config-simple.yaml make up
NETWORK_CONFIG=network-config-multihost.yaml make up
```

### Configuration Files

- `network-config.yaml` - Default production-like config
- `network-config-simple.yaml` - Single-host development setup
- Custom configs can define:
  - Multiple hosts and chassis
  - VPC topologies and subnets
  - Container placement and IPs
  - Persistent MAC addresses
  - OVN clustering for HA

## Network Diagnostics

The `make check` command runs comprehensive diagnostics:

**OVS Bridge Status**:
- Bridge existence and port count
- Interface ID verification

**OVN Logical Configuration**:
- Logical routers and switches
- NAT gateway configuration

**OVN Port Bindings**:
- All ports bound to chassis
- Proper MAC address assignment

**Container Connectivity**:
- Gateway reachability
- ARP resolution

**NAT Gateway Status**:
- Container running
- MASQUERADE rules
- External connectivity

## Orchestrator Commands

The orchestrator (`orchestrator.py`) provides fine-grained control:

```bash
# Run from inside the VM (make shell-vm)
cd ~/code/ovs-container-lab

# Complete setup with proper ordering
sudo python3 orchestrator.py up

# Individual operations
sudo python3 orchestrator.py setup              # Create OVN topology
sudo python3 orchestrator.py setup-chassis      # Configure OVS chassis
sudo python3 orchestrator.py bind-containers    # Bind containers to OVN
sudo python3 orchestrator.py reconcile          # Fix broken connections

# Diagnostics
sudo python3 orchestrator.py check              # Full diagnostics
sudo python3 orchestrator.py test               # Connectivity tests

# Chaos engineering
sudo python3 orchestrator.py chaos packet-loss --duration 60
sudo python3 orchestrator.py chaos latency --duration 60
```

## Monitoring (Accessible from macOS)

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin/admin |
| Prometheus | http://localhost:9090 | - |
| OVS Metrics | http://localhost:9475 | - |

## Development & Debugging

```bash
# Shell access
make shell-vm     # SSH into Lima VM
make shell-ovn    # Shell into OVN container
make shell-ovs    # Shell into OVS container

# Monitoring
make logs         # Follow container logs
make dashboard    # Open Grafana (http://localhost:3000)
make metrics      # Show current OVS metrics

# Inside the VM
cd ~/code/ovs-container-lab
sudo ovs-vsctl show              # OVS configuration
sudo docker exec ovn-central ovn-nbctl show  # OVN logical topology
sudo docker exec ovn-central ovn-sbctl show  # OVN physical bindings
```

## How It Works (SDN Architecture)

1. **OVN Control Plane**: Defines logical network topology (routers, switches, ports)
2. **OVS Data Plane**: Executes OpenFlow rules programmed by OVN controller
3. **NAT Gateway**: Provides external internet connectivity for all VPCs
4. **GENEVE Tunnels**: Automatic overlay networking between VPCs
5. **Container Integration**: Each container bound to an OVN logical switch port
6. **Orchestrator**: Python-based automation with proper error handling and verification

### Network Flow Types

- **Intra-VPC**: Direct routing within a VPC (e.g., web → app → db)
- **Inter-VPC**: Routed through OVN logical routers (VPC-A ↔ VPC-B)
- **External**: VPC → OVN Router → NAT Gateway → Internet

## Prerequisites

- macOS 11+ (Big Sur or later)
- Lima (`brew install lima`)
- 4GB RAM available for VM
- 10GB disk space

## Project Structure

```
ovs-container-lab/
├── lima.yaml                    # Lima VM configuration
├── Makefile                     # Simplified control commands
├── docker-compose.yml           # Container stack with profiles
├── orchestrator.py              # Main automation with error handling
├── network_config_manager.py    # Configuration parser and validator
├── network-config.yaml          # Default network topology
├── network-config-simple.yaml   # Single-host dev configuration
├── CONFIG_SYSTEM.md            # Configuration documentation
├── scripts/
│   ├── ovs-docker-*.sh         # OVS-Docker integration
│   └── network-simulation/      # Traffic and chaos tools
├── ovn-container/               # OVN control plane
├── nat-gateway/                 # External connectivity
├── traffic-generator/           # Traffic generation tools
├── grafana/                     # Monitoring dashboards
└── prometheus.yml               # Metrics configuration
```

## Troubleshooting

### VM won't start
```bash
# Check Lima VMs
limactl list

# Delete and recreate
make clean
make up
```

### "socket_vmnet" error
If you see an error about `socket_vmnet` not being installed, the VM was created but networking failed. Fix:
```bash
limactl stop ovs-lab
limactl delete ovs-lab
make up  # Will use simplified networking
```

### Containers can't connect
```bash
# Check OVS bridge in VM
make lima-ssh
sudo ovs-vsctl show

# Re-attach containers
make attach
```

### Port forwarding not working
```bash
# Check Lima status
limactl list

# Ensure services are running
make status
```

## Advanced Usage

### Custom OVS Configuration
```bash
make lima-ssh
sudo ovs-vsctl add-br br-custom
sudo ovs-vsctl set-controller br-custom tcp:127.0.0.1:6653
```

### Performance Testing
```bash
# Inside VM - test internal connectivity
docker exec vpc-a-web iperf3 -s &
docker exec vpc-b-web iperf3 -c 10.0.1.10

# Test external connectivity
docker exec vpc-a-web ping -c 5 8.8.8.8
docker exec vpc-b-web curl https://www.google.com
```

### Packet Capture
```bash
make lima-ssh
sudo tcpdump -i ovs-br0 -w capture.pcap
```

## License

MIT License - See LICENSE file for details