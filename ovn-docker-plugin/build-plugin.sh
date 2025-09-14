#!/bin/bash
set -e

PLUGIN_NAME="ovn-docker-plugin"
PLUGIN_TAG="latest"

echo "Building OVN Docker plugin..."

# Build the plugin image
docker build -t ${PLUGIN_NAME}:rootfs .

# Create plugin rootfs
rm -rf rootfs
mkdir -p rootfs
docker create --name tmp-${PLUGIN_NAME} ${PLUGIN_NAME}:rootfs
docker export tmp-${PLUGIN_NAME} | tar -x -C rootfs
docker rm tmp-${PLUGIN_NAME}

# Copy config.json
cp config.json rootfs/

# Create the plugin
docker plugin rm -f ${PLUGIN_NAME}:${PLUGIN_TAG} 2>/dev/null || true
docker plugin create ${PLUGIN_NAME}:${PLUGIN_TAG} rootfs/

# Clean up
rm -rf rootfs

echo "Plugin created: ${PLUGIN_NAME}:${PLUGIN_TAG}"
echo ""
echo "To enable the plugin, run:"
echo "  docker plugin enable ${PLUGIN_NAME}:${PLUGIN_TAG}"
echo ""
echo "To use the plugin, run:"
echo "  docker network create -d ${PLUGIN_NAME}:${PLUGIN_TAG} --subnet=10.99.0.0/24 test-ovn-net"