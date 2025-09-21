# OVS Container Lab - Architecture Design

## Overview

A Software-Defined Networking (SDN) lab using Open vSwitch (OVS) data plane and Open Virtual Network (OVN) control plane, running in a Lima VM on macOS. Demonstrates enterprise multi-VPC cloud architectures with full external connectivity via NAT Gateway and comprehensive monitoring capabilities.

## Core Principles

1. **Lima VM Based** - Runs in lightweight Lima VM on macOS (Ubuntu 24.04)
2. **Direct OVN Management** - Orchestrator directly creates OVN topology (no Docker driver)
3. **Orchestrated Setup** - Python orchestrator ensures proper order of operations
4. **Multi-Tenant Support** - Full tenant/VPC isolation with external IDs
5. **Comprehensive Monitoring** - Grafana dashboards with OVN router and switch metrics
6. **Configuration-Driven** - YAML-based network configuration with multiple profiles
7. **Deterministic Operation** - Verification at each step, no arbitrary sleeps

## Architecture Components

### 1. Control Plane

#### OVN Central (`ovn-central` container)
- **Role**: SDN control plane for entire deployment
- **Components**:
  - `ovn-northd`: Translates logical network to flow rules
  - `ovsdb-server` (North): Stores logical network configuration
  - `ovsdb-server` (South): Stores physical network bindings
  - `ovn-exporter`: Prometheus exporter for OVN metrics (v2.2.0 with router metrics)
- **Exposed Ports**:
  - 6641: OVN Northbound DB
  - 6642: OVN Southbound DB
  - 9476: OVN exporter metrics
  - 6081: OVS DB
- **Note**: Docker overlay driver is included but disabled (ENABLE_DOCKER_DRIVER=false)
  - Containers connected directly via orchestrator.py
  - Uses ovs-docker.sh scripts for veth pair creation

### 2. Data Plane

#### OVS Instance (Lima VM Host)
- **Role**: Single OVS instance managing all containers
- **Components**:
  - `ovs-vswitchd`: Kernel datapath
  - `ovsdb-server`: Local OVS configuration
  - `ovn-controller`: Connects to OVN central
  - Bridge `br-int`: OVN integration bridge
- **Configuration**:
  - Acts as OVN chassis "lima-chassis"
  - Container connections via veth pairs (created by ovs-docker.sh)
  - External IDs for tenant/VPC tracking
  - OpenFlow rules programmed by OVN

#### NAT Gateway Container
- **Role**: Provides external internet connectivity for all VPCs
- **Components**:
  - Ubuntu 22.04 base with FRR installed (but not used)
  - iptables for NAT/MASQUERADE functionality
  - Connected to OVN transit network via orchestrator
- **Configuration**:
  - IP: 192.168.100.254 on transit network
  - NAT rules for VPC subnets (10.0.0.0/16, 10.1.0.0/16)
  - Static routes to VPC networks via OVN gateway (192.168.100.1)
  - Connected via bind_container_to_ovn() in orchestrator

### 3. Logical Network Architecture

```
┌──────────────────────────────────────────────────┐
│              OVN Northbound DB                   │
├──────────────────────────────────────────────────┤
│                                                  │
│     ┌─────────────────────────────┐             │
│     │    NAT Gateway Container    │             │  ← External Connectivity
│     │   192.168.100.254 (eth1)    │             │
│     │   iptables MASQUERADE       │             │
│     └──────────┬──────────────────┘             │
│                │                                 │
│  ┌─────────────▼─────────────────┐              │
│  │  Logical Switch: ls-transit    │              │  ← Transit Network
│  │     192.168.100.0/24          │              │
│  └──┬──────────┬──────────┬──────┘              │
│     │          │          │                      │
│  ┌──▼────┐ ┌──▼──────┐ ┌▼───────┐              │
│  │lr-gateway│ │lr-vpc-a │ │lr-vpc-b│              │  ← Logical Routers
│  │Transit GW│ │Tenant-1 │ │Tenant-2│              │
│  └───────┘ └─┬──┬──┬─┘ └┬──┬──┬─┘              │
│              │  │  │  │   │  │  │  │             │
│           ┌──▼┐ │ ┌▼─┐┌──▼┐ │ ┌▼─┐┌▼──┐        │
│           │Web│ │ │App│Test│ │ │App│Test│        │  ← Logical Switches
│           └───┘ │ └──┘└────┘ │ └──┘└────┘        │
│                 │             │                   │
│               ┌─▼┐          ┌▼─┐                │
│               │DB│          │DB│                 │
│               └──┘          └──┘                 │
└──────────────────────────────────────────────────┘
```

