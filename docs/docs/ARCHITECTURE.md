# OVS Container Lab Architecture

## Overview

This lab provides two distinct operational modes for different use cases:

1. **Single OVS Mode** - Traditional OVS bridge networking for container interconnection
2. **Multi-VPC Mode** - Cloud-native SDN architecture with OVN and FRR routing

## Single OVS Mode (Default)

### Components

```
┌─────────────────────────────────────────────────┐
│              Docker Host                        │
│                                                  │
│  ┌─────────────────────────────────────────┐    │
│  │         OVS Container (Privileged)       │    │
│  │                                          │    │
│  │  ┌────────────────────────────────┐     │    │
│  │  │   ovs-vswitchd (userspace)     │     │    │
│  │  │                                 │     │    │
│  │  │     ┌─────────────────┐        │     │    │
│  │  │     │    ovs-br0      │        │     │    │
│  │  │     │  172.18.0.1/24  │        │     │    │
│  │  │     └────────┬────────┘        │     │    │
│  │  └──────────────┼─────────────────┘     │    │
│  │                 │                        │    │
│  │         Network Namespaces               │    │
│  │     ┌───────┼───────┼───────┐           │    │
│  │     │       │       │       │           │    │
│  └─────┼───────┼───────┼───────┼───────────┘    │
│        │       │       │       │                 │
│    ┌───▼──┐ ┌──▼──┐ ┌──▼──┐ ┌─▼──┐             │
│    │Test-1│ │Test-2│ │Test-3│ │... │             │
│    └──────┘ └─────┘ └─────┘ └────┘             │
└─────────────────────────────────────────────────┘
```

### Key Features

- **Userspace Datapath**: Cross-platform compatibility without kernel modules
- **Network Namespaces**: Container isolation using Linux namespaces
- **PID Sharing**: OVS container shares PID namespace with host for container access
- **Bridge Configuration**: Single bridge (ovs-br0) with 172.18.0.0/24 subnet

### Use Cases

- Container networking demos
- OVS feature testing
- Network monitoring and metrics collection
- Chaos engineering experiments

## Multi-VPC Mode (--profile vpc)

### High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                     OVN Control Plane                        │
│                                                              │
│   Northbound DB ◄──── ovn-northd ────► Southbound DB        │
│   (Logical View)     (Translator)     (Physical View)       │
└────────────────────────────┬─────────────────────────────────┘
                             │
                ┌────────────┴────────────┐
                │                         │
        ┌───────▼────────┐       ┌───────▼────────┐
        │   OVS-VPC-A    │       │   OVS-VPC-B    │
        │                │       │                │
        │ ovn-controller │       │ ovn-controller │
        │   + OVS        │       │   + OVS        │
        │                │       │                │
        │  10.0.0.0/16   │       │  10.1.0.0/16   │
        └───────┬────────┘       └────────┬───────┘
                │                         │
        ┌───────▼────────┐       ┌────────▼───────┐
        │ vRouter-VPC-A  │◄─────►│ vRouter-VPC-B  │
        │     (FRR)      │ OSPF  │     (FRR)      │
        └────────────────┘       └────────────────┘
                    Transit Network
                   192.168.100.0/24
```

### Component Details

#### OVN Central (ovn-central)
- **Role**: SDN control plane
- **Components**:
  - Northbound Database: Stores logical network configuration
  - Southbound Database: Stores physical network state
  - ovn-northd: Translates logical to physical flows
- **Network**: Connected to transit network for control plane communication

#### OVS Instances (ovs-vpc-a, ovs-vpc-b)
- **Role**: Data plane for each VPC
- **Components**:
  - OVS bridge (br-int): Integration bridge managed by OVN
  - ovn-controller: Programs OpenFlow rules based on Southbound DB
  - GENEVE tunnels: Overlay network between VPCs
- **Networks**:
  - VPC-specific internal network
  - Transit overlay network for inter-VPC tunneling

#### FRR vRouters (vrouter-vpc-a, vrouter-vpc-b)
- **Role**: Inter-VPC routing
- **Components**:
  - FRR daemon: Runs OSPF/BGP routing protocols
  - Static routes: Configured for VPC subnets
- **Networks**:
  - Connected to VPC internal networks
  - Connected to transit network for routing

### Network Topology

```yaml
Physical Networks (Docker):
  vpc-a-internal: 192.168.10.0/24
  vpc-b-internal: 192.168.20.0/24
  transit-overlay: 192.168.100.0/24

