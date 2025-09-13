#!/bin/bash

# Use the OVS control script which handles proper initialization including system-id
export PATH=/usr/share/openvswitch/scripts:$PATH

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVS container..."

# Ensure /dev/net/tun exists for netdev datapath tap devices
if [ ! -c /dev/net/tun ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Creating /dev/net/tun device..."
    mkdir -p /dev/net
    mknod /dev/net/tun c 10 200
    chmod 666 /dev/net/tun
fi

# Initialize database if needed
if [ ! -f /etc/openvswitch/conf.db ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Creating OVS database..."
    ovsdb-tool create /etc/openvswitch/conf.db /usr/share/openvswitch/vswitch.ovsschema
fi

# Start OVS using the official control script with hostname-based system-id
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVS services..."
/usr/share/openvswitch/scripts/ovs-ctl start --system-id=$(hostname)

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
    
    # Ensure system-id.conf file exists for exporter compatibility
    DB_SYSTEM_ID=$(ovs-vsctl --timeout=5 get Open_vSwitch . external_ids:system-id 2>/dev/null | tr -d '"' || echo "")
    
    if [ -n "$DB_SYSTEM_ID" ]; then
        if [ ! -f /etc/openvswitch/system-id.conf ]; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] Creating system-id.conf file with: $DB_SYSTEM_ID"
            echo "$DB_SYSTEM_ID" > /etc/openvswitch/system-id.conf
        else
            CONFIG_SYSTEM_ID=$(cat /etc/openvswitch/system-id.conf 2>/dev/null || echo "")
            if [ "$DB_SYSTEM_ID" != "$CONFIG_SYSTEM_ID" ]; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] Syncing system-id: database='$DB_SYSTEM_ID', config='$CONFIG_SYSTEM_ID'"
                echo "$DB_SYSTEM_ID" > /etc/openvswitch/system-id.conf
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] Updated system-id config file to match database"
            fi
        fi
    fi
fi

# Set bridge name from environment or use default
BRIDGE_NAME=${OVS_BRIDGE_NAME:-ovs-br0}
BRIDGE_IP=${OVS_BRIDGE_IP:-172.18.0.1/24}

# Create the bridge with userspace datapath (works without kernel module)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Creating bridge ${BRIDGE_NAME} with userspace datapath..."

# Create the bridge
ovs-vsctl --timeout=5 --may-exist add-br ${BRIDGE_NAME} || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Failed to create bridge ${BRIDGE_NAME}"
    exit 1
}

# Set bridge to use userspace datapath (netdev) - this enables userspace-only operation
ovs-vsctl --timeout=5 set bridge ${BRIDGE_NAME} datapath_type=netdev || {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: Failed to set userspace datapath"
    exit 1
}

# Set bridge to use modern OpenFlow versions
ovs-vsctl --timeout=5 set bridge ${BRIDGE_NAME} protocols=OpenFlow13,OpenFlow14,OpenFlow15 || echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: Failed to set bridge protocols"

# Configure bridge IP (may fail in some environments, don't exit on failure)
if [ -n "${BRIDGE_IP}" ]; then
    ip addr add ${BRIDGE_IP} dev ${BRIDGE_NAME} 2>/dev/null || echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: Could not configure bridge IP (normal in some environments)"
    ip link set ${BRIDGE_NAME} up 2>/dev/null || echo "[$(date '+%Y-%m-%d %H:%M:%S')] INFO: Could not bring bridge up (normal in some environments)"
fi

# Add basic flow rule to enable normal switching
ovs-ofctl -O OpenFlow13 add-flow ${BRIDGE_NAME} "priority=0,actions=normal" 2>/dev/null || echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: Failed to add flow rules"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] OVS bridge ${BRIDGE_NAME} is ready"
ovs-vsctl --timeout=3 show

# Start OVN controller if configured
if [ -n "${OVN_REMOTE}" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Configuring OVN controller..."
    
    # Set OVN configuration
    ovs-vsctl set open_vswitch . external_ids:ovn-remote="${OVN_REMOTE}"
    ovs-vsctl set open_vswitch . external_ids:ovn-encap-type="${OVN_ENCAP_TYPE:-geneve}"
    ovs-vsctl set open_vswitch . external_ids:ovn-encap-ip="${OVN_ENCAP_IP}"
    ovs-vsctl set open_vswitch . external_ids:system-id="${HOSTNAME}"
    
    # Start OVN controller
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVN controller..."
    /usr/share/ovn/scripts/ovn-ctl start_controller
    
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] OVN controller started"
fi

# Final system-id sync and exporter startup (after all OVS/OVN setup is complete)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Final system-id sync for exporter..."
DB_SYSTEM_ID=$(ovs-vsctl --timeout=5 get Open_vSwitch . external_ids:system-id 2>/dev/null | tr -d '"' || echo "")

if [ -n "$DB_SYSTEM_ID" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Creating system-id.conf file with: $DB_SYSTEM_ID"
    echo "$DB_SYSTEM_ID" > /etc/openvswitch/system-id.conf
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: Could not get system-id from database, using hostname"
    echo "$(hostname)" > /etc/openvswitch/system-id.conf
fi

# Start OVS exporter in background
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVS exporter..."
/usr/local/bin/ovs-exporter \
    -web.listen-address=:9475 \
    -web.telemetry-path=/metrics \
    -system.run.dir=/var/run/openvswitch \
    -database.vswitch.name=Open_vSwitch \
    -database.vswitch.socket.remote=unix:/var/run/openvswitch/db.sock \
    -database.vswitch.file.data.path=/etc/openvswitch/conf.db \
    -log.level=info &

OVS_EXPORTER_PID=$!
echo "[$(date '+%Y-%m-%d %H:%M:%S')] OVS exporter started with PID ${OVS_EXPORTER_PID}"

# Mark as ready for health checks (even in degraded mode)
touch /tmp/ovs-ready

# Handle shutdown gracefully
trap 'echo "Shutting down OVS and exporter..."; rm -f /tmp/ovs-ready; kill ${OVS_EXPORTER_PID} 2>/dev/null; if [ -n "${OVN_REMOTE}" ]; then /usr/share/ovn/scripts/ovn-ctl stop_controller; fi; /usr/share/openvswitch/scripts/ovs-ctl stop; exit 0' SIGTERM SIGINT

# Keep container running and show logs from both services
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Monitoring OVS logs..."
if [ -n "${OVN_REMOTE}" ]; then
    tail -F /var/log/openvswitch/*.log /var/log/ovn/*.log 2>/dev/null &
else
    tail -F /var/log/openvswitch/*.log 2>/dev/null &
fi

# Wait for background processes
wait