### 4. Physical Network Topology

```
Lima VM (Ubuntu 24.04)
│
├── OVS Bridge: br-int (OVN Integration Bridge)
│   ├── Container veth pairs (created by ovs-docker.sh)
│   ├── NAT Gateway eth1 interface
│   └── OpenFlow rules (programmed by ovn-controller)
│
├── Container Networks (via OVN port binding)
│   ├── VPC-A Containers
│   │   ├── vpc-a-web (10.0.1.10/24)
│   │   ├── vpc-a-app (10.0.2.10/24)
│   │   ├── vpc-a-db (10.0.3.10/24)
│   │   └── traffic-gen-a (10.0.4.10/24)
│   └── VPC-B Containers
│       ├── vpc-b-web (10.1.1.10/24)
│       ├── vpc-b-app (10.1.2.10/24)
│       ├── vpc-b-db (10.1.3.10/24)
│       └── traffic-gen-b (10.1.4.10/24)
│
└── Special Containers
    ├── nat-gateway (192.168.100.254)
    ├── prometheus (monitoring)
    └── grafana (dashboards)
```

## Network Flows

### Intra-VPC Communication
1. Container sends packet to OVS bridge via veth pair
2. OVN controller applies OpenFlow rules
3. Packet forwarded directly within VPC
4. No routing required for same subnet

### Inter-VPC Communication
1. Container in VPC-A sends packet to VPC-B
2. Packet hits OVN logical router lr-vpc-a
3. Routed through lr-gateway to lr-vpc-b
4. Delivered to destination container
5. All routing done in OpenFlow, no tunneling in single-host setup

### External Communication (Internet)
1. Container sends packet to internet (e.g., 8.8.8.8)
2. Packet routed: lr-vpc-a → lr-gateway → ls-transit
3. Delivered to NAT Gateway container (192.168.100.254)
4. NAT Gateway performs iptables MASQUERADE
5. Packet exits via container's default route
6. Return traffic follows reverse path with NAT translation

## Container Network Integration

### Direct OVN Binding (No Docker Driver)

Containers are connected directly to OVN using the orchestrator:

```python
# orchestrator.py flow:
1. Start containers with network_mode: none
2. Verify containers are running
3. Setup OVN logical topology (routers, switches, ports)
4. Bind containers to OVN ports:
   - Uses ovs-docker add-port to create veth pairs
   - Assigns IP and MAC addresses from configuration
   - Sets external IDs for tenant/VPC tracking
```

### Container Connection Process

```bash
# How orchestrator connects a container:
1. /scripts/ovs-docker.sh add-port br-int eth1 <container> --ipaddress=10.0.1.10/24
2. ovn-nbctl lsp-add ls-vpc-a-web <port-name>
3. ovn-nbctl lsp-set-addresses <port-name> "02:00:00:01:01:0a 10.0.1.10"
4. ovs-vsctl set Interface <iface> external-ids:container=<name>
5. ovs-vsctl set Interface <iface> external-ids:tenant-id=<tenant>
6. ovs-vsctl set Interface <iface> external-ids:vpc-id=<vpc>
```

## Monitoring Stack

### Metrics Collection
- **Prometheus**: Central metrics collection (port 9090)
- **OVS Exporter**: Bridge and interface metrics (port 9475)
- **OVN Exporter**: Logical router/switch metrics (port 9476)
- **Node Exporter**: System metrics (port 9100)
- **cAdvisor**: Container metrics (port 8080)

