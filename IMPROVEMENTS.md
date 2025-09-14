* ~~Make ovs_exporter work with a database of account and vpc to ovs interface and vpc mapping so that we can add labels to the metrics and show them per account and per vpc~~
* Improve traffic generation and chaos testing
* Integrate ovn_exporter for OVN metrics
* Create multi-tenant grafana dashbaord which shows all the important things grouped by tenant
    * Dashboard for the Host metrics
    * Dashboard for OVS and OVN Control Plane metrics
    * Dashboard for OVS and OVN Data Plane metrics
      * Router metrics
      * Virtual Switch metrics
      * Bridge metrics
      * Container network metrics
      * Interface metrics
      * Network metrics (e.g. transit, vpc networks, external)
      * Where it makes sense they should be associated with both their VPC and the tenant id that owns them
* Add support for adding a second VM that represents another compute node essentially that is a part of VPC A and VPC B

Excellent find! The OVN BGP Agent from OpenStack is exactly what would make this architecture production-ready. Looking at that project:

  OVN BGP Agent - Perfect Solution

  The OVN BGP Agent is a Python daemon that:
  - Watches OVN databases for network changes
  - Announces routes via BGP using FRR
  - Designed for production OpenStack deployments
  - Handles dynamic route advertisement automatically

  How We Could Integrate It:

  1. Architecture with OVN BGP Agent

  Internet
      ↓
  BGP Router (FRR Container)
      ├── BGP Peer: nat-gateway-a
      │   ├── Advertises: 10.0.0.0/16
      │   └── Learns: 0.0.0.0/0
      │
      └── BGP Peer: nat-gateway-b
          ├── Advertises: 10.1.0.0/16
          └── Learns: 0.0.0.0/0

  OVN BGP Agent Container
      ├── Watches: OVN Northbound DB
      ├── Controls: FRR daemon
      └── Advertises: VPC routes dynamically

  2. Implementation Steps

  # docker-compose.yml addition
  ovn-bgp-agent:
    build: ./ovn-bgp-agent
    container_name: ovn-bgp-agent
    privileged: true
    network_mode: host  # Needs host networking for BGP
    volumes:
      - /var/run/openvswitch:/var/run/openvswitch
    environment:
      - OVN_NB_CONNECTION=tcp:127.0.0.1:6641
      - BGP_AS=65001
      - BGP_ROUTER_ID=192.168.100.5

  3. OVN BGP Agent Dockerfile

  FROM ubuntu:22.04

  RUN apt-get update && apt-get install -y \
      python3-pip \
      frr \
      frr-pythontools

  RUN pip3 install ovn-bgp-agent

  COPY bgp-agent.conf /etc/ovn-bgp-agent/
  CMD ["ovn-bgp-agent", "--config-file=/etc/ovn-bgp-agent/bgp-agent.conf"]

  4. Configuration (bgp-agent.conf)

  [DEFAULT]
  debug = true
  ovsdb_connection = unix:/var/run/openvswitch/db.sock
  ovn_nb_connection = tcp:127.0.0.1:6641

  [BGP]
  bgp_as = 65001
  bgp_router_id = 192.168.100.5

  [AGENT]
  driver = ovn_bgp_driver
  # Advertise networks with specific external_ids
  expose_tenant_networks = true
  expose_ipv6_gua_tenant_networks = false

  5. Benefits Over Static Routes

  - Zero-touch subnet addition - Add a new subnet in OVN, it's automatically advertised
  - High availability ready - Can run multiple BGP agents
  - Production proven - Used in real OpenStack clouds
  - Tenant isolation - Can advertise routes per tenant
  - Dynamic failover - BGP handles path selection

  6. What This Enables

  With OVN BGP Agent, you could:
  - Add new VPCs without touching NAT Gateway configs
  - Add new subnets that are instantly routable
  - Simulate cloud provider BGP (like AWS Direct Connect)
  - Multi-region connectivity via BGP peering
  - Anycast services across VPCs

  7. Realistic Cloud Simulation

  This would make your lab mirror real cloud providers:
  - AWS: VPCs with NAT Gateways + Transit Gateway with BGP
  - Azure: VNets with NAT Gateways + Route Server with BGP
  - GCP: VPCs with Cloud NAT + Cloud Router with BGP

  The OVN BGP Agent essentially turns OVN into a cloud-native routing platform. Instead of static routes, you get the same dynamic routing that powers real
  cloud infrastructure.

  This would be a fantastic addition to IMPROVEMENTS.md - implementing proper BGP-based routing would make this lab enterprise-grade and much more
  educational for understanding real cloud networking!

