# Missing Metrics for OVS Exporter

This document outlines metrics that could be added to the upstream OVS exporter to better support multi-VPC OVN deployments and provide more comprehensive monitoring capabilities.

## Current Metrics Status

The official OVS exporter (v2.2.0) provides excellent coverage for:
- ✅ **Basic OVS metrics**: Bridges, interfaces, flows, datapath statistics
- ✅ **Interface statistics**: RX/TX packets, bytes, errors, drops (per interface)
- ✅ **GENEVE tunnel detection**: Tunnels are identified with `port_type="geneve"`
- ✅ **Coverage statistics**: Detailed OVS internal event counters
- ✅ **Process metrics**: CPU, memory, file descriptors

## Potentially Missing Metrics

### 1. OVN-Specific Metrics

The current exporter focuses on OVS dataplane metrics but doesn't expose OVN control plane information:

```prometheus
# OVN Logical Topology
ovn_logical_switch_count           # Number of logical switches
ovn_logical_router_count           # Number of logical routers  
ovn_logical_port_count{type="switch"}  # Number of logical switch ports
ovn_logical_port_count{type="router"}  # Number of logical router ports
ovn_chassis_count                  # Number of registered chassis

# OVN Health/Status
ovn_southbound_connection_status{chassis="chassis-name"}  # Per-chassis SB connection
ovn_controller_status{chassis="chassis-name"}           # Per-chassis controller status
```

**Rationale**: In multi-VPC deployments, monitoring the OVN control plane is crucial for detecting misconfigurations, split-brain scenarios, or connectivity issues between chassis.

### 2. Enhanced Tunnel Metrics

While GENEVE tunnels are detected, per-tunnel traffic statistics with remote endpoint information are missing:

```prometheus  
# Per-tunnel traffic with remote endpoint context
ovs_tunnel_rx_packets{tunnel="ovn-abc123-0", remote_ip="192.168.100.20", vpc="vpc-a"}
ovs_tunnel_tx_packets{tunnel="ovn-abc123-0", remote_ip="192.168.100.20", vpc="vpc-a"}
ovs_tunnel_rx_bytes{tunnel="ovn-abc123-0", remote_ip="192.168.100.20", vpc="vpc-a"}
ovs_tunnel_tx_bytes{tunnel="ovn-abc123-0", remote_ip="192.168.100.20", vpc="vpc-a"}

# Tunnel health/status
ovs_tunnel_status{tunnel="ovn-abc123-0", remote_ip="192.168.100.20", status="up|down"}
```

**Rationale**: In multi-VPC scenarios, understanding per-tunnel traffic patterns helps identify inter-VPC communication issues, bandwidth utilization, and network partitions.

### 3. Bridge-Level Aggregations

Currently, metrics are per-interface. Bridge-level aggregations would be valuable:

```prometheus
# Per-bridge aggregated statistics  
ovs_bridge_port_count{bridge="br-int", vpc="vpc-a"}      # Total ports per bridge
ovs_bridge_flow_count{bridge="br-int", vpc="vpc-a"}      # Total flows per bridge
ovs_bridge_rx_packets{bridge="br-int", vpc="vpc-a"}      # Aggregated RX across all ports
ovs_bridge_tx_packets{bridge="br-int", vpc="vpc-a"}      # Aggregated TX across all ports
```

**Rationale**: Provides high-level bridge health without needing to aggregate per-interface metrics in queries.

### 4. VPC Context Labels

Adding VPC context to existing metrics would improve multi-VPC monitoring:

```prometheus
# Enhanced existing metrics with VPC context
ovs_interface_rx_packets{name="vpc-a-web-1", vpc="vpc-a", workload="web"}
ovs_dp_flows{datapath="system@ovs-system", vpc="vpc-a"} 
```

**Rationale**: Enables VPC-scoped dashboards and alerting without complex label parsing.

### 5. Flow Table Metrics

More detailed OpenFlow table information:

```prometheus
# Per-table flow statistics
ovs_flow_table_size{bridge="br-int", table_id="0"}       # Flows in each table
ovs_flow_table_lookups{bridge="br-int", table_id="0"}    # Lookup counters per table  
ovs_flow_table_matches{bridge="br-int", table_id="0"}    # Match counters per table
```

**Rationale**: Helps identify flow table bottlenecks and inefficient flow programming.

## Implementation Approaches

### Option 1: Extend OVS Exporter
- Add OVN database connections to existing exporter
- Implement OVN-specific collectors alongside OVS collectors  
- Add configuration flags for OVN endpoints

### Option 2: Companion OVN Exporter
- Create separate `ovn-exporter` for control plane metrics
- Keep OVS exporter focused on dataplane
- Deploy both exporters in OVN environments

### Option 3: Configuration-Driven Context
- Add configuration file support for VPC/workload label mappings
- Enhance existing metrics with configurable labels
- Maintain backward compatibility

## Data Sources

The missing metrics would primarily come from:

1. **OVN Northbound DB**: `ovn-nbctl` commands for logical topology
2. **OVN Southbound DB**: `ovn-sbctl` commands for chassis/binding status  
3. **OVS Interface Options**: Enhanced parsing of GENEVE tunnel options
4. **OpenFlow Tables**: `ovs-ofctl dump-flows` with table-specific parsing

## Impact Assessment

- **Low Impact**: Bridge-level aggregations, VPC labels (pure additions)
- **Medium Impact**: Enhanced tunnel metrics (new data collection)  
- **High Impact**: OVN metrics (new database connections, dependencies)

## Current Workaround

The custom Python script (`multi-vpc-exporter.py`) demonstrates these missing metrics by:
- Executing `docker exec` commands to collect data
- Parsing JSON output from OVS/OVN CLI tools
- Exposing metrics on port 9476 alongside the official exporter

This approach works but has limitations:
- Requires Docker access and CLI parsing
- Less efficient than native OVSDB connections
- Duplicate metric collection overhead
- Maintenance burden for custom code

## Recommendations

1. **Priority 1**: OVN logical topology metrics (switches, routers, ports)
2. **Priority 2**: Enhanced tunnel metrics with remote endpoint context
3. **Priority 3**: Bridge-level aggregations and VPC label support
4. **Priority 4**: Flow table granularity

Contributing these upstream would benefit the entire OVN community and eliminate the need for custom metric collection scripts.