### Dashboards (Grafana - port 3000)
- **Network Topology Performance**: Complete view of all network components
  - Interface traffic by tenant/VPC/container
  - Packet drops and errors with multi-level grouping
  - OVS bridge performance and datapath flows
  - OVN logical routers and switches with external IDs
  - NAT rules, routing policies, and load balancers
  - System overview with aggregate metrics
- **OVS Underlay Failure Detection**: Network health monitoring
- Additional dashboards for system resources and flow analysis

## Test Container Architecture

### Automatic Container Deployment

When `make up` is executed, the orchestrator automatically:

1. **Starts Containers First** (critical for proper flow installation):
   - All containers started with `network_mode: none`
   - Ensures containers exist before OVN topology creation
   - Verifies all containers are running

2. **Creates OVN Logical Topology**:
   - Logical routers: lr-gateway, lr-vpc-a, lr-vpc-b
   - Logical switches per tier:
     - `ls-vpc-a-web` (10.0.1.0/24) - VPC-A web tier
     - `ls-vpc-a-app` (10.0.2.0/24) - VPC-A application tier
     - `ls-vpc-a-db` (10.0.3.0/24) - VPC-A database tier
     - `ls-vpc-a-test` (10.0.4.0/24) - VPC-A test tier
     - Similar for VPC-B with 10.1.x.0/24 subnets
   - Transit network: ls-transit (192.168.100.0/24)

3. **Binds Containers to OVN**:
   - Creates veth pairs using ovs-docker.sh
   - Assigns IPs and MACs from network-config.yaml
   - Sets external IDs for multi-tenant monitoring
   - Verifies connectivity before proceeding

### Container Distribution

```
VPC-A (Tenant-1):
├── vpc-a-web (Web tier - 10.0.1.10)
├── vpc-a-app (App tier - 10.0.2.10)
├── vpc-a-db (Database tier - 10.0.3.10)
└── traffic-gen-a (Traffic generation - 10.0.4.10)

VPC-B (Tenant-2):
├── vpc-b-web (Web tier - 10.1.1.10)
├── vpc-b-app (App tier - 10.1.2.10)
├── vpc-b-db (Database tier - 10.1.3.10)
└── traffic-gen-b (Traffic generation - 10.1.4.10)

Special:
└── nat-gateway (Transit network - 192.168.100.254)
```

## Automation Architecture

### Orchestrator Design

```
orchestrator.py                  # Main orchestration with proper ordering
├── OVNManager                  # OVN topology and container management
│   ├── setup_topology()        # Creates logical routers/switches
│   ├── bind_container_to_ovn() # Connects containers via veth pairs
│   └── verify_connectivity()   # Tests network paths
├── MonitoringManager           # Exporter setup and verification
│   ├── setup_ovs_exporter()    # OVS metrics
│   └── setup_ovn_exporter()    # OVN metrics (in container)
├── TestRunner                  # Connectivity and verification testing
└── ChaosEngineer              # Network chaos scenarios

# Configuration now handled directly in docker-compose files:
# - VPC topology and OVN switches/routers defined in docker-compose.yml
# - Container networking managed by Docker and OVS plugin
# - No separate configuration files needed
```

### Makefile Targets

```makefile
# Core Operations
make up          # Complete setup with orchestration and verification
make down        # Stop containers (VM stays running)
make clean       # Delete VM and everything
make status      # Show VM, container, and OVS/OVN status
make check       # Run comprehensive network diagnostics

# Traffic & Testing
make test        # Run connectivity tests
make traffic-run # Generate normal traffic patterns
make traffic-chaos # Heavy traffic + network failures (5 min)
make traffic-stop # Stop all traffic generation

# Chaos Engineering
make chaos-loss  # Simulate 30% packet loss (1 min)
make chaos-delay # Add 100ms network delay (1 min)
make chaos-bandwidth # Limit bandwidth to 1mbit (1 min)
make chaos-partition # Create network partition (30s)

# Access
make shell-vm    # SSH into Lima VM
make dashboard   # Open Grafana (http://localhost:3000)
make logs        # Follow container logs
```

## Implementation Status

