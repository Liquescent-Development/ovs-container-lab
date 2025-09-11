#!/bin/bash

CONTAINER_NAME=$1
IP_ADDRESS=$2
BRIDGE_NAME=${3:-ovs-br0}

if [ -z "$CONTAINER_NAME" ] || [ -z "$IP_ADDRESS" ]; then
    echo "Usage: $0 <container_name> <ip_address> [bridge_name]"
    exit 1
fi

# Check if container exists and is running
if ! docker inspect $CONTAINER_NAME >/dev/null 2>&1; then
    echo "Container $CONTAINER_NAME not found"
    exit 1
fi

# Get the container PID from the host
TARGET_PID=$(docker inspect -f '{{.State.Pid}}' $CONTAINER_NAME)
if [ -z "$TARGET_PID" ] || [ "$TARGET_PID" = "0" ]; then
    echo "Container $CONTAINER_NAME is not running"
    exit 1
fi

# Check if OVS container is running
if ! docker inspect ovs >/dev/null 2>&1; then
    echo "OVS container not found. Please run: docker-compose up -d ovs"
    exit 1
fi

# Generate unique MAC address based on IP address last octet
LAST_OCTET=$(echo $IP_ADDRESS | cut -d. -f4)
MAC_ADDRESS=$(printf "02:42:ac:12:00:%02x" $LAST_OCTET)

# Create a unique interface name (truncate container name if needed)
VETH_HOST="veth-$(echo $CONTAINER_NAME | cut -c1-8)"

echo "Connecting $CONTAINER_NAME to OVS bridge $BRIDGE_NAME..."

# Run all network operations inside the OVS container
# Pass the PID as a variable so we don't need docker inside the container
docker exec ovs bash -c "
    # Create netns directory and link for container namespace access
    mkdir -p /var/run/netns
    
    # Create namespace link if it doesn't exist
    if [ ! -e /var/run/netns/$TARGET_PID ]; then
        ln -s /proc/$TARGET_PID/ns/net /var/run/netns/$TARGET_PID
    fi
    
    # Generate unique interface names using container name and microsecond timestamp
    INTERFACE_ID=\$(echo '$CONTAINER_NAME' | tr -d '-' | cut -c1-6)\$(date +%s%N | tail -c 6)
    VETH_HOST=\"\${INTERFACE_ID}_l\"
    VETH_CONTAINER=\"\${INTERFACE_ID}_c\"
    
    # Clean up any existing interfaces for this container
    EXISTING_PORTS=\$(ovs-vsctl --data=bare --no-heading --columns=name find interface external_ids:container_id='$CONTAINER_NAME' 2>/dev/null || true)
    for port in \$EXISTING_PORTS; do
        if [ -n \"\$port\" ]; then
            echo 'Cleaning up existing interface \$port'
            ovs-vsctl del-port $BRIDGE_NAME \"\$port\" 2>/dev/null || true
            ip link delete \"\$port\" 2>/dev/null || true
        fi
    done
    
    # Create veth pair
    ip link add \$VETH_HOST type veth peer name \$VETH_CONTAINER || {
        echo 'Failed to create veth pair'
        exit 1
    }
    
    # Move container side to the target container's network namespace
    ip link set \$VETH_CONTAINER netns $TARGET_PID || {
        echo 'Failed to move interface to container namespace'
        ip link delete \$VETH_HOST 2>/dev/null
        rm -f /var/run/netns/$TARGET_PID
        exit 1
    }
    
    # Configure the container's interface using ip netns exec (more reliable than nsenter)
    ip netns exec $TARGET_PID ip link set dev \$VETH_CONTAINER name eth1
    ip netns exec $TARGET_PID ip link set eth1 address $MAC_ADDRESS
    ip netns exec $TARGET_PID ip link set eth1 up
    ip netns exec $TARGET_PID ip addr add $IP_ADDRESS/24 dev eth1
    ip netns exec $TARGET_PID ip route add default via 172.18.0.1 2>/dev/null || true
    
    # Add host side to OVS bridge with container metadata
    ovs-vsctl add-port $BRIDGE_NAME \$VETH_HOST -- set interface \$VETH_HOST external_ids:container_id='$CONTAINER_NAME' external_ids:container_iface='eth1'
    ip link set \$VETH_HOST up
    
    # Clean up namespace link
    rm -f /var/run/netns/$TARGET_PID
    
    echo 'Network configuration complete for container $CONTAINER_NAME'
" || {
    echo "Failed to configure networking for $CONTAINER_NAME"
    exit 1
}

echo "Successfully connected $CONTAINER_NAME to $BRIDGE_NAME with IP $IP_ADDRESS and MAC $MAC_ADDRESS"