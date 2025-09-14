#!/bin/bash
set -e

echo "Starting NAT Gateway with FRR..."

# Enable IP forwarding
echo 1 > /proc/sys/net/ipv4/ip_forward
sysctl -w net.ipv4.ip_forward=1

# Wait for network interfaces to be ready
echo "Waiting for network interfaces..."
for i in {1..30}; do
    if ip link show eth0 &>/dev/null && ip link show eth1 &>/dev/null; then
        echo "All interfaces are ready"
        break
    fi
    echo "Waiting for interfaces... (attempt $i/30)"
    sleep 2
done

# Get interface information
echo "Network interfaces:"
ip addr show

# Setup NAT for VPC subnets to external network
# eth0 = external/internet (Docker bridge network)
# eth1 = OVN transit network (OVS connection)
echo "Configuring NAT rules..."

# Only add NAT rules if eth0 exists (external interface)
if ip link show eth0 &>/dev/null; then
    # NAT for VPC-A
    iptables -t nat -A POSTROUTING -s 10.0.0.0/16 -o eth0 -j MASQUERADE
    # NAT for VPC-B
    iptables -t nat -A POSTROUTING -s 10.1.0.0/16 -o eth0 -j MASQUERADE
    echo "NAT rules added for VPC subnets"
fi

# Allow forwarding between OVN network (eth1) and external (eth0)
if ip link show eth0 &>/dev/null && ip link show eth1 &>/dev/null; then
    iptables -A FORWARD -i eth1 -o eth0 -j ACCEPT
    iptables -A FORWARD -i eth0 -o eth1 -m state --state RELATED,ESTABLISHED -j ACCEPT
    echo "Forwarding rules added between eth1 and eth0"
fi

# Add static routes for VPCs
# These route through the OVN gateway router on the transit network
if ip link show eth1 &>/dev/null; then
    # Wait for eth1 to get an IP
    for i in {1..10}; do
        if ip addr show eth1 | grep -q "192.168.100.254"; then
            break
        fi
        sleep 1
    done

    # Add routes for VPC subnets via OVN gateway
    ip route add 10.0.0.0/16 via 192.168.100.1 dev eth1 2>/dev/null || true
    ip route add 10.1.0.0/16 via 192.168.100.1 dev eth1 2>/dev/null || true
    echo "Routes added for VPC subnets"
fi

echo "NAT rules configured:"
iptables -t nat -L POSTROUTING -n -v

echo "Routing table:"
ip route

echo "NAT Gateway is ready"

# Keep container running
echo "NAT Gateway running. Monitoring network..."
while true; do
    sleep 60
    echo "$(date): NAT Gateway healthy - Interfaces: $(ip link | grep -E "eth[0-9]:" | wc -l), NAT rules: $(iptables -t nat -L POSTROUTING -n | grep MASQUERADE | wc -l)"
done