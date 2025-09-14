# OVS Container Lab - Architecture Design

## Overview

A fully containerized Open vSwitch (OVS) and Open Virtual Network (OVN) lab that simulates enterprise multi-VPC cloud architectures. Runs entirely in Docker with userspace datapath, requiring no kernel modules or host modifications.

## Core Principles

1. **100% Containerized** - Everything runs in Docker containers
2. **Userspace Only** - OVS userspace datapath, no kernel modules required
3. **Multi-Host Ready** - GENEVE/VXLAN overlay supports federation across hosts
4. **Docker Native** - Uses Docker's libnetwork API via OVN driver
5. **Full Automation** - Single `make up` brings up entire environment

## Architecture Components

### 1. Control Plane

#### OVN Central (`ovn-central`)
- **Role**: SDN control plane for entire deployment
- **Components**:
  - `ovn-northd`: Translates logical network to flow rules
  - `ovsdb-server` (North): Stores logical network configuration
  - `ovsdb-server` (South): Stores physical network bindings
  - `ovn-docker-overlay-driver`: Official OVN Docker network plugin (from ovn-docker package)
- **Exposed Ports**:
  - 6641: OVN Northbound DB
  - 6642: OVN Southbound DB
  - 9876: Docker network driver API (when ENABLE_DOCKER_DRIVER=true)
- **Docker Integration**:
  - Mounts `/var/run/docker.sock` for Docker API access
  - Runs official `ovn-docker-overlay-driver` from OVN project
  - Registers as `openvswitch` network driver with Docker

### 2. Data Plane

#### OVS Instances (`ovs-vpc-a`, `ovs-vpc-b`)
- **Role**: Virtual switches for each VPC
- **Components**:
  - `ovs-vswitchd`: Userspace datapath
  - `ovsdb-server`: Local OVS configuration
  - `ovn-controller`: Connects to OVN central
  - OVS Prometheus exporter (port 9475)
- **Configuration**:
  - Each acts as OVN chassis
  - GENEVE tunnels for overlay networking
  - Userspace datapath via `--disable-system` flag

### 3. Logical Network Architecture

```
┌──────────────────────────────────────────┐
│           OVN Northbound DB              │
├──────────────────────────────────────────┤
│                                          │
│  ┌────────────────────────────────┐     │
│  │    Logical Router: lr-gateway   │     │  ← External Gateway Router
│  │    - NAT: 0.0.0.0/0            │     │
│  │    - External IP: <public>      │     │
│  └──────┬──────────────┬──────────┘     │
│         │              │                 │
│  ┌──────▼──────┐ ┌────▼──────┐         │
│  │  LR-VPC-A   │ │  LR-VPC-B  │         │  ← VPC Logical Routers
│  │ 10.0.0.0/16 │ │10.1.0.0/16 │         │
│  └──┬───┬───┬──┘ └──┬───┬───┬─┘        │
│     │   │   │       │   │   │           │
│  ┌──▼─┐ │ ┌─▼──┐ ┌──▼─┐ │ ┌─▼──┐      │
│  │LS  │ │ │LS  │ │LS  │ │ │LS  │      │  ← Logical Switches
│  │Web │ │ │App │ │Web │ │ │App │      │
│  └────┘ │ └────┘ └────┘ │ └────┘      │
│         │                │              │
│       ┌─▼──┐           ┌─▼──┐          │
│       │LS  │           │LS  │          │
│       │DB  │           │DB  │          │
│       └────┘           └────┘          │
└──────────────────────────────────────────┘
```

### 4. Physical Network Topology

```
Host Machine
│
├── Docker Bridge: transit-overlay (192.168.100.0/24)
│   ├── ovn-central (192.168.100.5)
│   ├── ovs-vpc-a (192.168.100.10)
│   └── ovs-vpc-b (192.168.100.20)
│
├── GENEVE Tunnels (Overlay)
│   └── Between OVS instances for cross-VPC traffic
│
└── Container Networks (via OVN)
    ├── VPC-A Networks
    │   ├── vpc-a-web (10.0.1.0/24)
    │   ├── vpc-a-app (10.0.2.0/24)
    │   └── vpc-a-db (10.0.3.0/24)
    └── VPC-B Networks
        ├── vpc-b-web (10.1.1.0/24)
        ├── vpc-b-app (10.1.2.0/24)
        └── vpc-b-db (10.1.3.0/24)
```

