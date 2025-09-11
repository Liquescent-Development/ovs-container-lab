#!/bin/bash

# Health check script for OVS container
# Returns 0 if healthy, 1 if unhealthy

# Check if readiness file exists
if [ ! -f /tmp/ovs-ready ]; then
    echo "UNHEALTHY: OVS not ready (no readiness indicator)"
    exit 1
fi

# Check if OVS database is accessible
if ! ovs-vsctl --timeout=3 show >/dev/null 2>&1; then
    echo "UNHEALTHY: Cannot connect to OVS database"
    exit 1
fi

# Check if the bridge exists
BRIDGE_NAME=${OVS_BRIDGE_NAME:-ovs-br0}
if ! ovs-vsctl --timeout=3 br-exists "$BRIDGE_NAME" 2>/dev/null; then
    echo "UNHEALTHY: Bridge $BRIDGE_NAME does not exist"
    exit 1
fi

# Check bridge datapath type (should be netdev for userspace)
DATAPATH_TYPE=$(ovs-vsctl --timeout=3 get bridge "$BRIDGE_NAME" datapath_type 2>/dev/null | tr -d '"')
if [ "$DATAPATH_TYPE" != "netdev" ]; then
    echo "WARNING: Bridge $BRIDGE_NAME is not using userspace datapath (datapath_type=$DATAPATH_TYPE)"
fi

# Check if we can query flows (OpenFlow is working)
if ! ovs-ofctl -O OpenFlow13 dump-flows "$BRIDGE_NAME" >/dev/null 2>&1; then
    echo "WARNING: Cannot query OpenFlow rules - OpenFlow may not be working properly"
    # Don't fail immediately as this might be transient
fi

# Check if processes are running
if ! pgrep -x ovsdb-server >/dev/null; then
    echo "UNHEALTHY: ovsdb-server is not running"
    exit 1
fi

if ! pgrep -x ovs-vswitchd >/dev/null; then
    echo "UNHEALTHY: ovs-vswitchd is not running"
    exit 1
fi

echo "HEALTHY: All OVS components operational"
exit 0