Logical Networks (OVN):
  VPC-A:
    - vpc-a-web: 10.0.1.0/24
    - vpc-a-app: 10.0.2.0/24
    - vpc-a-db: 10.0.3.0/24
  
  VPC-B:
    - vpc-b-web: 10.1.1.0/24
    - vpc-b-app: 10.1.2.0/24
    - vpc-b-db: 10.1.3.0/24
  
  Transit:
    - transit-network: 10.99.1.0/24 (logical)
```

### Traffic Flow

#### Intra-VPC Traffic (Same VPC)
```
Container A → OVS br-int → OVN flows → Container B
```
- Handled entirely by OVN logical flows
- No external routing required
- Microsegmentation via logical switches

#### Inter-VPC Traffic (Different VPCs)
```
VPC-A Container → OVN → vRouter-A → Transit → vRouter-B → OVN → VPC-B Container
```
1. Source container sends packet
2. OVN routes to local vRouter
3. vRouter-A forwards to vRouter-B
4. vRouter-B delivers to destination VPC
5. OVN forwards to target container

#### External Traffic
```
Container → OVN → NAT Gateway → External Network
```
- SNAT configured on logical routers
- External bridge (br-external) for outside connectivity
- Supports multiple external gateways

### SDN Components

#### Logical Switches
- Software-defined L2 segments
- VLAN-like isolation without physical VLANs
- MAC learning and ARP responder built-in

#### Logical Routers
- Distributed routing between logical switches
- Gateway ports for external connectivity
- Static and dynamic routing support

#### OpenFlow Rules
- Automatically generated from logical topology
- ~1000 flows per OVS instance
- Priority-based packet processing

### Overlay Networking

#### GENEVE Tunnels
```
┌──────────────┐          ┌──────────────┐
│  OVS-VPC-A   │          │  OVS-VPC-B   │
│              │          │              │
│  10.0.1.10   │          │  10.1.1.10   │
│      ↓       │          │      ↑       │
│   GENEVE     │◄────────►│   GENEVE     │
│  Encapsulate │          │ Decapsulate  │
└──────────────┘          └──────────────┘
     192.168.100.10          192.168.100.20
