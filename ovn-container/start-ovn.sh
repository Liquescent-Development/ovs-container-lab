#!/bin/bash

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVN container..."

# Start OVS first
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVS..."
service openvswitch-switch start

# Ensure ovs-vswitchd is actually running
if ! pgrep -x ovs-vswitchd >/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting ovs-vswitchd manually..."
    ovs-vswitchd --pidfile --detach --log-file
fi

# Wait for OVS to be ready
OVS_READY=false
for i in {1..30}; do
    if ovs-vsctl --timeout=5 show &>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] OVS is ready"
        OVS_READY=true
        break
    fi
    sleep 1
done

if [ "$OVS_READY" != "true" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERROR: OVS failed to start properly"
    exit 1
fi

# Set OVS to use OVN with timeout
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Configuring OVS for OVN..."
ovs-vsctl --timeout=5 set open_vswitch . external_ids:ovn-bridge="br-int"
ovs-vsctl --timeout=5 set open_vswitch . external_ids:ovn-remote="unix:/var/run/ovn/ovnsb_db.sock"
ovs-vsctl --timeout=5 set open_vswitch . external_ids:ovn-encap-type="geneve"
ovs-vsctl --timeout=5 set open_vswitch . external_ids:ovn-encap-ip="127.0.0.1"

# Start OVN Central components (Northbound and Southbound databases)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVN Central components..."

# Create OVN directories
mkdir -p /var/lib/ovn /var/run/ovn /var/log/ovn

# Create database files if they don't exist
if [ ! -f /var/lib/ovn/ovnnb.db ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Creating OVN Northbound database..."
    ovsdb-tool create /var/lib/ovn/ovnnb.db /usr/share/ovn/ovn-nb.ovsschema
fi

if [ ! -f /var/lib/ovn/ovnsb.db ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Creating OVN Southbound database..."
    ovsdb-tool create /var/lib/ovn/ovnsb.db /usr/share/ovn/ovn-sb.ovsschema
fi

# Start OVN Northbound database
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVN Northbound database..."
ovsdb-server --detach --monitor \
    --log-file=/var/log/ovn/ovn-northbound.log \
    --remote=punix:/var/run/ovn/ovnnb_db.sock \
    --remote=ptcp:6641:0.0.0.0 \
    --pidfile=/var/run/ovn/ovnnb_db.pid \
    /var/lib/ovn/ovnnb.db

# Start OVN Southbound database
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVN Southbound database..."
ovsdb-server --detach --monitor \
    --log-file=/var/log/ovn/ovn-southbound.log \
    --remote=punix:/var/run/ovn/ovnsb_db.sock \
    --remote=ptcp:6642:0.0.0.0 \
    --pidfile=/var/run/ovn/ovnsb_db.pid \
    /var/lib/ovn/ovnsb.db

# Initialize databases if needed
sleep 2
if ! ovn-nbctl --db=unix:/var/run/ovn/ovnnb_db.sock ls-list &>/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Initializing OVN Northbound database..."
    ovn-nbctl --db=unix:/var/run/ovn/ovnnb_db.sock init
fi

if ! ovn-sbctl --db=unix:/var/run/ovn/ovnsb_db.sock show &>/dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Initializing OVN Southbound database..."
    ovn-sbctl --db=unix:/var/run/ovn/ovnsb_db.sock init
fi

# Start OVN northd daemon
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVN northd..."
ovn-northd --detach --monitor \
    --log-file=/var/log/ovn/ovn-northd.log \
    --pidfile=/var/run/ovn/ovn-northd.pid \
    --ovnnb-db=unix:/var/run/ovn/ovnnb_db.sock \
    --ovnsb-db=unix:/var/run/ovn/ovnsb_db.sock

# Start OVN controller
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVN controller..."
ovn-controller --detach --monitor \
    --log-file=/var/log/ovn/ovn-controller.log \
    --pidfile=/var/run/ovn/ovn-controller.pid \
    unix:/var/run/openvswitch/db.sock

# Wait for OVN to be ready
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for OVN to be ready..."
for i in {1..30}; do
    if ovn-nbctl ls-list &>/dev/null && ovn-sbctl show &>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] OVN is ready"
        break
    fi
    sleep 1
done

# Create integration bridge
ovs-vsctl --may-exist add-br br-int -- set bridge br-int fail-mode=secure

echo "[$(date '+%Y-%m-%d %H:%M:%S')] OVN setup complete"

# Start OVN Docker overlay driver if enabled
if [ "$ENABLE_DOCKER_DRIVER" == "true" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVN Docker overlay driver..."

    # Configure OVS external_ids for the driver
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Configuring OVS external_ids for Docker driver..."
    ovs-vsctl set open_vswitch . external_ids:ovn-nb="tcp://127.0.0.1:6641"
    ovs-vsctl set open_vswitch . external_ids:ovn-encap-ip="127.0.0.1"
    ovs-vsctl set open_vswitch . external_ids:ovn-encap-type="geneve"

    # Set OVN database locations for the driver
    export OVN_NB="tcp://127.0.0.1:6641"
    export OVN_SB="tcp://127.0.0.1:6642"

    # Check if the driver exists (prefer /usr/local/bin for our fixed version)
    DRIVER_PATH="/usr/local/bin/ovn-docker-overlay-driver"
    if [ ! -x "$DRIVER_PATH" ]; then
        DRIVER_PATH="/usr/bin/ovn-docker-overlay-driver"
    fi

    if [ -x "$DRIVER_PATH" ]; then
        # Kill any existing driver process
        pkill -f ovn-docker-overlay-driver 2>/dev/null || true
        sleep 1

        # Start the driver (it will daemonize itself)
        $DRIVER_PATH

        # Wait for the driver to start
        for i in {1..10}; do
            if netstat -tlnp 2>/dev/null | grep -q ':5000'; then
                echo "[$(date '+%Y-%m-%d %H:%M:%S')] Docker overlay driver started on port 5000"
                break
            fi
            sleep 1
        done

        if ! netstat -tlnp 2>/dev/null | grep -q ':5000'; then
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: Docker driver not listening on port 5000"
        fi
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] WARNING: ovn-docker-overlay-driver not found"
    fi
fi

# Start OVN exporter
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVN exporter..."
/usr/local/bin/ovn-exporter \
    --web.listen-address=:9476 \
    --database.northbound.socket.remote=unix:/var/run/ovn/ovnnb_db.sock \
    --database.southbound.socket.remote=unix:/var/run/ovn/ovnsb_db.sock \
    --ovn.poll-interval=15 \
    --log.level=info &

# Wait for exporter to start
for i in {1..5}; do
    if netstat -tlnp 2>/dev/null | grep -q ':9476'; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] OVN exporter started on port 9476"
        break
    fi
    sleep 1
done

# Mark as ready
touch /tmp/ovn-ready

# Keep container running and show logs
tail -F /var/log/ovn/*.log /var/log/openvswitch/*.log 2>/dev/null