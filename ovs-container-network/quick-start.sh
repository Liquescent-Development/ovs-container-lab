#!/bin/bash

# Quick start script for OVS Container Network Plugin
# This script provides a simple way to test the plugin

set -e

PLUGIN_NAME="ovs-container-network"
PLUGIN_TAG="${PLUGIN_TAG:-latest}"
NETWORK_NAME="ovs-demo"
SUBNET="172.30.0.0/24"

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo_info() {
    echo -e "${GREEN}➜${NC} $1"
}

echo_cmd() {
    echo -e "${YELLOW}\$ $1${NC}"
}

clear

echo "╔══════════════════════════════════════════════╗"
echo "║  OVS Container Network Plugin - Quick Start  ║"
echo "╚══════════════════════════════════════════════╝"
echo

echo_info "This script will demonstrate the OVS Container Network Plugin"
echo

# Step 1: Check prerequisites
echo_info "Step 1: Checking prerequisites..."
echo

if ! docker plugin ls | grep -q ${PLUGIN_NAME}; then
    echo "  ⚠️  Plugin not installed. Please run ./install.sh first"
    exit 1
fi

echo "  ✓ Plugin is installed"
echo

# Step 2: Create a network
echo_info "Step 2: Creating an OVS network..."
echo

echo_cmd "docker network create --driver ${PLUGIN_NAME}:${PLUGIN_TAG} --subnet ${SUBNET} ${NETWORK_NAME}"
docker network create --driver ${PLUGIN_NAME}:${PLUGIN_TAG} \
    --subnet ${SUBNET} \
    ${NETWORK_NAME} 2>/dev/null || true

echo "  ✓ Network '${NETWORK_NAME}' created"
echo

# Step 3: Run containers
echo_info "Step 3: Starting containers on the OVS network..."
echo

echo_cmd "docker run -d --name web --network ${NETWORK_NAME} nginx:alpine"
docker run -d --name web --network ${NETWORK_NAME} nginx:alpine 2>/dev/null || true

echo_cmd "docker run -d --name app --network ${NETWORK_NAME} alpine sleep 3600"
docker run -d --name app --network ${NETWORK_NAME} alpine sleep 3600 2>/dev/null || true

echo "  ✓ Containers started"
echo

# Step 4: Test connectivity
echo_info "Step 4: Testing connectivity between containers..."
echo

echo_cmd "docker exec app ping -c 3 web"
docker exec app ping -c 3 web

echo
echo "  ✓ Connectivity verified"
echo

# Step 5: Show OVS configuration
echo_info "Step 5: Inspecting OVS configuration..."
echo

if command -v ovs-vsctl &> /dev/null; then
    echo_cmd "sudo ovs-vsctl show"
    sudo ovs-vsctl show | head -20
    echo "  ..."
else
    echo "  ⚠️  OVS commands not available (install openvswitch-switch)"
fi
echo

# Step 6: Clean up
echo_info "Step 6: Cleaning up demo resources..."
echo

read -p "Press Enter to clean up demo resources..."

echo_cmd "docker rm -f web app"
docker rm -f web app 2>/dev/null || true

echo_cmd "docker network rm ${NETWORK_NAME}"
docker network rm ${NETWORK_NAME} 2>/dev/null || true

echo "  ✓ Demo resources cleaned up"
echo

echo "╔══════════════════════════════════════════════╗"
echo "║                Demo Complete!                 ║"
echo "╚══════════════════════════════════════════════╝"
echo
echo "You can now create your own OVS networks with:"
echo
echo "  docker network create --driver ${PLUGIN_NAME}:${PLUGIN_TAG} \\"
echo "    --subnet 10.0.0.0/24 \\"
echo "    --opt tenant_id=my-tenant \\"
echo "    --opt vlan=100 \\"
echo "    my-network"
echo
echo "For more examples, see README.md"
echo