## Network Flows

### Intra-VPC Communication
1. Container sends packet to OVS bridge
2. OVN controller applies flow rules
3. Packet forwarded directly within VPC
4. No tunneling required

### Inter-VPC Communication
1. Container in VPC-A sends packet to VPC-B
2. OVN logical router makes routing decision
3. Packet encapsulated in GENEVE tunnel
4. Sent via transit network to destination OVS
5. Decapsulated and delivered to container

### External Communication
1. Container sends packet to internet
2. Logical router applies SNAT
3. Packet routed through gateway router
4. NAT to external IP (if configured)

## Multi-Host Federation

### Connecting Multiple Hosts

To connect ovs-container-lab instances across hosts:

```bash
# Host 1 (Primary - runs OVN Central)
export CENTRAL_IP=10.0.1.100
docker run -d --name ovn-central \
  -p 6641:6641 -p 6642:6642 \
  ovn-central

# Host 2 (Secondary - connects to Host 1)
export CENTRAL_IP=10.0.1.100  # Host 1's IP
docker run -d --name ovs-vpc-c \
  -e OVN_REMOTE=tcp:${CENTRAL_IP}:6642 \
  -e OVN_ENCAP_IP=10.0.1.101 \
  ovs-vpc
```

### Requirements for Multi-Host
- Ports 6641, 6642 accessible between hosts
- GENEVE (UDP 6081) or VXLAN (UDP 4789) connectivity
- Unique chassis names for each OVS instance
- Shared OVN central or federated setup

## Docker Integration

### Network Driver API

The OVN Docker driver implements Docker's libnetwork API:

```python
# Driver endpoints
POST /NetworkDriver.CreateNetwork
POST /NetworkDriver.DeleteNetwork
POST /NetworkDriver.CreateEndpoint
POST /NetworkDriver.DeleteEndpoint
POST /NetworkDriver.Join
POST /NetworkDriver.Leave
```

### Usage Examples

```bash
# Create network via OVN
docker network create -d openvswitch \
  --subnet=10.2.0.0/24 \
  --gateway=10.2.0.1 \
  my-ovn-network

# Run container on OVN network
docker run -d --network my-ovn-network nginx

# Connect existing container
docker network connect my-ovn-network my-container
```

## Monitoring Stack

### Metrics Collection
- **Prometheus**: Scrapes all exporters
- **OVS Exporter**: Per-VPC metrics (ports 9475, 9477)
- **Node Exporter**: System metrics
- **cAdvisor**: Container metrics

### Dashboards (Grafana)
- Multi-VPC Overview
- Per-VPC Traffic Analysis
- Flow Table Monitoring
- Tunnel Health
- Chaos Testing Impact

## Test Container Architecture

### Automatic Container Deployment

When `make up` is executed, the system automatically:

1. **Creates Docker Networks** (via OVN driver):
   - `vpc-a-web` (10.0.1.0/24) - VPC-A web tier
   - `vpc-a-app` (10.0.2.0/24) - VPC-A application tier
   - `vpc-a-db` (10.0.3.0/24) - VPC-A database tier
   - `vpc-b-web` (10.1.1.0/24) - VPC-B web tier
   - `vpc-b-app` (10.1.2.0/24) - VPC-B application tier
   - `vpc-b-db` (10.1.3.0/24) - VPC-B database tier

2. **Deploys Test Containers**:
   - 10 Alpine-based containers (5 per VPC)
   - Distributed across different subnets
   - Pre-installed with networking tools (iperf3, tcpdump, netcat)
   - Listening on ports 80, 443, and iperf3

3. **Container Distribution**:
   ```
   VPC-A:
   ├── vpc-a-web-1, vpc-a-web-2 (Web tier)
   ├── vpc-a-app-1, vpc-a-app-2 (App tier)
   └── vpc-a-db-1 (Database tier)

   VPC-B:
   ├── vpc-b-web-1, vpc-b-web-2 (Web tier)
   ├── vpc-b-app-1, vpc-b-app-2 (App tier)
   └── vpc-b-db-1 (Database tier)
   ```

### Testing Scenarios

The test containers enable:
- **Intra-VPC routing**: Between different subnets in the same VPC
- **Inter-VPC routing**: Between VPC-A and VPC-B via OVN logical routers
- **Performance testing**: Using iperf3 for bandwidth measurements
- **Chaos engineering**: Network failure simulation
- **Traffic generation**: Using netcat listeners on various ports

