#!/bin/bash

# Use the OVS control script which handles proper initialization including system-id
export PATH=/usr/share/openvswitch/scripts:$PATH

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVS container..."

# Initialize database if needed
if [ ! -f /etc/openvswitch/conf.db ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Creating OVS database..."
    ovsdb-tool create /etc/openvswitch/conf.db /usr/share/openvswitch/vswitch.ovsschema
fi

# Start OVS using the official control script with system-id=random
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVS services..."
/usr/share/openvswitch/scripts/ovs-ctl start --system-id=random

# Force start ovs-vswitchd even without kernel module (for userspace operation)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Ensuring ovs-vswitchd is running for userspace operation..."
if ! pgrep -x ovs-vswitchd >/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting ovs-vswitchd manually for userspace operation..."
    ovs-vswitchd --pidfile --detach --log-file
fi

# Create symlinks for exporter compatibility
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Creating control socket symlinks for exporter compatibility..."
if [ -f /var/run/openvswitch/ovs-vswitchd.pid ]; then
    VSWITCHD_PID=$(cat /var/run/openvswitch/ovs-vswitchd.pid)
    ln -sf "ovs-vswitchd.${VSWITCHD_PID}.ctl" /var/run/openvswitch/ovs-vswitchd.0.ctl
fi
if [ -f /var/run/openvswitch/ovsdb-server.pid ]; then
    OVSDB_PID=$(cat /var/run/openvswitch/ovsdb-server.pid)
    ln -sf "ovsdb-server.${OVSDB_PID}.ctl" /var/run/openvswitch/ovsdb-server.0.ctl
fi

# Wait for OVS to be ready
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for OVS to be ready..."
OVS_READY=false
for i in {1..30}; do
    if ovs-vsctl --timeout=3 show >/dev/null 2>&1; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] OVS is ready"
        OVS_READY=true
        break
    fi
    sleep 1
done

if [ "$OVS_READY" != "true" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: OVS did not become ready within timeout, but continuing..."
    # Check if at least ovsdb-server is running
    if ! pgrep -x ovsdb-server >/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: ovsdb-server is not running, exiting"
        exit 1
    fi
fi

# Set the hostname in the OVS database (required by ovs-exporter) with timeout
if [ "$OVS_READY" = "true" ]; then
    ovs-vsctl --timeout=5 set Open_vSwitch . external_ids:hostname=$(hostname) || echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: Failed to set hostname in OVS database"
fi

# Create the bridge with userspace datapath (works without kernel module)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Creating bridge with userspace datapath..."

# Create the bridge
ovs-vsctl --timeout=5 --may-exist add-br ovs-br0 || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Failed to create bridge ovs-br0"
    exit 1
}

# Set bridge to use userspace datapath (netdev) - this enables userspace-only operation
ovs-vsctl --timeout=5 set bridge ovs-br0 datapath_type=netdev || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Failed to set userspace datapath"
    exit 1
}

# Set bridge to use modern OpenFlow versions
ovs-vsctl --timeout=5 set bridge ovs-br0 protocols=OpenFlow13,OpenFlow14,OpenFlow15 || echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: Failed to set bridge protocols"

# Configure bridge IP (may fail in some environments, don't exit on failure)
ip addr add 172.18.0.1/24 dev ovs-br0 2>/dev/null || echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: Could not configure bridge IP (normal in some environments)"
ip link set ovs-br0 up 2>/dev/null || echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: Could not bring bridge up (normal in some environments)"

# Add basic flow rule to enable normal switching
ovs-ofctl -O OpenFlow13 add-flow ovs-br0 "priority=0,actions=normal" 2>/dev/null || echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: Failed to add flow rules"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] OVS bridge ovs-br0 is ready"
ovs-vsctl --timeout=3 show

# Mark as ready for health checks (even in degraded mode)
touch /tmp/ovs-ready

# Handle shutdown gracefully
trap 'echo "Shutting down OVS..."; rm -f /tmp/ovs-ready; /usr/share/openvswitch/scripts/ovs-ctl stop; exit 0' SIGTERM SIGINT

# Keep container running and show logs from both services
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Monitoring OVS logs..."
tail -F /var/log/openvswitch/*.log 2>/dev/null