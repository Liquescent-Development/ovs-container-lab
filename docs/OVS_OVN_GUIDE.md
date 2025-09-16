# Understanding OVS and OVN: A Comprehensive Guide

## Table of Contents
1. [OVS/OVN for Physical Network Experts](#1-ovsovn-for-physical-network-experts)
2. [Operating System Integration and Data Paths](#2-operating-system-integration-and-data-paths)
3. [Lab Setup Walkthrough](#3-lab-setup-walkthrough)
4. [Component Breakdown](#4-component-breakdown)
5. [Capabilities Overview](#5-capabilities-overview)
6. [OVS/OVN Cheat Sheet](#6-ovsovn-cheat-sheet)
7. [Monitoring for Cloud Providers](#7-monitoring-for-cloud-providers)

---

## 1. OVS/OVN for Physical Network Experts

### The Analogy: From Physical to Virtual

Think of **OVS (Open vSwitch)** as a software-based line card that can be programmed like a high-end switch ASIC, but running in userspace or kernel. It's essentially a virtual Cisco Nexus or Arista switch that you can instantiate anywhere - on servers, in VMs, or containers.

**OVN (Open Virtual Network)** is the SDN control plane - imagine it as a combination of:
- A distributed routing protocol (like OSPF/BGP) that automatically programs routes
- A network orchestrator (like Cisco ACI or VMware NSX)
- A distributed firewall and load balancer controller

### Key Conceptual Mappings

| Physical Network | OVS/OVN Equivalent | Purpose |
|-----------------|-------------------|---------|
| Switch ASIC | OVS Datapath | Fast packet forwarding based on flow rules |
| TCAM/Flow Tables | OpenFlow Tables | Match-action rules for packet processing |
| VLANs | Logical Switches | L2 broadcast domains |
| VRF | Logical Routers | Isolated L3 routing domains |
| Trunk Ports | GENEVE/STT Tunnels | Carry multiple virtual networks |
| Router on a Stick | Distributed Logical Router | Inter-VLAN routing |
| Hardware ACLs | OVN ACLs/Security Groups | Stateful firewall rules |
| Physical Topology | OVN Northbound DB | Desired network state |
| MAC/ARP Tables | OVN Southbound DB | Actual network state/bindings |

### How Packets Flow

1. **Ingress from VM/Container**: Packet enters OVS through a virtual port (veth pair or tap device)
2. **Classification**: OVS matches packet against OpenFlow tables (like TCAM lookup)
3. **Logical Processing**: Packet traverses logical topology:
   - Logical switch (L2 forwarding, like VLAN)
   - Logical router (L3 routing, like VRF)
   - ACLs/Security Groups (distributed firewall)
4. **Encapsulation**: If destination is remote, packet is encapsulated (GENEVE/VXLAN)
5. **Physical Forwarding**: Encapsulated packet sent through physical NIC
6. **Decapsulation & Delivery**: Remote OVS decapsulates and delivers to destination

### Why This Matters

Unlike physical networks where topology changes require rewiring, OVN lets you define your entire network topology in software. You describe what you want (10 VPCs, each with 5 subnets, specific routing policies) and OVN automatically:
- Programs flow rules into every OVS instance
- Handles MAC learning and ARP resolution
- Sets up overlay tunnels between hosts
- Implements distributed routing and firewall rules
- Maintains consistency across hundreds of hypervisors

---

## 2. Operating System Integration and Data Paths

### Understanding OVS Data Path Architecture

OVS operates with multiple data path options, each with different performance characteristics and use cases. The data path is where actual packet forwarding happens, while the control path (ovs-vswitchd) manages the flow tables.

#### Data Path Types

##### 1. Linux Kernel Module (openvswitch.ko)
```
┌─────────────────────────────────────────────────────────────┐
│                        User Space                           │
│  ┌────────────┐  ┌──────────────┐   ┌──────────────┐        │
│  │    VMs     │  │  Containers  │   │     Apps     │        │
│  └─────┬──────┘  └──────┬───────┘   └──────┬───────┘        │
│        │                │                  │                │
│        │ tap/tun        │ veth             │ socket         │
├────────┼────────────────┼──────────────────┼────────────────┤
│        ▼                ▼                  ▼                │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              ovs-vswitchd (slow path)                │   │
│  │  • First packet of flow                              │   │
│  │  • Complex actions                                   │   │
│  │  • Flow table management                             │   │
│  └────────────┬─────────────────────────────────────────┘   │
│               │ netlink                                     │
│               ▼                                             │
│         Kernel Space                                        │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         openvswitch.ko (fast path)                   │   │
│  │  • Cached flows (megaflows)                          │   │
│  │  • Direct packet forwarding                          │   │
│  │  • Connection tracking                               │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Characteristics**:
- **Performance**: High performance, packets stay in kernel
- **CPU Usage**: Low CPU overhead
- **Features**: Full feature set including conntrack
- **Deployment**: Requires kernel module installation
- **Use Cases**: Production hypervisors, high throughput

**Flow Processing**:
1. First packet of flow goes to userspace (upcall)
2. ovs-vswitchd processes and installs megaflow
3. Subsequent packets processed entirely in kernel
4. Megaflows are cached flow entries with wildcards

##### 2. Userspace Data Path (netdev)
```
┌─────────────────────────────────────────────────────────────┐
│                        User Space                           │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────┐         │
│  │    VMs     │  │  Containers  │  │     Apps     │         │
│  └─────┬──────┘  └──────┬───────┘  └──────┬───────┘         │
│        │                │                 │                 │
│        │ tap/tun        │ veth            │ socket          │
│        │                │                 │                 │
│        ▼                ▼                 ▼                 │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              ovs-vswitchd with netdev                │   │
│  │  ┌─────────────────────────────────────────────────┐ │   │
│  │  │         Userspace Data Path                     │ │   │
│  │  │  • All packet processing in userspace           │ │   │
│  │  │  • PMD threads for polling                      │ │   │
│  │  │  • No kernel involvement                        │ │   │
│  │  └─────────────────────────────────────────────────┘ │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│                   No Kernel Processing                      │
└─────────────────────────────────────────────────────────────┘
```

**Characteristics**:
- **Performance**: Moderate, all processing in userspace
- **CPU Usage**: Higher CPU usage due to polling
- **Features**: Full OVS features
- **Deployment**: No kernel modules needed
- **Use Cases**: Containers, development, testing

**Configuration**:
```bash
ovs-vsctl add-br br0 -- set bridge br0 datapath_type=netdev
```

##### 3. DPDK Data Path (High Performance)
```
┌─────────────────────────────────────────────────────────────┐
│                        User Space                           │
│  ┌────────────┐  ┌──────────────┐                           │
│  │  DPDK VMs  │  │ SR-IOV VFs   │                           │
│  └─────┬──────┘  └──────┬───────┘                           │
│        │ vhost-user     │ passthrough                       │
│        ▼                ▼                                   │
│  ┌──────────────────────────────────────────────────────┐   │
│  │           OVS-DPDK (ovs-vswitchd-dpdk)               │   │
│  │  ┌─────────────────────────────────────────────────┐ │   │
│  │  │      DPDK PMD Threads (Poll Mode Driver)        │ │   │
│  │  │  • CPU cores dedicated to packet processing     │ │   │
│  │  │  • Zero-copy packet handling                    │ │   │
│  │  │  • Huge pages for packet buffers                │ │   │
│  │  │  • NUMA-aware memory allocation                 │ │   │
│  │  └─────────────────────────────────────────────────┘ │   │
│  │                          ▼                           │   │
│  │  ┌─────────────────────────────────────────────────┐ │   │
│  │  │          DPDK Libraries & Drivers               │ │   │
│  │  │  • Direct NIC access (bypass kernel)            │ │   │
│  │  │  • User space NIC drivers                       │ │   │
│  │  └─────────────────────────────────────────────────┘ │   │
│  └────────────────────┬─────────────────────────────────┘   │
│                       │                                     │
│                       ▼ Direct NIC Access                   │
│              Physical NICs (DPDK-enabled)                   │
└─────────────────────────────────────────────────────────────┘
```

**Characteristics**:
- **Performance**: Line-rate performance (10/40/100 Gbps)
- **CPU Usage**: Dedicated CPU cores (100% usage)
- **Latency**: Ultra-low latency (<10μs)
- **Features**: Limited features (no kernel conntrack)
- **Use Cases**: NFV, Telco, HPC

**Configuration**:
```bash
# Bind NICs to DPDK
dpdk-devbind.py --bind=vfio-pci 0000:04:00.0

# Configure OVS-DPDK
ovs-vsctl set Open_vSwitch . other_config:dpdk-init=true
ovs-vsctl set Open_vSwitch . other_config:dpdk-lcore-mask=0x3
ovs-vsctl set Open_vSwitch . other_config:dpdk-socket-mem="1024,1024"
ovs-vsctl add-br br0 -- set bridge br0 datapath_type=netdev
ovs-vsctl add-port br0 dpdk0 -- set Interface dpdk0 type=dpdk options:dpdk-devargs=0000:04:00.0
```

##### 4. Hardware Offload (Smart NICs)
```
┌─────────────────────────────────────────────────────────────┐
│                        User Space                           │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              ovs-vswitchd (control plane)            │   │
│  │  • Programs offload rules via TC or DPDK             │   │
│  │  • Handles non-offloaded flows                       │   │
│  └────────────┬─────────────────────────────────────────┘   │
│               │ TC flower / DPDK rte_flow                   │
├───────────────▼─────────────────────────────────────────────┤
│              Kernel (minimal involvement)                   │
├─────────────────────────────────────────────────────────────┤
│            Smart NIC Hardware                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │         NIC ASIC/FPGA (e.g., Mellanox, Intel)        │   │
│  │  • Match-action tables in hardware                   │   │
│  │  • Wire-speed packet processing                      │   │
│  │  • Tunneling encap/decap in hardware                 │   │
│  └──────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────┘
```

**Characteristics**:
- **Performance**: Wire-speed with minimal CPU
- **CPU Usage**: Near-zero for offloaded flows
- **Features**: Depends on NIC capabilities
- **Cost**: Expensive hardware required
- **Use Cases**: Cloud providers, high-density virtualization

### Virtual Networking Interfaces

#### Interface Types and Their Relationships

##### 1. TAP/TUN Devices
```
┌─────────────────────┐
│    VM (QEMU/KVM)    │
│  ┌───────────────┐  │
│  │  Guest Kernel │  │
│  │  eth0 (virtio)│  │
│  └───────┬───────┘  │
└──────────┼──────────┘
           │
     ┌─────▼─────┐
     │   tap0    │  ← TAP device (L2, Ethernet frames)
     │ /dev/tap0 │     or TUN device (L3, IP packets)
     └─────┬─────┘
           │
     ┌─────▼─────┐
     │    OVS    │
     │   br-int  │
     └───────────┘
```

**TAP Devices**:
- Layer 2 (Ethernet) interface
- Used for VM networking with KVM/QEMU
- Appears as regular network interface to host
- Can be added to OVS bridge

**TUN Devices**:
- Layer 3 (IP) interface
- Used for VPN and tunneling applications
- No Ethernet headers

**OVS Integration**:
```bash
# Add TAP to OVS
ovs-vsctl add-port br-int tap0

# Set interface type for VMs
ovs-vsctl set interface tap0 external-ids:vm-id="vm-123"
```

##### 2. veth Pairs (Virtual Ethernet)
```
┌──────────────────┐         ┌──────────────────┐
│   Container A    │         │   Container B    │
│   namespace      │         │   namespace      │
│  ┌────────────┐  │         │  ┌────────────┐  │
│  │   eth0     │  │         │  │   eth0     │  │
│  └─────┬──────┘  │         │  └─────┬──────┘  │
└────────┼─────────┘         └────────┼─────────┘
         │                            │
    ┌────▼────┐                  ┌────▼────┐
    │ vethA1  │◄─────────────────┤ vethB1  │
    └────┬────┘  veth pair       └────┬────┘
         │       (like cable)         │
         │                            │
    ┌────▼────────────────────────────▼────┐
    │              OVS br-int              │
    └──────────────────────────────────────┘
```

**Characteristics**:
- Always created in pairs
- Like a virtual cross-over cable
- Can span network namespaces
- Commonly used with containers

**Creation and OVS Integration**:
```bash
# Create veth pair
ip link add veth0 type veth peer name veth1

# Move one end to container namespace
ip link set veth0 netns $CONTAINER_PID

# Add other end to OVS
ovs-vsctl add-port br-int veth1
```

##### 3. Internal Ports
```
┌─────────────────────────────────────┐
│            Host System              │
│  ┌─────────────────────────────┐    │
│  │      Host IP Stack          │    │
│  │    (routing, iptables)      │    │
│  └──────────┬──────────────────┘    │
│             │                       │
│        ┌────▼────┐                  │
│        │ br-int  │ ← Internal Port  │
│        │10.0.1.1 │   (L3 interface) │
│        └────┬────┘                  │
│             │                       │
│  ┌──────────▼──────────────────┐    │
│  │      OVS Bridge (br-int)    │    │
│  └─────────────────────────────┘    │
└─────────────────────────────────────┘
```

**Purpose**:
- Provides L3 connectivity to host
- Used for management interfaces
- Can act as gateway for VMs/containers

**Configuration**:
```bash
# Create internal port
ovs-vsctl add-port br-int br-int -- set interface br-int type=internal

# Assign IP
ip addr add 10.0.1.1/24 dev br-int
ip link set br-int up
```

##### 4. Patch Ports
```
┌─────────────────────┐     ┌─────────────────────┐
│    OVS Bridge 1     │     │    OVS Bridge 2     │
│      (br-int)       │     │      (br-ex)        │
│  ┌───────────────┐  │     │  ┌───────────────┐  │
│  │  patch-to-ex  ├──┼─────┼──┤  patch-to-int │  │
│  └───────────────┘  │     │  └───────────────┘  │
└─────────────────────┘     └─────────────────────┘
```

**Purpose**:
- Connect two OVS bridges
- Virtual equivalent of cable between switches
- No kernel involvement (pure OVS)

**Configuration**:
```bash
ovs-vsctl add-port br-int patch-to-ex -- set interface patch-to-ex type=patch options:peer=patch-to-int
ovs-vsctl add-port br-ex patch-to-int -- set interface patch-to-int type=patch options:peer=patch-to-ex
```

### Network Namespaces and OVS

Network namespaces provide network isolation at the kernel level. OVS bridges can connect different namespaces.

#### Namespace Architecture
```
┌───────────────────────────────────────────────────────┐
│                   Host Network Namespace              │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐    │
│  │     OVS     │  │   Routes    │  │  iptables   │    │
│  │   br-int    │  │   Tables    │  │    rules    │    │
│  └──────┬──────┘  └─────────────┘  └─────────────┘    │
│         │                                             │
│    ┌────┴─────┬─────────┬─────────┐                   │
│    │          │         │         │                   │
│ ┌──▼──┐    ┌──▼──┐   ┌──▼───┐   ┌─▼────┐              │
│ │veth1│    │veth3│   │veth5 │   │veth7 │              │
│ └──┬──┘    └──┬──┘   └───┬──┘   └───┬──┘              │
└────┼──────────┼──────────┼──────────┼─────────────────┘
     │          │          │          │
 ┌───┼──────────┼──────────┼──────────┼──────────────┐
 │   │          │          │          │              │
 │┌──▼──┐   ┌───▼─┐   ┌────▼─┐   ┌────▼─┐   NS1      │
 ││veth0│   │veth2│   │veth4 │   │veth6 │            │
 │└─────┘   └──┬──┘   └──────┘   └──────┘            │
 │             │                                     │
 │        ┌────▼────┐   ┌─────────┐                  │
 │        │  eth0   │   │ Routes  │                  │
 │        │10.0.1.10│   │ Tables  │                  │
 │        └─────────┘   └─────────┘                  │
 │         Container/VM Namespace                    │
 └───────────────────────────────────────────────────┘
```

#### Creating and Connecting Namespaces
```bash
# Create namespace
ip netns add container-ns

# Create veth pair
ip link add veth-host type veth peer name veth-container

# Move one end to namespace
ip link set veth-container netns container-ns

# Configure namespace interface
ip netns exec container-ns ip addr add 10.0.1.10/24 dev veth-container
ip netns exec container-ns ip link set veth-container up
ip netns exec container-ns ip route add default via 10.0.1.1

# Add host end to OVS
ovs-vsctl add-port br-int veth-host
```

### OVS Port Types Summary

| Port Type | Layer | Use Case | Performance | Kernel Involvement |
|-----------|-------|----------|-------------|-------------------|
| Normal | L2 | Physical NICs | Hardware speed | Yes |
| Internal | L2/L3 | Host connectivity | High | Yes |
| TAP | L2 | VMs (KVM/QEMU) | Good | Yes |
| veth | L2 | Containers | Good | Yes |
| Patch | L2 | Bridge interconnect | Excellent | No |
| DPDK | L2 | High performance | Line-rate | No |
| dpdkvhostuser | L2 | DPDK VMs | Line-rate | No |
| Tunnel | L2/L3 | Overlay (VXLAN/GENEVE) | Good | Varies |

### Integration with Container Runtimes

#### Docker Integration
```bash
# Docker with OVS plugin
docker run -d --name container1 --network none nginx
ovs-docker add-port br-int eth0 container1 --ipaddress=10.0.1.10/24
ovs-docker set-vlan br-int eth0 container1 100
```

#### Kubernetes CNI
```yaml
# OVN-Kubernetes CNI Configuration
apiVersion: v1
kind: ConfigMap
metadata:
  name: ovn-config
data:
  ovn_kubernetes.conf: |
    [default]
    mtu=1400
    cluster-subnets=10.128.0.0/14/23
    encap-type=geneve
```

### Connection Flow Example

Here's a complete example showing how a packet flows from a container through OVS to the external network:

```
Container (10.0.1.10) → veth → OVS Bridge → Flow Tables → Encapsulation → Physical NIC

Detailed Path:
1. Container network stack generates packet
2. Packet exits via veth interface in container namespace
3. Arrives at peer veth in host namespace
4. OVS receives packet on veth port
5. Packet matches OpenFlow rules:
   - Table 0: Classification (which logical network?)
   - Table 20: Ingress ACL (security policies)
   - Table 30: L2 forwarding (MAC learning)
   - Table 40: L3 routing (if needed)
   - Table 50: Egress ACL
   - Table 60: Output processing
6. If remote destination: GENEVE encapsulation
7. Forward to physical NIC via kernel network stack
8. Or if DPDK: Direct to NIC bypassing kernel
```

### Performance Tuning by Data Path

#### Kernel Module Tuning
```bash
# Increase flow cache size
ovs-vsctl set Open_vSwitch . other_config:flow-limit=2000000

# Adjust revalidator threads
ovs-vsctl set Open_vSwitch . other_config:n-revalidator-threads=4

# Enable/disable kernel flow cache
ovs-appctl upcall/set-flow-limit 200000
```

#### Userspace/Netdev Tuning
```bash
# Set PMD threads
ovs-vsctl set Open_vSwitch . other_config:pmd-cpu-mask=0xFF

# Pin PMD threads to cores
ovs-vsctl set Open_vSwitch . other_config:pmd-rxq-affinity="0:1,1:2"

# Adjust EMC (Exact Match Cache) size
ovs-vsctl set Open_vSwitch . other_config:emc-insert-inv-prob=100
```

#### DPDK Tuning
```bash
# Huge pages configuration
echo 1024 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages

# NUMA awareness
ovs-vsctl set Open_vSwitch . other_config:dpdk-socket-mem="2048,2048"

# CPU isolation
isolcpus=2-7 # In kernel boot parameters

# Set core masks
ovs-vsctl set Open_vSwitch . other_config:dpdk-lcore-mask=0x3
ovs-vsctl set Open_vSwitch . other_config:pmd-cpu-mask=0x3C
```

### Troubleshooting Data Path Issues

#### Check Data Path Type
```bash
ovs-vsctl get bridge br-int datapath_type
ovs-dpctl show
```

#### Analyze Packet Path
```bash
# Trace packet through data path
ovs-appctl ofproto/trace br-int in_port=1,dl_src=00:00:00:00:00:01,dl_dst=00:00:00:00:00:02

# Check upcall statistics
ovs-appctl coverage/show | grep upcall

# Monitor data path flows
watch -n 1 'ovs-dpctl dump-flows'
```

#### Performance Bottleneck Detection
```bash
# Check CPU usage by thread
top -H -p $(pidof ovs-vswitchd)

# PMD statistics (DPDK)
ovs-appctl dpif-netdev/pmd-stats-show

# Cache effectiveness
ovs-appctl dpif-netdev/subtable-lookup-stats-show
```

---

## 3. Lab Setup Walkthrough

### Step-by-Step Manual Setup

Here's exactly what happens when you set up the OVS container lab, broken down into manual commands:

#### Step 1: Initialize OVS Database and Daemon
```bash
# Create and initialize the OVS database
ovsdb-tool create /etc/openvswitch/conf.db /usr/share/openvswitch/vswitch.ovsschema

# Start the OVS database server
ovsdb-server --remote=punix:/var/run/openvswitch/db.sock \
             --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
             --pidfile --detach

# Initialize the database (only needed first time)
ovs-vsctl --no-wait init

# Start the OVS daemon
ovs-vswitchd --pidfile --detach --log-file
```
**What this does**: Sets up OVS's configuration database and starts the switching daemon. Think of it as booting up your virtual switch.

#### Step 2: Create Integration Bridge
```bash
# Create the integration bridge (br-int is OVN's standard bridge name)
ovs-vsctl add-br br-int

# Set the bridge to use OpenFlow 1.3+ for advanced features
ovs-vsctl set bridge br-int protocols=OpenFlow13,OpenFlow14,OpenFlow15
```
**What this does**: Creates the main bridge where all virtual ports connect. Like creating a VLAN on a physical switch.

#### Step 3: Initialize OVN Control Plane
```bash
# Start OVN Northbound database (stores logical topology)
ovsdb-server --detach --remote=punix:/var/run/ovn/ovnnb_db.sock \
             --remote=db:OVN_Northbound,NB_Global,connections \
             --pidfile=/var/run/ovn/ovnnb_db.pid \
             /var/lib/ovn/ovnnb.db

# Start OVN Southbound database (stores physical bindings)
ovsdb-server --detach --remote=punix:/var/run/ovn/ovnsb_db.sock \
             --remote=db:OVN_Southbound,SB_Global,connections \
             --pidfile=/var/run/ovn/ovnsb_db.pid \
             /var/lib/ovn/ovnsb.db

# Start OVN Northd (translates logical to physical)
ovn-northd --pidfile --detach --log-file
```
**What this does**: Starts OVN's control plane. Northbound DB is like your intended config, Southbound DB is like your running config, and northd translates between them.

#### Step 4: Connect OVS to OVN
```bash
# Tell OVS about this chassis (physical host)
ovs-vsctl set open-vswitch . external_ids:system-id="chassis-1"
ovs-vsctl set open-vswitch . external_ids:hostname="host1"
ovs-vsctl set open-vswitch . external_ids:ovn-encap-type="geneve"
ovs-vsctl set open-vswitch . external_ids:ovn-encap-ip="192.168.100.10"

# Start the OVN controller (programs OVS based on OVN topology)
ovn-controller --pidfile --detach --log-file
```
**What this does**: Registers this OVS instance with OVN and starts the controller that programs OpenFlow rules based on the logical topology.

#### Step 5: Create Logical Topology
```bash
# Create a logical switch (like a VLAN)
ovn-nbctl ls-add ls-web
ovn-nbctl lsp-add ls-web lsp-web-port1
ovn-nbctl lsp-set-addresses lsp-web-port1 "02:00:00:00:00:01 10.0.1.10"

# Create a logical router (like a VRF)
ovn-nbctl lr-add lr-vpc-a
ovn-nbctl lrp-add lr-vpc-a lrp-vpc-a-web 02:00:00:00:01:00 10.0.1.1/24
ovn-nbctl lsp-add ls-web ls-web-router
ovn-nbctl lsp-set-type ls-web-router router
ovn-nbctl lsp-set-addresses ls-web-router "02:00:00:00:01:00"
ovn-nbctl lsp-set-options ls-web-router router-port=lrp-vpc-a-web
```
**What this does**: Defines your network topology in software. Creates switches, routers, and connects them together.

#### Step 6: Add NAT and External Connectivity
```bash
# Add NAT rules for external access
ovn-nbctl lr-nat-add lr-vpc-a snat 192.168.100.100 10.0.0.0/16
ovn-nbctl lr-route-add lr-vpc-a 0.0.0.0/0 192.168.100.1

# Set gateway chassis (which host handles external traffic)
ovn-nbctl lrp-set-gateway-chassis lrp-vpc-a-external chassis-1 20
```
**What this does**: Configures NAT for internet access and designates which physical host handles north-south traffic.

#### Step 7: Connect Containers
```bash
# Create a veth pair (like a virtual cable)
ip link add veth-web type veth peer name ovs-veth-web

# Move one end into container's network namespace
ip link set veth-web netns $(docker inspect -f '{{.State.Pid}}' container-web)
docker exec container-web ip addr add 10.0.1.10/24 dev veth-web
docker exec container-web ip link set veth-web up
docker exec container-web ip route add default via 10.0.1.1

# Attach other end to OVS
ovs-vsctl add-port br-int ovs-veth-web
ovs-vsctl set interface ovs-veth-web external_ids:iface-id=lsp-web-port1
```
**What this does**: Creates a virtual cable between the container and OVS, then tells OVN which logical port this physical interface corresponds to.

#### Step 8: Verify Flows
```bash
# Check programmed OpenFlow rules
ovs-ofctl -O OpenFlow13 dump-flows br-int

# Verify port bindings
ovn-sbctl show
ovn-sbctl list port_binding

# Test connectivity
docker exec container-web ping 10.0.1.1
```
**What this does**: Verifies that OVN has programmed the correct forwarding rules into OVS.

---

## 4. Component Breakdown

### OVS Components

#### ovs-vswitchd
- **Purpose**: The main switching daemon
- **Function**: Implements the datapath, processes packets according to OpenFlow rules
- **Analogy**: The switching ASIC/forwarding plane
- **Key Operations**: Packet classification, action execution, statistics collection

#### ovsdb-server
- **Purpose**: Configuration database
- **Function**: Stores switch configuration, port information, bridge settings
- **Analogy**: Switch's running configuration
- **Key Data**: Bridges, ports, interfaces, QoS settings, OpenFlow controllers

#### ovs-vsctl
- **Purpose**: Configuration utility
- **Function**: Modifies OVS configuration
- **Analogy**: CLI for configuring a physical switch
- **Common Commands**: Add/delete bridges, add/delete ports, set controllers

#### ovs-ofctl
- **Purpose**: OpenFlow management utility
- **Function**: Directly manipulates flow tables
- **Analogy**: Low-level TCAM programming tool
- **Use Cases**: Debugging flows, adding custom rules, viewing statistics

#### ovs-dpctl
- **Purpose**: Datapath management
- **Function**: Controls kernel or userspace datapath
- **Analogy**: ASIC-level debugging tool
- **Operations**: View/modify datapath flows, show cache statistics

### OVN Components

#### ovn-northd
- **Purpose**: Central control plane daemon
- **Function**: Translates logical network from Northbound DB to physical flows in Southbound DB
- **Analogy**: SDN controller's brain
- **Responsibilities**: Route calculation, ACL compilation, load balancer configuration

#### ovn-controller
- **Purpose**: Local control plane agent
- **Function**: Programs OVS on each hypervisor based on Southbound DB
- **Analogy**: OpenFlow agent on a switch
- **Operations**: Monitors SB database, programs flows, handles local events

#### ovn-nbctl
- **Purpose**: Northbound DB management
- **Function**: Configure logical network topology
- **Analogy**: Network orchestration API
- **Objects**: Logical switches, routers, ACLs, load balancers

#### ovn-sbctl
- **Purpose**: Southbound DB management
- **Function**: View/debug physical network state
- **Analogy**: Operational state viewer
- **Information**: Chassis, port bindings, MAC bindings, flow tables

#### Northbound Database
- **Purpose**: Stores desired logical network configuration
- **Schema Objects**:
  - Logical_Switch: Virtual L2 segments
  - Logical_Router: Virtual L3 routers
  - Logical_Switch_Port/Logical_Router_Port: Virtual interfaces
  - ACL: Firewall rules
  - Load_Balancer: LB configuration
  - NAT: NAT rules
  - QoS: Quality of service policies

#### Southbound Database
- **Purpose**: Stores physical network state and bindings
- **Schema Objects**:
  - Chassis: Physical hypervisors/hosts
  - Port_Binding: Maps logical ports to physical locations
  - MAC_Binding: ARP/ND cache
  - Logical_Flow: OpenFlow rules to be programmed
  - Multicast_Group: BUM traffic handling

---

## 5. Capabilities Overview

### OVS Capabilities

#### Switching Features
- **Multi-table Pipeline**: Up to 255 flow tables for complex processing
- **VLAN Support**: 802.1Q tagging/untagging, QinQ
- **Bonding/LAG**: Active-backup, balance-slb, balance-tcp modes
- **Spanning Tree**: STP/RSTP support
- **Port Mirroring**: SPAN/RSPAN functionality
- **Learning**: MAC learning with configurable aging

#### Advanced Networking
- **Tunneling Protocols**: VXLAN, GENEVE, GRE, STT, IPsec
- **MPLS**: Push/pop labels, LSR functionality
- **NAT**: Connection tracking based NAT
- **Stateful Firewall**: Connection tracking with iptables-like rules
- **QoS**: Rate limiting, queuing, traffic shaping
- **NetFlow/sFlow/IPFIX**: Traffic monitoring and analysis

#### Performance Features
- **DPDK Support**: Userspace datapath with DPDK for line-rate performance
- **Hardware Offload**: NIC offload for supporting cards
- **Megaflows**: Flow caching for performance
- **Datapath Types**: Kernel module, userspace, or Windows

### OVN Capabilities

#### Logical Networking
- **Distributed L2**: Logical switches span multiple hypervisors
- **Distributed L3**: Logical routers with distributed processing
- **Distributed Security**: ACLs processed at ingress hypervisor
- **Distributed Load Balancing**: LB rules applied at source
- **Distributed NAT**: SNAT/DNAT at hypervisor level

#### Multi-Tenancy
- **Overlapping IP**: Multiple tenants can use same IP space
- **Logical Isolation**: Complete separation between tenants
- **Per-Tenant QoS**: Individual bandwidth/priority policies
- **RBAC**: Role-based access control for management

#### Service Features
- **DHCP**: Native DHCP server per logical switch
- **DNS**: Distributed DNS responder
- **IPv6**: Full IPv6 support including RA
- **BFD**: Bidirectional forwarding detection
- **ECMP**: Equal-cost multi-path routing
- **Policy Routing**: Route based on source/destination/protocol

#### High Availability
- **Active-Standby Gateways**: Automatic failover for external connectivity
- **Distributed Gateway**: Every hypervisor can be a gateway
- **OVN-IC**: Interconnection between multiple OVN deployments
- **Database HA**: Active-backup or clustered OVSDB

---

## 6. OVS/OVN Cheat Sheet

### Essential OVS Commands

```bash
# Bridge Management
ovs-vsctl add-br <bridge>                    # Create bridge
ovs-vsctl del-br <bridge>                    # Delete bridge
ovs-vsctl list-br                            # List all bridges
ovs-vsctl br-exists <bridge>                 # Check if bridge exists

# Port Management
ovs-vsctl add-port <bridge> <port>           # Add port to bridge
ovs-vsctl del-port <bridge> <port>           # Remove port from bridge
ovs-vsctl list-ports <bridge>                # List ports on bridge
ovs-vsctl port-to-br <port>                  # Find bridge for port

# VLAN Configuration
ovs-vsctl set port <port> tag=<vlan-id>      # Set access port VLAN
ovs-vsctl set port <port> trunk=<vlan-list>  # Set trunk VLANs
ovs-vsctl clear port <port> tag              # Remove VLAN tag

# View Configuration
ovs-vsctl show                                # Show overall config
ovs-vsctl list bridge                        # Detailed bridge info
ovs-vsctl get bridge <br> datapath_type      # Get datapath type

# Flow Management
ovs-ofctl dump-flows <bridge>                # Show all flows
ovs-ofctl add-flow <bridge> <flow>           # Add flow rule
ovs-ofctl del-flows <bridge>                 # Delete all flows
ovs-ofctl dump-ports <bridge>                # Show port statistics

# Troubleshooting
ovs-dpctl show                                # Show datapath info
ovs-dpctl dump-flows                         # Show datapath flows
ovs-appctl dpif/show                         # Show datapath interfaces
ovs-appctl coverage/show                     # Show coverage counters
```

### Essential OVN Commands

```bash
# Logical Switch Management
ovn-nbctl ls-add <switch>                    # Create logical switch
ovn-nbctl ls-del <switch>                    # Delete logical switch
ovn-nbctl ls-list                            # List logical switches

# Logical Switch Ports
ovn-nbctl lsp-add <switch> <port>            # Add port to switch
ovn-nbctl lsp-set-addresses <port> <mac> <ip> # Set port addresses
ovn-nbctl lsp-set-port-security <port> <addrs> # Set port security

# Logical Router Management
ovn-nbctl lr-add <router>                    # Create logical router
ovn-nbctl lr-del <router>                    # Delete logical router
ovn-nbctl lr-list                            # List logical routers

# Logical Router Ports
ovn-nbctl lrp-add <router> <port> <mac> <ip/mask> # Add router port
ovn-nbctl lrp-del <port>                     # Delete router port

# Static Routes
ovn-nbctl lr-route-add <router> <prefix> <nexthop> # Add route
ovn-nbctl lr-route-list <router>             # List routes
ovn-nbctl lr-route-del <router> <prefix>     # Delete route

# NAT Configuration
ovn-nbctl lr-nat-add <router> snat <ext-ip> <int-subnet> # Add SNAT
ovn-nbctl lr-nat-add <router> dnat <ext-ip> <int-ip>    # Add DNAT
ovn-nbctl lr-nat-list <router>               # List NAT rules
ovn-nbctl lr-nat-del <router> <type> <ip>    # Delete NAT rule

# ACLs (Firewall Rules)
ovn-nbctl acl-add <switch> <dir> <priority> <match> <action> # Add ACL
ovn-nbctl acl-list <switch>                  # List ACLs
ovn-nbctl acl-del <switch>                   # Delete all ACLs

# Load Balancer
ovn-nbctl lb-add <lb-name> <vip> <backends>  # Create load balancer
ovn-nbctl lr-lb-add <router> <lb-name>       # Attach LB to router
ovn-nbctl ls-lb-add <switch> <lb-name>       # Attach LB to switch

# Southbound Inspection
ovn-sbctl show                                # Show chassis and bindings
ovn-sbctl list chassis                       # List all chassis
ovn-sbctl list port_binding                  # Show port bindings
ovn-sbctl list mac_binding                   # Show MAC bindings

# Tracing
ovn-trace <datapath> <microflow>             # Trace packet flow
ovn-detrace < ovs-dpctl-output               # Decode datapath actions
```

### Common Troubleshooting Patterns

```bash
# Check if container is properly connected
ovs-vsctl list interface <port> | grep external_ids
ovn-sbctl find port_binding logical_port=<lsp-name>

# Verify tunnel establishment
ovs-vsctl show | grep -A 1 "Port.*geneve"
ovs-ofctl dump-ports <bridge> | grep -E "port.*[1-9][0-9]*:"

# Debug packet drops
ovs-dpctl dump-flows | grep drop
ovs-ofctl dump-flows br-int | grep -E "actions=drop|n_packets=0"

# Check controller connection
ovs-vsctl get-controller <bridge>
ovn-sbctl list connection

# Monitor flow programming in real-time
ovs-ofctl monitor br-int watch:
ovn-controller --log-file=/tmp/ovn.log --detach
```

---

## 7. Monitoring for Cloud Providers

### Critical Metrics to Monitor

#### Data Plane Health
1. **Packet Processing Performance**
   ```bash
   # Monitor with Prometheus metrics
   ovs_interface_rx_packets_total         # Ingress packet rate
   ovs_interface_tx_packets_total         # Egress packet rate
   ovs_interface_rx_dropped_total         # Dropped packets (critical!)
   ovs_interface_collisions_total         # Network collisions
   ovs_datapath_flows                     # Active flows in datapath
   ovs_datapath_cache_hit_ratio           # Flow cache efficiency
   ```
   **Alert Thresholds**:
   - Packet drops > 0.01%
   - Cache hit ratio < 95%
   - Flow count > 100k

2. **Bridge and Port Status**
   ```bash
   ovs_bridge_port_count                  # Ports per bridge
   ovs_interface_admin_state               # Port up/down
   ovs_interface_link_state                # Link status
   ovs_interface_mtu_bytes                 # MTU mismatches
   ```
   **Alert Conditions**:
   - Any port admin_state != up
   - MTU inconsistencies across tunnel endpoints

#### Control Plane Health
3. **OVN Database Performance**
   ```bash
   # Monitor database operations
   ovn_northbound_cluster_role             # NB DB role (leader/follower)
   ovn_southbound_cluster_role             # SB DB role
   ovn_northbound_db_size_bytes           # Database size
   ovn_southbound_db_size_bytes
   ovn_controller_processing_delay_ms      # Flow programming delay
   ```
   **Alert Thresholds**:
   - DB size > 1GB
   - Processing delay > 100ms
   - Leader changes > 1/hour

4. **Logical Topology Scale**
   ```bash
   ovn_logical_switches_total              # Number of logical switches
   ovn_logical_routers_total               # Number of logical routers
   ovn_logical_ports_total                 # Total logical ports
   ovn_port_bindings_total                 # Bound ports
   ovn_mac_bindings_total                  # MAC cache size
   ```
   **Alert Conditions**:
   - Unbound ports > 0
   - MAC bindings > 100k (potential MAC explosion)

#### Tunnel Health
5. **Overlay Network Status**
   ```bash
   ovs_tunnel_rx_packets                   # Tunnel ingress
   ovs_tunnel_tx_packets                   # Tunnel egress
   ovs_tunnel_rx_errors                    # Tunnel errors
   ovs_bfd_status                          # BFD session status
   ovs_tunnel_remote_ip_count              # Number of tunnel endpoints
   ```
   **Alert Thresholds**:
   - Tunnel errors > 0
   - BFD status != up
   - Tunnel endpoint changes

#### Resource Utilization
6. **System Resources**
   ```bash
   ovs_vswitchd_cpu_usage_percent          # CPU usage
   ovs_vswitchd_memory_usage_bytes         # Memory usage
   ovs_vswitchd_file_descriptors           # Open FDs
   ovs_handler_threads                     # Thread count
   ovs_revalidator_threads
   ```
   **Alert Thresholds**:
   - CPU > 80%
   - Memory > 4GB
   - FDs > 10k

### Monitoring Best Practices

#### 1. Dashboard Organization
Create separate dashboards for:
- **Tenant View**: Per-VPC metrics, isolated by tenant
- **Infrastructure View**: Physical host and tunnel metrics
- **Control Plane View**: OVN database and controller health
- **Troubleshooting View**: Packet drops, errors, failed flows

#### 2. Alerting Strategy
```yaml
# Example Prometheus alert rules
groups:
  - name: ovs_critical
    rules:
      - alert: HighPacketDropRate
        expr: rate(ovs_interface_rx_dropped_total[5m]) > 100
        for: 2m
        annotations:
          summary: "High packet drop rate on {{ $labels.interface }}"

      - alert: OVNControllerDisconnected
        expr: up{job="ovn-controller"} == 0
        for: 1m
        annotations:
          summary: "OVN controller disconnected on {{ $labels.chassis }}"

      - alert: TunnelEndpointDown
        expr: ovs_bfd_status != 1
        for: 30s
        annotations:
          summary: "BFD detected tunnel failure to {{ $labels.remote_ip }}"
```

#### 3. Capacity Planning Metrics
Track trends for:
- Flow table utilization (percentage of max flows)
- Port creation/deletion rate
- Database growth rate
- Tunnel endpoint scaling
- MAC binding table size

#### 4. Performance Baselines
Establish baselines for:
- Normal packet processing latency (<100μs)
- Flow installation time (<10ms)
- Database replication lag (<100ms)
- Tunnel overhead (GENEVE adds ~50 bytes)

#### 5. Troubleshooting Metrics
When issues occur, check:
- Connection tracking table size
- Datapath flow recirculation count
- OpenFlow message rate to controller
- Database compaction frequency
- Memory allocator statistics

### Cloud Provider Specific Considerations

#### Multi-Tenant Isolation
- Monitor per-tenant resource consumption
- Track cross-tenant traffic (should be zero)
- Audit ACL rule changes
- Monitor tenant-specific QoS compliance

#### Scale Considerations
- **< 100 hypervisors**: Single OVN deployment
- **100-1000 hypervisors**: OVN with DB clustering
- **> 1000 hypervisors**: Multiple OVN deployments with OVN-IC

#### Integration Points
Monitor integration with:
- **CNI plugins** (for Kubernetes)
- **OpenStack Neutron** (for OpenStack)
- **Cloud management platforms**
- **Physical network equipment** (BGP peering, VLAN handoff)

#### Disaster Recovery
Track for DR readiness:
- Database backup frequency and size
- Time to rebuild flow tables after controller restart
- Failover time for gateway chassis
- Database cluster split-brain detection

### Sample Monitoring Query Library

```promql
# Top 10 ports by packet rate
topk(10, rate(ovs_interface_rx_packets_total[5m]))

# Ports with errors in last hour
increase(ovs_interface_rx_errors_total[1h]) > 0

# Flow cache efficiency by chassis
(1 - rate(ovs_datapath_cache_missed[5m]) / rate(ovs_datapath_cache_lookups[5m])) * 100

# Database operation latency percentiles
histogram_quantile(0.99, rate(ovn_controller_processing_duration_bucket[5m]))

# Tenant isolation verification (should return empty)
rate(ovs_flow_matches{src_tenant!="",dst_tenant!="",src_tenant!=dst_tenant}[5m]) > 0

# Tunnel bandwidth utilization
rate(ovs_tunnel_rx_bytes[5m]) * 8 / 1000000  # Mbps

# Control plane message rate
rate(ovn_controller_openflow_messages_total[5m])
```

---

## Conclusion

OVS and OVN together provide a complete SDN solution that abstracts physical network complexity while providing cloud-scale multi-tenancy, security, and performance. The key to successful deployment is understanding the separation between the logical topology (what you want) and the physical implementation (how it's achieved), combined with comprehensive monitoring of both control and data planes.

For cloud providers, OVS/OVN offers the flexibility of software-defined networking with performance approaching hardware switches, especially when combined with DPDK and smart NIC offload. The distributed nature of OVN eliminates traditional SDN controller bottlenecks while maintaining centralized policy definition.