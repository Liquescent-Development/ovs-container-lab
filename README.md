# OVS Container Lab

**A Software-Defined Networking (SDN) lab** using Open vSwitch (OVS) data plane and Open Virtual Network (OVN) control plane, running in a Lima VM. Demonstrates enterprise multi-VPC cloud architectures with proper SDN - **no Linux iptables or routing**, everything is controlled by OVN.

## Why Lima?

Docker Desktop on macOS runs containers inside a VM, preventing direct network namespace manipulation. Lima provides:
- ✅ **Lightweight** - Uses macOS native Virtualization.framework (no VirtualBox)
- ✅ **Fast** - Much better performance than VirtualBox
- ✅ **Full Linux kernel** with OVS kernel modules
- ✅ **Direct network namespace access**
- ✅ **Real veth pair creation** and manipulation
- ✅ **Native container-to-OVS bridge** attachment
- ✅ **Control everything from your Mac** via Make

## Quick Start

```bash
# Install Lima (lightweight VM for macOS)
brew install lima

# Start everything (VM + containers)
make up
# First time: Lima will prompt you to confirm VM creation
# Select "Proceed with the current configuration" and press Enter
# Initial setup takes ~5 minutes to download Ubuntu and install everything

# Check status
make status

# Test connectivity
make test

# Access Grafana from your Mac
open http://localhost:3000

# SSH into VM if needed
make lima-ssh

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
│  │   OVS    │  │    OVS     │  │   OVS    │            │
│  │  VPC-A   │◄─┤  br-int    ├─►│  VPC-B   │            │
│  └──────────┘  └────────────┘  └──────────┘            │
│                                                          │
│  ┌──────────────────────────────────────────────────┐  │
│  │         Docker Containers (network=none)          │  │
│  │   Attached to OVS via veth pairs and namespaces   │  │
│  └──────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

## Core Commands (Run from macOS)

| Command | Description |
|---------|------------|
| `make up` | Start Lima VM and entire stack |
| `make down` | Stop containers (VM stays running) |
| `make status` | Show VM and container status |
| `make test` | Run connectivity tests |
| `make clean` | Delete VM and everything |

## Lima VM Control

| Command | Description |
|---------|------------|
| `make lima-start` | Start/create the Lima VM |
| `make lima-ssh` | SSH into the Lima VM |
| `make lima-stop` | Stop the Lima VM |
| `make lima-delete` | Delete the Lima VM |
| `make install-lima` | Install Lima via Homebrew |

## Container Networking

| Command | Description |
|---------|------------|
| `make attach` | Attach test containers to OVS |
| `make test-ping` | Test container connectivity |
| `make test-ovn` | Show OVN configuration |

## Monitoring (Accessible from macOS)

| Service | URL | Credentials |
|---------|-----|-------------|
| Grafana | http://localhost:3000 | admin/admin |
| Prometheus | http://localhost:9090 | - |
| OVS Metrics | http://localhost:9475 | - |

## Development

```bash
# Get a shell in the VM
make lima-ssh

# Inside the VM
cd ~/code/ovs-container-lab

# Attach a container manually
sudo ovs-docker add-port ovs-br0 eth1 my-container

# Or use the standard OVS tools
sudo ovs-vsctl show
sudo ovs-ofctl dump-flows ovs-br0

# Shell into containers from Mac
make shell-ovn
make shell-ovs
```

## How It Works (SDN Architecture)

1. **OVN Control Plane**: Defines logical network topology (routers, switches, ports)
2. **OVS Data Plane**: Executes OpenFlow rules programmed by OVN controller
3. **No Linux Routing**: All packet forwarding via OVS flow tables, not iptables
4. **GENEVE Tunnels**: Automatic overlay networking between VPCs
5. **Container Integration**: Each container bound to an OVN logical switch port
6. **Automated Setup**: `orchestrator.py` handles all OVN/OVS configuration

## Prerequisites

- macOS 11+ (Big Sur or later)
- Lima (`brew install lima`)
- 4GB RAM available for VM
- 10GB disk space

## Project Structure

```
ovs-container-lab/
├── lima.yaml           # Lima VM configuration
├── Makefile            # Control from macOS
├── docker-compose.yml  # Container stack
├── scripts/
│   ├── attach-containers.sh  # Container-to-OVS attachment
│   └── test-connectivity.sh   # Connectivity tests
├── ovs-container/      # OVS container config
├── ovn-container/      # OVN controller config
├── grafana/            # Monitoring dashboards
└── prometheus.yml      # Metrics configuration
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
# Inside VM
docker exec vpc-a-web iperf3 -s &
docker exec vpc-b-web iperf3 -c 10.0.1.10
```

### Packet Capture
```bash
make lima-ssh
sudo tcpdump -i ovs-br0 -w capture.pcap
```

## Lima vs Other Solutions

| Feature | Docker Desktop | VirtualBox+Vagrant | Lima |
|---------|---------------|--------------------|------|
| Performance | ❌ Slow | ❌ Heavy | ✅ Fast native |
| Resource Usage | ❌ High | ❌ Very High | ✅ Lightweight |
| macOS Integration | ⚠️ Limited | ❌ Poor | ✅ Excellent |
| Network namespaces | ❌ Hidden | ✅ Full access | ✅ Full access |
| Veth pairs | ❌ Can't create | ✅ Works | ✅ Works |
| OVS kernel module | ❌ Not available | ✅ Available | ✅ Available |
| Setup complexity | ✅ Simple | ❌ Complex | ✅ Simple |

## Why Lima is Better

1. **Native Performance**: Uses Apple's Virtualization.framework
2. **Lightweight**: No VirtualBox overhead
3. **Fast Boot**: VM starts in seconds
4. **Automatic File Sharing**: SSHFS mounts work seamlessly
5. **Built for macOS**: Designed specifically for Mac users
6. **Simple CLI**: Clean, easy-to-use commands

## License

MIT License - See LICENSE file for details