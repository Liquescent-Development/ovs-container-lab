#!/bin/bash

CONTAINER_NAME=$1
BRIDGE_NAME=${2:-ovs-br0}

if [ -z "$CONTAINER_NAME" ]; then
    echo "Usage: $0 <container_name> [bridge_name]"
    echo "Example: $0 test1"
    echo "Example: $0 test1 ovs-br0"
    exit 1
fi

# Check if OVS container is running
if ! docker inspect ovs >/dev/null 2>&1; then
    echo "OVS container not found. Please run: docker-compose up -d ovs"
    exit 1
fi

echo "Disconnecting $CONTAINER_NAME from OVS bridge $BRIDGE_NAME..."

# Run all operations inside the OVS container
docker exec ovs bash -c "
    # Find interfaces for this container using metadata (matches connect script approach)
    EXISTING_PORTS=\$(ovs-vsctl --data=bare --no-heading --columns=name find interface external_ids:container_id='$CONTAINER_NAME' 2>/dev/null || true)
    
    if [ -z \"\$EXISTING_PORTS\" ]; then
        echo 'No OVS interfaces found for container $CONTAINER_NAME'
        echo 'Container may not be connected to OVS or already disconnected'
        exit 0
    fi
    
    # Remove each interface associated with this container
    for port in \$EXISTING_PORTS; do
        if [ -n \"\$port\" ]; then
            echo 'Removing interface \$port from OVS bridge...'
            ovs-vsctl del-port $BRIDGE_NAME \"\$port\" 2>/dev/null || true
            
            # Remove veth pair if it exists (this also removes the peer in the container)
            if ip link show \"\$port\" &>/dev/null; then
                echo 'Removing veth pair \$port...'
                ip link delete \"\$port\" 2>/dev/null || true
            fi
        fi
    done
    
    echo 'Cleanup complete for container $CONTAINER_NAME'
" || {
    echo "Warning: Some cleanup operations may have failed"
}

echo "Disconnected container $CONTAINER_NAME from $BRIDGE_NAME"