### Completed ✅
- [x] Lima VM integration for macOS (Ubuntu 24.04)
- [x] OVS/OVN setup with proper chassis configuration
- [x] Multi-VPC topology with OVN logical routers and switches
- [x] External connectivity via NAT Gateway (iptables MASQUERADE)
- [x] Python orchestrator with proper order of operations
- [x] Error handling that stops on failure (no "continuing when broken")
- [x] YAML-based network configuration system
- [x] Comprehensive monitoring with Grafana dashboards
- [x] OVN exporter v2.2.0 with router metrics
- [x] Multi-tenant support with external IDs
- [x] Traffic generation containers
- [x] Chaos engineering capabilities
- [x] Full connectivity verification (internal + external)
- [x] Deterministic setup without arbitrary sleeps
- [x] Container binding via ovs-docker.sh scripts

### Production Ready 🚀
- Full multi-VPC connectivity with tenant isolation
- External internet access for all containers
- Comprehensive monitoring and observability
- Traffic generation and chaos testing
- Configuration-driven deployment
- Proper error handling and verification

### Architecture Highlights
- **No Docker Driver Needed**: Direct OVN management via orchestrator
- **Proper Orchestration**: Containers created before OVN topology
- **Verification at Each Step**: Fails fast on errors
- **Multi-Tenant Isolation**: Using OVN external IDs
- **Complete Monitoring**: All components visible in Grafana

### Future Enhancements 📋
- [ ] Multi-host federation with GENEVE tunnels
- [ ] OVN clustering for HA
- [ ] Kubernetes CNI integration
- [ ] Load balancing via OVN
- [ ] Advanced QoS and traffic shaping
- [ ] IPsec encryption for GENEVE tunnels
- [ ] FRR integration for BGP/OSPF routing

## Configuration System

### Network Configuration Files
- `network-config.yaml` - Default production-like configuration
- `network-config-simple.yaml` - Single-host development setup
- Custom configurations supported via NETWORK_CONFIG environment variable

### Configuration Structure
```yaml
hosts:           # Future multi-host support
vpcs:            # VPC definitions with subnets
containers:      # Container placement and IPs
ovn_cluster:     # Future OVN clustering config
```

## Security Considerations

### Container Isolation
- Containers start with `network_mode: none`
- Connected to OVN networks only via orchestrator
- No direct bridge access

### Control Plane Security
- OVN DBs can use SSL/TLS (future)
- RBAC for network operations (future)
- Audit logging available

### Data Plane Security
- OpenFlow rules provide isolation
- External IDs enable policy enforcement
- Future: GENEVE encryption with IPsec

## Performance Optimization

### Current Setup
- Kernel datapath for stability
- Single OVN chassis for simplicity
- Monitoring overhead minimal

### Scaling Considerations
- Single OVN central supports ~1000 chassis
- Future: Distributed gateways for HA
- Flow caching reduces controller load

## Troubleshooting

### Common Issues

1. **Containers can't communicate**
   - Check OVN logical topology: `sudo docker exec ovn-central ovn-nbctl show`
   - Verify port bindings: `sudo ovs-vsctl show`
   - Check OpenFlow rules: `sudo ovs-ofctl dump-flows br-int`

2. **Container connectivity issues**
   - Check container binding: `sudo ovs-vsctl show`
   - Verify OVN port: `sudo docker exec ovn-central ovn-nbctl show`
   - Check veth pairs: `ip link show | grep veth`

3. **External connectivity broken**
   - Check NAT gateway: `docker logs nat-gateway`
   - Verify NAT rules: `docker exec nat-gateway iptables -t nat -L -n`
   - Check routes: `docker exec nat-gateway ip route`

### Debug Commands

```bash
# OVN logical view
sudo docker exec ovn-central ovn-nbctl show

# Physical bindings
sudo docker exec ovn-central ovn-sbctl show

# OVS bridges and ports
sudo ovs-vsctl show

# OpenFlow rules
sudo ovs-ofctl dump-flows br-int

# Container network namespaces
sudo docker exec <container> ip addr show
```

---

**Status**: Production Ready
**Latest Updates**:
- OVN exporter v2.2.0 with router metrics
- Comprehensive Network Topology Performance dashboard
- Proper orchestration with error handling
- Full external connectivity via NAT Gateway