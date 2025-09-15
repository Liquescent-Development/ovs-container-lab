# Network Configuration System

## Overview

The OVS Container Lab now supports a comprehensive configuration system that allows:
- **Multi-host deployments** with containers spanning across hosts
- **OVN clustering** for high availability
- **Persistent MAC addresses** to survive container restarts
- **Declarative network topology** via YAML configuration
- **Future extensibility** for user-defined layouts

## Setup

The configuration system runs entirely inside the Lima VM, which has all required dependencies pre-installed (Python, PyYAML, etc). No setup is needed on your macOS host.

### Configuration File

The system uses `network-config.yaml` by default. You can specify a different file using the `NETWORK_CONFIG` environment variable when running make commands:

```bash
# Use a custom configuration
NETWORK_CONFIG=network-config-simple.yaml make up

# Or use the default
make up  # Uses network-config.yaml
```

## Configuration Structure

### Hosts
Define physical or virtual hosts that run OVS/OVN:

```yaml
hosts:
  host-1:
    chassis_name: chassis-host-1
    management_ip: 192.168.100.10
    tunnel_ip: 192.168.100.10      # GENEVE endpoint
    location: datacenter-1
    zone: us-west-1a
    type: lima-vm  # physical, vm, lima-vm, docker-host
    roles:
      - ovn-central     # Participates in OVN cluster
      - ovn-controller  # Runs ovn-controller
      - gateway        # Can provide external connectivity
```

### OVN Clustering
Configure RAFT-based clustering for HA:

```yaml
ovn_cluster:
  northbound:
    cluster_name: OVN_Northbound
    port: 6641
    raft_port: 6643
    nodes:
      - host: host-1
        priority: 100  # Leader election priority
        address: 192.168.100.10
```

### VPCs
Define Virtual Private Clouds:

```yaml
vpcs:
  vpc-a:
    tenant: tenant-1
    cidr: 10.0.0.0/16
    spanning_hosts: all  # or specific host list
    router:
      name: lr-vpc-a
      mac: "00:00:00:01:00:00"
      ha_chassis_group:  # For HA
        name: ha-group-vpc-a
        members:
          - chassis: chassis-host-1
            priority: 100
```

### Containers
Define containers with persistent MACs and placement:

```yaml
containers:
  vpc-a-web-1:
    host: host-1           # Placement constraint
    vpc: vpc-a
    switch: ls-vpc-a-web
    ip: 10.0.1.10
    mac: "02:00:00:01:01:10"  # Persistent MAC
    tier: web
    scheduling:
      anti_affinity:       # Don't place with these
        - vpc-a-web-2
```

## Usage

### Validate Configuration

```bash
# The configuration is automatically validated when running make commands
# To explicitly validate:
make status  # Shows current configuration status
```

### Show Configuration

```bash
# View OVN configuration
make show-ovn

# View container status
make status
```

### Apply Configuration

The configuration is automatically loaded and applied during normal operations:

```bash
# Setup entire stack with configuration
NETWORK_CONFIG=network-config-simple.yaml make up

# Reconcile containers with configured MACs
NETWORK_CONFIG=network-config-simple.yaml make reconcile

# Bind containers using MACs from config
NETWORK_CONFIG=network-config-simple.yaml make attach
```

## Key Features

### 1. Persistent MAC Addresses
- MACs are defined in configuration and preserved across container restarts
- Reconciler uses configured MACs when reconnecting containers
- Prevents ARP cache issues and connection drops

### 2. Multi-Host Support
- Containers can span multiple hosts
- GENEVE tunnels automatically configured between hosts
- VPCs can be distributed or localized

### 3. High Availability
- OVN clustering with RAFT consensus
- HA chassis groups for routers
- Multiple NAT gateways with failover

### 4. Chaos Testing Ready
- Predefined chaos scenarios in config
- Target specific hosts or datacenters
- Simulate partitions, failures, and degradation

## Example: Single-Host Development

For local development, use a simplified config:

```yaml
hosts:
  local:
    chassis_name: chassis-local
    management_ip: 127.0.0.1
    tunnel_ip: 127.0.0.1
    type: lima-vm
    roles:
      - ovn-central
      - ovn-controller
      - gateway

vpcs:
  vpc-a:
    tenant: tenant-1
    cidr: 10.0.0.0/16
    spanning_hosts: [local]
    # ... rest of VPC config

containers:
  vpc-a-web:
    host: local
    vpc: vpc-a
    switch: ls-vpc-a-web
    ip: 10.0.1.10
    mac: "02:00:00:01:01:10"
```

## Example: Multi-Host Production

For production with multiple hosts:

```yaml
hosts:
  prod-host-1:
    chassis_name: chassis-prod-1
    management_ip: 10.100.0.10
    tunnel_ip: 10.100.0.10
    location: datacenter-east
    zone: us-east-1a
    type: physical
    roles:
      - ovn-central
      - ovn-controller
      - gateway

  prod-host-2:
    chassis_name: chassis-prod-2
    management_ip: 10.100.0.11
    tunnel_ip: 10.100.0.11
    location: datacenter-east
    zone: us-east-1b
    type: physical
    roles:
      - ovn-central
      - ovn-controller
      - gateway

  prod-host-3:
    chassis_name: chassis-prod-3
    management_ip: 10.100.0.12
    tunnel_ip: 10.100.0.12
    location: datacenter-west
    zone: us-west-1a
    type: physical
    roles:
      - ovn-central
      - ovn-controller
      - gateway

# OVN cluster across all three hosts
ovn_cluster:
  northbound:
    nodes:
      - host: prod-host-1
        priority: 100
      - host: prod-host-2
        priority: 90
      - host: prod-host-3
        priority: 80
```

## Troubleshooting

### Config Not Loading
```bash
# Check if config file exists
ls -la network-config.yaml

# Validate YAML syntax (run from Lima VM)
limactl shell ovs-lab -- python3 -c "import yaml; yaml.safe_load(open('/home/lima/code/ovs-container-lab/network-config.yaml'))"

# Check which config is being used
echo $NETWORK_CONFIG  # Shows which config file is set
```

### MAC Address Issues
```bash
# Check configured MAC
python3 orchestrator.py config show | grep -A1 "container-name"

# Verify MAC on interface
docker exec container-name ip link show eth1
```

### Multi-Host Connectivity
```bash
# Check GENEVE tunnels
ovs-vsctl show | grep -A3 geneve

# Verify chassis registration
ovn-sbctl show

# Test tunnel connectivity
ping -c 1 <remote-tunnel-ip>
```

## Future Enhancements

1. **Dynamic Provisioning**: Auto-generate containers from config
2. **State Synchronization**: Sync runtime state back to config
3. **Template Support**: Use Jinja2 templates for config generation
4. **REST API**: Expose configuration via API for automation
5. **Kubernetes Integration**: Generate K8s manifests from config