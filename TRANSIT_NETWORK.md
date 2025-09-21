# Transit Network Architecture

## Overview

The OVS Container Lab now uses a Docker plugin-managed transit network for inter-VPC routing and external connectivity. This eliminates the need for complex orchestration scripts to set up OVN topology.

## Components

### 1. Docker Network Plugin (`ovs-container-network`)
- Creates and manages all OVN logical networks
- Handles transit network with gateway router
- Configures inter-VPC routing automatically
- Manages VPC routers and their connections

### 2. Transit Network
Created as a special Docker network with role=transit:
```yaml
transit-net:
  driver: ovs-container-network:latest
  driver_opts:
    ovn.role: transit
    ovn.switch: ls-transit
    ovn.external_gateway: 192.168.100.254
    ovn.nb_connection: tcp:192.168.100.5:6641
    ovn.sb_connection: tcp:192.168.100.5:6642
```

This automatically:
- Creates `ls-transit` logical switch in OVN
- Creates `lr-gateway` router
- Adds default route to external gateway (NAT gateway at .254)
- Sets up port for NAT gateway with port security disabled

### 3. VPC Networks
Each VPC network connects to transit via `ovn.transit_network` option:
```yaml
vpc-a-web-net:
  driver: ovs-container-network:latest
  driver_opts:
    ovn.switch: ls-vpc-a-web
    ovn.router: lr-vpc-a
    ovn.transit_network: transit-net  # Connects to transit
```

This automatically:
- Creates VPC logical switch
- Creates/reuses VPC router
- Connects VPC router to transit network
- Adds routing for inter-VPC and external traffic

### 4. NAT Gateway
- Container that provides external connectivity
- Connects to both:
  - `default` network for internet access
  - `transit-net` at 192.168.100.254 for internal routing
- Runs iptables MASQUERADE for outbound NAT

## Network Flow

```
Container → VPC Switch → VPC Router → Transit Network → Gateway Router → NAT Gateway → Internet
                            ↓
                     Other VPC Router ← Inter-VPC Traffic
```

## Key Benefits

1. **Simplified Setup**: No need for orchestrator to create OVN topology
2. **Declarative**: Everything defined in docker-compose.yml
3. **Multi-host Ready**: Works across multiple Docker hosts with shared OVN
4. **Production Ready**: Clean separation between network infrastructure and containers

## Files

- `docker-compose.yml` - Main compose file with all network definitions
- `orchestrator-simple.py` - Only handles chassis setup and monitoring
- `ovs-container-network/` - Docker plugin source code

## Troubleshooting

### Check OVN Topology
```bash
docker exec ovn-central ovn-nbctl show
```

### Check Transit Network
```bash
docker exec ovn-central ovn-nbctl lr-route-list lr-gateway
```

### Check VPC Connectivity
```bash
docker exec vpc-a-web ping 10.1.1.10  # Inter-VPC
docker exec vpc-a-web ping 8.8.8.8    # External
```