## Automation Architecture

### Orchestrator Design

```
orchestrator.py            # Unified Python tool
├── OVNManager            # OVN topology and container management
├── DockerNetworkManager  # Docker network driver integration
├── TestRunner           # Connectivity testing
└── ChaosEngineer        # Chaos scenarios
```

### Simplified Makefile Targets

```makefile
make up       # Complete environment setup
make test     # Automated testing suite
make demo     # Traffic generation + chaos
make status   # Health check all components
make clean    # Full teardown
```

## Implementation Status

### Completed ✅
- [x] Basic OVS/OVN container setup
- [x] Multi-VPC network topology design with OVN logical routers
- [x] GENEVE overlay tunnels configuration
- [x] Prometheus/Grafana monitoring
- [x] Removed FRR vRouters (replaced with OVN logical routers)
- [x] OVN Docker overlay driver integration (from upstream v25.09.0 with Python 3 fixes)
- [x] Docker socket mounting for container network management
- [x] Cleaned up all shell scripts - replaced with Python orchestrator
- [x] Python orchestrator (`orchestrator.py`) for all operations
- [x] Setup verification script (`verify-setup.py`)
- [x] Docker network driver testing (`make test-driver`)
- [x] Simplified Makefile with clean targets
- [x] Fixed port conflict with macOS AirPlay (driver on port 9876)
- [x] Working OVN Docker driver API endpoints

### Ready for Testing 🧪
- OVN Docker driver API on port 9876
- OVN logical routers for inter-VPC routing
- Chaos engineering scenarios
- Multi-VPC connectivity

### Known Limitations on macOS 🍎
- Docker Desktop runs in a VM that cannot access host localhost:9876
- The OVN driver runs correctly but cannot be registered with Docker Desktop
- Workaround: Use orchestrator.py to manage OVN networks directly
- Full functionality available on Linux where driver can be properly registered

### Planned 📋
- [ ] Multi-host federation testing
- [ ] Advanced monitoring dashboards
- [ ] Performance benchmarking
- [ ] Kubernetes CNI integration
- [ ] Traffic generation patterns

## Security Considerations

### Container Isolation
- Containers use `network_mode: none` initially
- Connected to OVN networks programmatically
- No direct bridge access

### Control Plane Security
- OVN DB can use SSL/TLS
- RBAC for network operations
- Audit logging available

### Data Plane Security
- GENEVE encryption support (IPsec)
- Flow-based ACLs via OVN
- Microsegmentation per tier

## Performance Optimization

### Userspace Datapath
- DPDK support possible (not default)
- CPU pinning for vswitchd
- Hugepages for packet buffers

### Scaling Considerations
- Single OVN central supports ~1000 chassis
- Distributed gateways avoid bottlenecks
- Flow caching reduces controller load

## Troubleshooting

### Common Issues

1. **Containers can't communicate**
   - Check OVN logical topology: `ovn-nbctl show`
   - Verify chassis registration: `ovn-sbctl show`
   - Check GENEVE tunnels: `ovs-vsctl show`

2. **Docker network creation fails**
   - Ensure driver is running: `docker plugin ls`
   - Check driver logs: `docker logs ovn-central`
   - Verify Docker socket mount

3. **Poor performance**
   - Check CPU allocation
   - Verify userspace datapath active
   - Monitor flow table size

### Debug Commands

```bash
# OVN logical view
docker exec ovn-central ovn-nbctl show

# Physical bindings
docker exec ovn-central ovn-sbctl show

# OVS bridges and ports
docker exec ovs-vpc-a ovs-vsctl show

# Flow tables
docker exec ovs-vpc-a ovs-ofctl dump-flows br-int

# Tunnel status
docker exec ovs-vpc-a ovs-appctl ofproto/list-tunnels
```

## Future Enhancements

1. **Kubernetes Integration**
   - OVN-Kubernetes CNI plugin
   - Pod networking via OVN

2. **Advanced Features**
   - Load balancing via OVN
   - Distributed firewall rules
   - QoS and traffic shaping

3. **Federation**
   - Multi-region support
   - WAN optimization
   - Hybrid cloud connectivity

---

**Status**: Architecture Design Phase
**Next Steps**: Implement OVN Docker driver integration