```

- **Protocol**: GENEVE (Generic Network Virtualization Encapsulation)
- **Purpose**: Tunneling between OVS instances
- **Key Exchange**: Automatic via OVN Southbound DB
- **MTU Considerations**: 1500 - 50 (GENEVE overhead) = 1450

### High Availability Considerations

#### Control Plane HA
- OVN databases support clustering (not implemented in lab)
- Multiple ovn-northd instances possible
- Raft consensus for database replication

#### Data Plane HA
- Gateway chassis with BFD monitoring
- Automatic failover for gateway ports
- Distributed routing reduces single points of failure

### Monitoring Integration

#### Metrics Collection Architecture

**Single OVS Mode:**
```
OVS → ovs_exporter (9475) → Prometheus → Grafana
```

**Multi-VPC Mode:**
```
┌─────────────────────────────────────────────┐
│ ovs-vpc-a ──┐                               │
│             ├→ multi-vpc-exporter (9476) ───┼→ Prometheus
│ ovs-vpc-b ──┘                               │
│                                             │
│ ovn-central → multi-vpc-exporter (9476) ────┼→ Prometheus
│                                             │
│ vrouter-a → node_exporter (9101) ──────────┼→ Prometheus
│ vrouter-b → node_exporter (9102) ──────────┼→ Prometheus
└─────────────────────────────────────────────┘
```

#### Key Metrics Collected

**OVS Metrics:**
- Interface statistics (rx/tx packets, bytes, drops, errors)
- OpenFlow flow table sizes and counts
- Port status and configuration
- Bridge information

**OVN Metrics:**
- Logical switch/router counts
- Logical port statistics
- Chassis registration status
- Northbound/Southbound DB health

**GENEVE Tunnel Metrics:**
- Per-tunnel packet/byte statistics
- Tunnel endpoint health
- Encapsulation overhead monitoring

**vRouter Metrics:**
- CPU and memory utilization
- Network interface statistics
- Routing table size
- OSPF neighbor status

#### Available Dashboards
1. **OVS Underlay Failure Detection** - Network failure scenarios
2. **OVS Datapath & Flow Analysis** - Flow table analytics
3. **OVS Coverage & Drops Analysis** - Packet drop investigation
4. **Multi-VPC Monitoring** - VPC-specific metrics and health
5. **OVS System Resources** - Resource utilization

### Stress Testing & Chaos Engineering

#### Traffic Generation Capabilities

**Traffic Intensities:**
- **Low**: 10-50 packets/sec - Normal application traffic
- **Medium**: 1,000-5,000 packets/sec - Moderate load
- **High**: 10,000-50,000 packets/sec - Heavy load
- **Overload**: 50,000+ packets/sec - Stress testing

**Traffic Types:**
- TCP SYN floods
- UDP floods
- ICMP floods
- Mixed protocol traffic
- Inter-VPC traffic patterns

#### Chaos Scenarios

**Component-Specific Stress:**
1. **OVN Controller Stress**
   - CPU and memory exhaustion
   - Database churn (rapid create/delete operations)
   - Connection flapping

2. **OVS Instance Stress**
   - Flow table overload (10,000+ flows)
   - Packet processing bottlenecks
   - GENEVE tunnel saturation

3. **vRouter Stress**
   - Routing table explosion (50,000+ routes)
   - OSPF protocol churn
   - Interface flapping

**Orchestrated Chaos Scenarios:**
1. **Standard Chaos** - Progressive degradation with recovery periods
2. **Cascading Failure** - Component failures triggering cascade effects
3. **Apocalypse Mode** - Simultaneous failure of all components

**Network Chaos Types:**
- Packet loss (configurable percentage)
- Network delay and jitter
- Bandwidth limitation
- Packet corruption
- Network partitioning (split-brain)

**Resource Stress:**
- CPU stress (configurable core count)
- Memory exhaustion
- I/O stress
- Combined resource pressure

#### Stress Testing Scripts

```
scripts/network-simulation/
├── vpc-demo.sh              # Automated VPC demos with stress
├── vpc-stress-test.sh       # Component-wide stress testing
├── ovs-overload-test.sh     # OVS-specific overload testing
├── vrouter-stress-test.sh   # vRouter stress testing
├── vpc-chaos-orchestrator.sh # Orchestrated chaos scenarios
└── vpc-traffic-gen.py       # Python-based traffic generator
```

### Comparison with Cloud Providers

| Feature | Our Lab | AWS VPC | OpenStack Neutron |
|---------|---------|---------|-------------------|
| Isolation | OVN Logical Switches | Security Groups | Network Namespaces |
| Routing | FRR vRouters | AWS Hyperplane | L3 Agent |
| Overlay | GENEVE | Custom | VXLAN/GRE |
| SDN Controller | OVN | Proprietary | OVN/OVS |
| Inter-VPC | vRouter Peering | VPC Peering/TGW | Router |

## Implementation Details

### File Structure
```
ovs-container-lab/
├── docker-compose.yml      # Service definitions
├── ovs-container/          # OVS container config
├── ovn-container/          # OVN central config
├── frr-router/            # FRR vRouter config
├── scripts/
│   ├── ovn-init.sh        # OVN topology setup
│   ├── connect-vpc-to-ovn.sh  # Container connection
│   ├── setup-ovn-topology.sh  # Logical network creation
│   ├── setup-external-gateway.sh  # NAT configuration
│   └── connect-vrouters.sh    # vRouter setup
└── docs/
    ├── ARCHITECTURE.md     # This document
    └── MULTI-VPC-IMPLEMENTATION-PLAN.md
