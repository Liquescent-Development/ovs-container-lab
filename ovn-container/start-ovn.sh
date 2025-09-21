#!/bin/bash

echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVN Central components only..."

# NOTE: This container only runs OVN control plane (NB/SB databases and northd)
# OVS and OVN controller should run on the compute nodes (host or ovs container)

# Start OVN Central components (Northbound and Southbound databases)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting OVN Central components..."

# Create OVN directories
mkdir -p /var/lib/ovn /var/run/ovn /var/log/ovn /var/run/openvswitch

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

# NOTE: OVN controller is NOT started here - it should run on compute nodes
# where OVS is running (in the ovs container or on the host)

# Wait for OVN databases to be ready
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Waiting for OVN databases to be ready..."
for i in {1..30}; do
    if ovn-nbctl ls-list &>/dev/null && ovn-sbctl show &>/dev/null; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] OVN databases are ready"
        break
    fi
    sleep 1
done

# NOTE: br-int bridge is NOT created here - it should be created on compute nodes

echo "[$(date '+%Y-%m-%d %H:%M:%S')] OVN setup complete"

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
tail -F /var/log/ovn/*.log 2>/dev/null