Current vs Real Cloud Architecture

  What We Have Now:

  - Single shared NAT Gateway for all VPCs (anti-pattern)
  - Static routes hardcoded in the NAT Gateway
  - Single point of failure for all external traffic

  Real Cloud Architecture:

  - One NAT Gateway per VPC (or per availability zone)
  - Dynamic routing via BGP/OSPF to learn VPC routes
  - Isolated failure domains - one VPC's NAT failure doesn't affect others

  How I Would Implement This:

  1. Separate NAT Gateways per VPC

  # docker-compose.yml
  nat-gateway-a:
    build: ./nat-gateway
    container_name: nat-gateway-a
    hostname: nat-gw-a
    networks:
      - default  # For internet
    environment:
      - VPC_ID=vpc-a
      - ROUTER_ID=10.0.255.1
      - VPC_CIDR=10.0.0.0/16

  nat-gateway-b:
    build: ./nat-gateway
    container_name: nat-gateway-b
    hostname: nat-gw-b
    networks:
      - default  # For internet
    environment:
      - VPC_ID=vpc-b
      - ROUTER_ID=10.1.255.1
      - VPC_CIDR=10.1.0.0/16

  2. Add NAT Gateway Subnets to Each VPC

  # In orchestrator.py
  self._create_logical_switch("ls-vpc-a-nat", "10.0.255.0/24", tenant_id="tenant-1", vpc_id="vpc-a", tier="nat")
  self._create_logical_switch("ls-vpc-b-nat", "10.1.255.0/24", tenant_id="tenant-2", vpc_id="vpc-b", tier="nat")

  3. Enable FRR with OSPF in NAT Gateways

  # /etc/frr/frr.conf in NAT Gateway
  router ospf
   ospf router-id 10.0.255.1
   network 10.0.0.0/16 area 0
   network 192.168.100.0/24 area 0
   passive-interface eth0  # Don't advertise to internet
  !

  4. Configure OVN Gateway Router for OSPF

  Since OVN doesn't directly support OSPF, we'd need to:
  - Create a "routing" container that bridges OVN and FRR
  - OR use OVN's BGP capabilities (experimental but available)

  5. Architecture Would Look Like:

  Internet
      ↓
  Docker Bridge Network
      ├── nat-gateway-a (10.0.255.1)
      │   ↓ OSPF
      │   lr-vpc-a ← Learns routes dynamically
      │   ├── Web (10.0.1.0/24)
      │   ├── App (10.0.2.0/24)
      │   └── DB  (10.0.3.0/24)
      │
      └── nat-gateway-b (10.1.255.1)
          ↓ OSPF
          lr-vpc-b ← Learns routes dynamically
          ├── Web (10.1.1.0/24)
          ├── App (10.1.2.0/24)
          └── DB  (10.1.3.0/24)

  6. Benefits of This Approach:

  - Isolation: VPC-A NAT failure doesn't affect VPC-B
  - Dynamic: Add new subnets without updating NAT configs
  - Realistic: Matches AWS/Azure/GCP patterns
  - Scalable: Each VPC can scale independently
  - BGP Ready: Could peer with external networks

  7. Implementation Complexity:

  The main challenge is that OVN logical routers don't directly speak OSPF/BGP. We'd need either:
  - Option A: Bridge containers that translate between OVN and FRR
  - Option B: Use OVN's experimental BGP support
  - Option C: Run FRR inside the OVN chassis container (complex)

  This would make the lab much more realistic for enterprise scenarios where dynamic routing is essential. The current static route approach works for a lab
   but wouldn't scale in production.


Complete External Networking Architecture Plan

  Current State Analysis

  1. VPC Containers → Connected to OVN logical switches (ls-vpc-a-, ls-vpc-b-)
  2. OVN Logical Routers → lr-vpc-a, lr-vpc-b, lr-gateway
  3. Transit Network → ls-transit (192.168.100.0/24) connecting all routers
  4. NAT Gateway Container → Has two interfaces:
    - eth0: Docker default network (has internet access)
    - eth1: Docker transit-overlay network (192.168.100.254)
  5. Problem: NAT Gateway on Docker network ≠ OVN logical network

  Required Components for External Networking

  1. Network Topology

  [VPC Containers] → [OVN Logical Network] → [Transit Network] → [NAT Gateway] → [Internet]

  2. Connection Requirements

  A. NAT Gateway Integration

  - Option 1: Connect NAT Gateway to OVN via OVS
    - NAT Gateway needs eth2 interface connected to OVS br-int
    - Create OVN logical port for NAT Gateway on ls-transit
    - Bind the logical port to the physical interface
  - Option 2: Bridge OVN to Docker Network
    - Create a bridge between OVN transit network and Docker transit-overlay
    - Use OVN gateway port on a chassis

  B. Routing Configuration

  1. OVN Routes:
    - VPC routers → Default route to lr-gateway
    - lr-gateway → Default route to NAT Gateway (192.168.100.254)
  2. NAT Gateway Routes:
    - Static routes for 10.0.0.0/16 → 192.168.100.10 (VPC-A router)
    - Static routes for 10.1.0.0/16 → 192.168.100.20 (VPC-B router)
  3. NAT Rules:
    - MASQUERADE for 10.0.0.0/16 → eth0 (internet)
    - MASQUERADE for 10.1.0.0/16 → eth0 (internet)

  C. Interface Configuration

  1. NAT Gateway needs:
    - eth0: External/Internet (Docker default network)
    - eth1: Management/Transit (Docker transit-overlay)
    - eth2: OVN connection (connected to OVS br-int)
  2. OVS/OVN Configuration:
    - br-int with netdev datapath
    - Logical switch port on ls-transit for NAT Gateway
    - Port binding between logical and physical

  Implementation Plan

  Step 1: Modify NAT Gateway Container

  - Start with network_mode: none
  - Manually attach to Docker networks after start
  - Connect to OVS using ovs-docker

  Step 2: Update docker-compose.yml

  nat-gateway:
    network_mode: none  # We'll manually manage networks
    # Rest of config...

  Step 3: Update orchestrator.py

  - Add function to setup NAT Gateway networking:
    a. Attach NAT Gateway to Docker default network for internet
    b. Attach NAT Gateway to Docker transit-overlay for management
    c. Connect NAT Gateway to OVS br-int with ovs-docker
    d. Bind OVN logical port to the OVS interface

  Step 4: Update NAT Gateway entrypoint.sh

  - Wait for all interfaces to be available
  - Configure routing table with proper metrics
  - Setup NAT rules for the correct interfaces

  Step 5: Testing Strategy

  1. Test NAT Gateway can reach internet
  2. Test VPC containers can reach NAT Gateway
  3. Test VPC containers can reach internet via NAT Gateway

  Clean Implementation (No Hacks)