```

### Container Startup Sequence

1. **OVN Central** starts first
   - Initializes Northbound and Southbound databases
   - Starts ovn-northd daemon

2. **OVS Instances** start next
   - Wait for OVN Central to be healthy
   - Start ovs-vswitchd
   - Connect ovn-controller to Southbound DB

3. **Topology Configuration**
   - Create logical switches and routers
   - Configure port bindings
   - Add routing rules

4. **vRouters** start last
   - Initialize FRR daemons
   - Configure static routes
   - Establish OSPF adjacencies

5. **Container Connection**
   - Create internal OVS ports
   - Bind to OVN logical ports
   - Configure IP addresses

### Troubleshooting

#### Common Issues

1. **Inter-VPC routing not working**
   - Check GENEVE tunnel status: `ovs-vsctl show`
   - Verify vRouter routes: `docker exec vrouter-vpc-a ip route`
   - Check OVN port bindings: `ovn-sbctl show`

2. **OVN controller not connecting**
   - Verify OVN_REMOTE environment variable
   - Check network connectivity to OVN Central
   - Review ovn-controller logs

3. **High packet loss**
   - Check MTU settings (should be 1450 for GENEVE)
   - Verify CPU resources for OVS/OVN
   - Monitor OpenFlow rule count

4. **Containers not cleaning up**
   - Use `make clean-all` for deep cleanup
   - Use `make clean-force` for emergency cleanup
   - Check for orphaned containers: `docker ps -a | grep ovs`

5. **Monitoring not working**
   - Verify exporters are running: `docker ps | grep exporter`
   - Check Prometheus targets: http://localhost:9090/targets
   - Verify metrics endpoints:
     - Single OVS: http://localhost:9475/metrics
     - Multi-VPC: http://localhost:9476/metrics
     - vRouters: http://localhost:9101/metrics and :9102

6. **Stress tests failing**
   - Ensure all VPC components are running: `make vpc-status`
   - Check Docker resources (CPU/memory limits)
   - Verify Pumba can access Docker socket
   - Check for conflicting container names

#### Debug Commands

```bash
# OVN logical topology
docker exec ovn-central ovn-nbctl show

# OVN physical bindings
docker exec ovn-central ovn-sbctl show

# OVS tunnel status
docker exec ovs-vpc-a ovs-vsctl show

# OpenFlow rules
docker exec ovs-vpc-a ovs-ofctl dump-flows br-int

# Packet tracing
docker exec ovn-central ovn-trace <datapath> <flow>

# vRouter status
docker exec vrouter-vpc-a vtysh -c "show ip ospf neighbor"

# Check stress test status
docker ps --filter "name=stress-" --filter "name=chaos-"

# Monitor real-time metrics
make watch-metrics  # Single OVS
make metrics-vpc    # Multi-VPC

# Emergency cleanup
make clean-force    # WARNING: Removes ALL containers
```

## Future Enhancements

### Planned Features
- BGP routing between vRouters
- Multiple availability zones
- Load balancer integration
- Network policies and ACLs
- IPv6 support
- Service mesh integration

### Scalability Improvements
- OVN database clustering
- Distributed gateway ports
- Incremental processing optimization
- Connection tracking offload

### Monitoring Enhancements
- Flow-based monitoring
- Latency metrics
- Bandwidth utilization per VPC
- Security event logging