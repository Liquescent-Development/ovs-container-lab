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



⏺ Bash(limactl shell ovs-lab -- sudo ovs-vsctl -- del-port br-int veth-tg-a -- add-port br-int veth-tg-a -- set Interface veth-tg-a
      external_ids:iface-id=lsp-traffic-g…)
  ⎿  bash: line 1: cd: /Users/kiener/code/ovs-container-lab: No such file or directory
     bash: line 1: cd: /Users/kiener: No such file or directory

⏺ Now test TCP again:

⏺ Bash(limactl shell ovs-lab -- sudo docker exec traffic-gen-a curl -v --connect-timeout 2 http://10.0.1.10 2>&1 | head -10)
  ⎿  bash: line 1: cd: /Users/kiener/code/ovs-container-lab: No such file or directory
     bash: line 1: cd: /Users/kiener: No such file or directory
     *   Trying 10.0.1.10:80...
     … +8 lines (ctrl+o to expand)

⏺ Still failing. The fundamental issue is that TCP packets are entering OVS but with the wrong metadata/flow mapping. Let me check what the metadata values
  mean:

⏺ Bash(limactl shell ovs-lab -- sudo docker exec ovn-central ovn-sbctl list Datapath_Binding | grep -E "tunnel_key|external_ids" | head -10)
  ⎿  external_ids        : {logical-switch="dab43cfa-14c0-4838-bd44-9786c21ba4f7", name=ls-vpc-a-db}
     tunnel_key          : 6
     external_ids        : {logical-switch="9d040d9d-dac2-4ad3-8014-434275ecbca6", name=ls-vpc-a-app}
     … +9 lines (ctrl+o to expand)

⏺ The port 9 flow has metadata 0x7 which would be tunnel_key 7. Let me find what that is:

⏺ Bash(limactl shell ovs-lab -- sudo docker exec ovn-central ovn-sbctl list Datapath_Binding | grep -B1 "tunnel_key.*: 7")
  ⎿  load_balancers      : []
     tunnel_key          : 7
     bash: line 1: cd: /Users/kiener/code/ovs-container-lab: No such file or directory
     bash: line 1: cd: /Users/kiener: No such file or directory

⏺ Let me get more context:

⏺ Bash(limactl shell ovs-lab -- sudo docker exec ovn-central ovn-sbctl find Datapath_Binding tunnel_key=7 | grep -E "external_ids|tunnel_key")
  ⎿  external_ids        : {logical-switch="0ff35410-2f67-47f5-9f2b-d5814be48151", name=ls-vpc-a-test}
     tunnel_key          : 7
     bash: line 1: cd: /Users/kiener/code/ovs-container-lab: No such file or directory
     bash: line 1: cd: /Users/kiener: No such file or directory

⏺ Good! Metadata 0x7 is ls-vpc-a-test which is correct for traffic-gen-a. So the packets ARE entering the correct logical switch. The issue must be in the
  subsequent flow tables.

  Let me trace what happens after table 8:

⏺ Bash(limactl shell ovs-lab -- sudo ovs-ofctl dump-flows br-int table=8 | grep "metadata=0x7" | head -5)
  ⎿  cookie=0x832e7e9c, duration=318.993s, table=8, n_packets=0, n_bytes=0, idle_age=318, priority=120,icmp6,reg10=0x10000/0x10000,metadata=0x7,dl_dst=00:0
    0:00:01:04:01,icmp_type=2,icmp_code=0 actions=push:NXM_NX_REG14[],push:NXM_NX_REG15[],pop:NXM_NX_REG14[],pop:NXM_NX_REG15[],resubmit(,35)
     cookie=0x832e7e9c, duration=318.993s, table=8, n_packets=0, n_bytes=0, idle_age=318, priority=120,icmp,reg10=0x10000/0x10000,metadata=0x7,dl_dst=00:00
    … +8 lines (ctrl+o to expand)



⏺ These are ICMP flows. Let me check for generic flows:

⏺ Bash(limactl shell ovs-lab -- sudo ovs-ofctl dump-flows br-int table=8 | grep -v "icmp" | grep "metadata=0x7" | head -5)
  ⎿  cookie=0x9ddcf9ad, duration=326.498s, table=8, n_packets=0, n_bytes=0, idle_age=326, priority=100,metadata=0x7,vlan_tci=0x1000/0x1000 actions=drop
     cookie=0x36c80c7f, duration=326.498s, table=8, n_packets=0, n_bytes=0, idle_age=326, priority=100,metadata=0x7,dl_src=01:00:00:00:00:00/01:00:00:00:00
    :00 actions=drop
    … +4 lines (ctrl+o to expand)


⏺ Good! The priority=50 flow has 8 packets (our TCP packets). They're going to table 73 then table 9. Let me check what's in table 9:

⏺ Bash(limactl shell ovs-lab -- sudo ovs-ofctl dump-flows br-int table=9 | grep "n_packets=[1-9]" | grep "metadata=0x7" | head -3)
  ⎿   cookie=0x17193873, duration=334.412s, table=9, n_packets=8, n_bytes=456, idle_age=42, priority=0,metadata=0x7 actions=resubmit(,10)
     bash: line 1: cd: /Users/kiener/code/ovs-container-lab: No such file or directory
     bash: line 1: cd: /Users/kiener: No such file or directory

⏺ Table 9 sends to table 10. Let me continue tracing:

⏺ Bash(limactl shell ovs-lab -- sudo ovs-ofctl dump-flows br-int table=10 | grep "metadata=0x7" | grep -E "tcp|ip" | head -5)
  ⎿  bash: line 1: cd: /Users/kiener/code/ovs-container-lab: No such file or directory
     bash: line 1: cd: /Users/kiener: No such file or directory

⏺ No matches. Let me check all table 10 flows with packets:

⏺ Bash(limactl shell ovs-lab -- sudo ovs-ofctl dump-flows br-int table=10 | grep "n_packets=[1-9]" | grep "metadata=0x7" | head -3)
  ⎿   cookie=0xf9d4e7fc, duration=347.300s, table=10, n_packets=8, n_bytes=456, idle_age=55, priority=0,metadata=0x7 actions=resubmit(,11)
     bash: line 1: cd: /Users/kiener/code/ovs-container-lab: No such file or directory
     bash: line 1: cd: /Users/kiener: No such file or directory

⏺ To table 11. This is getting tedious. Let me check where the packets are being dropped by looking for the last table with packet hits:

⏺ Bash(limactl shell ovs-lab -- sudo ovs-ofctl dump-flows br-int | grep "metadata=0x7" | grep "n_packets=[1-9]" | tail -5)
  ⎿  cookie=0x15799b76, duration=354.297s, table=51, n_packets=8, n_bytes=456, idle_age=62, priority=0,metadata=0x7 actions=load:0->NXM_NX_REG10[12],resubm
    it(,75),move:NXM_NX_REG10[12]->NXM_NX_XXREG0[111],resubmit(,52)
     cookie=0x52bbc902, duration=354.297s, table=52, n_packets=8, n_bytes=456, idle_age=62, priority=0,metadata=0x7 actions=resubmit(,64)
    … +9 lines (ctrl+o to expand)


⏺ Interesting! Table 65 shows:
  - 3 packets with reg15=0x2 go to output:9 (back to port 9, which is veth-tg-a - these are probably ICMP)
  - 5 packets with reg15=0x1 go to a complex clone action that resubmits to table 8 with metadata=0x2

  Metadata 0x2 is lr-vpc-a (the VPC-A router). So the packets ARE being forwarded to the logical router! But then they're not making it through.

  Let me check what happens in the router (metadata=0x2):

⏺ Bash(limactl shell ovs-lab -- sudo ovs-ofctl dump-flows br-int | grep "metadata=0x2" | grep "n_packets=[1-9]" | grep -E "tcp|ip" | head -5)
  ⎿  cookie=0xf08324bb, duration=366.660s, table=21, n_packets=5, n_bytes=330, idle_age=79, priority=74,ip,metadata=0x2,nw_dst=10.0.1.0/24 actions=dec_ttl(
    ),load:0->OXM_OF_PKT_REG4[32..47],move:NXM_OF_IP_DST[]->NXM_NX_XXREG0[96..127],load:0xa000101->NXM_NX_XXREG0[64..95],mod_dl_src:00:00:00:01:01:01,load:
    0x1->NXM_NX_REG15[],load:0x1->NXM_NX_REG10[0],resubmit(,22)
    … +2 lines (ctrl+o to expand)



⏺ Good! The router IS routing the packets to 10.0.1.0/24 (5 packets)! It's decrementing TTL, setting the source MAC to 00:00:00:01:01:01 (router MAC), and
  going to table 22. The packets are being routed correctly!

  Let me continue following the flow through the egress pipeline. The packets should now enter ls-vpc-a-web (metadata should change to the web switch). Let
  me check if they reach the web switch:

⏺ Bash(limactl shell ovs-lab -- sudo docker exec ovn-central ovn-sbctl find Datapath_Binding name=ls-vpc-a-web | grep tunnel_key)
  ⎿  bash: line 1: cd: /Users/kiener/code/ovs-container-lab: No such file or directory
     bash: line 1: cd: /Users/kiener: No such file or directory
     ovn-sbctl: Datapath_Binding does not contain a column whose name matches "name"

⏺ Bash(limactl shell ovs-lab -- sudo docker exec ovn-central ovn-sbctl list Datapath_Binding | grep -A1 "ls-vpc-a-web" | grep tunnel_key)
  ⎿  bash: line 1: cd: /Users/kiener/code/ovs-container-lab: No such file or directory
     bash: line 1: cd: /Users/kiener: No such file or directory

⏺ Let me trace where the packets go after routing. From table 21, they went to table 22:

⏺ Bash(limactl shell ovs-lab -- sudo ovs-ofctl dump-flows br-int table=22 | grep "metadata=0x2" | grep "n_packets=[1-9]" | head -3)
  ⎿   cookie=0xb1695ba5, duration=391.238s, table=22, n_packets=5, n_bytes=330, idle_age=104, priority=150,reg8=0/0xffff,metadata=0x2 actions=resubmit(,23)
     bash: line 1: cd: /Users/kiener/code/ovs-container-lab: No such file or directory
     bash: line 1: cd: /Users/kiener: No such file or directory

⏺ Table 23. Let me skip ahead and see where they end up:

⏺ Bash(limactl shell ovs-lab -- sudo ovs-ofctl dump-flows br-int | grep "metadata=0x2" | grep "n_packets=5" | tail -3)
  ⎿  cookie=0x42cffaf7, duration=397.283s, table=48, n_packets=5, n_bytes=330, idle_age=110, priority=100,reg15=0x1,metadata=0x2 actions=resubmit(,64)
     cookie=0x77af33d4, duration=397.282s, table=64, n_packets=5, n_bytes=330, idle_age=110, priority=100,reg10=0x1/0x1,reg15=0x1,metadata=0x2 actions=push
    :NXM_OF_IN_PORT[],load:0xffff->NXM_OF_IN_PORT[],resubmit(,65),pop:NXM_OF_IN_PORT[]
    … +7 lines (ctrl+o to expand)


⏺ Table 65 again! This time it's changing metadata from 0x2 (router) to 0x4. Let me check what metadata 0x4 is:

⏺ Bash(limactl shell ovs-lab -- sudo docker exec ovn-central ovn-sbctl find Datapath_Binding tunnel_key=4 | grep external_ids)
  ⎿  external_ids        : {logical-switch="dd4dabaa-300d-4887-b59f-48dcaa5d9f01", name=ls-vpc-a-web}
     bash: line 1: cd: /Users/kiener/code/ovs-container-lab: No such file or directory
     bash: line 1: cd: /Users/kiener: No such file or directory

⏺ Perfect! Metadata 0x4 is ls-vpc-a-web. So the packets ARE entering the web switch! Now let me check if they're reaching the output stage:

⏺ Bash(limactl shell ovs-lab -- sudo ovs-ofctl dump-flows br-int | grep "metadata=0x4" | grep "n_packets=[1-9]" | tail -5)
  ⎿  cookie=0xba59a384, duration=413.415s, table=49, n_packets=5, n_bytes=330, idle_age=126, priority=0,metadata=0x4 actions=resubmit(,50)
     cookie=0x5004adc9, duration=413.419s, table=50, n_packets=5, n_bytes=330, idle_age=126, priority=0,metadata=0x4 actions=resubmit(,51)
     cookie=0x15799b76, duration=413.415s, table=51, n_packets=5, n_bytes=330, idle_age=126, priority=0,metadata=0x4 actions=load:0->NXM_NX_REG10[12],resub
    … +5 lines (ctrl+o to expand)


⏺ FINALLY! Table 65 shows output:3 - the packets are being sent to port 3! Let me check what port 3 is:

⏺ Bash(limactl shell ovs-lab -- sudo ovs-ofctl show br-int | grep "^\s*3(")
  ⎿   3(veth-vpc-a-we): addr:b2:e2:33:4f:4d:2c
     bash: line 1: cd: /Users/kiener/code/ovs-container-lab: No such file or directory
     bash: line 1: cd: /Users/kiener: No such file or directory


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