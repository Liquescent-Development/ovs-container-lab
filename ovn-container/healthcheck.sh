#!/bin/bash

# Check if OVS is running
if ! ovs-vsctl show &>/dev/null; then
    echo "OVS is not running"
    exit 1
fi

# Check if OVN Northbound is accessible
if ! ovn-nbctl ls-list &>/dev/null; then
    echo "OVN Northbound is not accessible"
    exit 1
fi

# Check if OVN Southbound is accessible
if ! ovn-sbctl show &>/dev/null; then
    echo "OVN Southbound is not accessible"
    exit 1
fi

# Check if ready flag exists
if [ ! -f /tmp/ovn-ready ]; then
    echo "OVN not ready yet"
    exit 1
fi

echo "OVN is healthy"
exit 0