#!/bin/sh
set -e

# Get tier from environment variable (web, app, or db)
TIER=${TIER:-web}

echo "Starting VPC container (tier: $TIER)..."

# Start iperf3 server in background (bind to IPv4)
echo "Starting iperf3 server on port 5201..."
iperf3 -s -B 0.0.0.0 -D

# Start tier-specific services
case "$TIER" in
    web)
        echo "Starting web tier services..."
        # HTTP on port 80
        nc -l -k -p 80 < /dev/zero > /dev/null 2>&1 &
        # HTTPS on port 443
        nc -l -k -p 443 < /dev/zero > /dev/null 2>&1 &
        echo "Listening on ports: 80, 443, 5201 (iperf3)"
        ;;
    app)
        echo "Starting app tier services..."
        # App ports
        nc -l -k -p 8080 < /dev/zero > /dev/null 2>&1 &
        nc -l -k -p 8443 < /dev/zero > /dev/null 2>&1 &
        echo "Listening on ports: 8080, 8443, 5201 (iperf3)"
        ;;
    db)
        echo "Starting db tier services..."
        # Database ports
        nc -l -k -p 5432 < /dev/zero > /dev/null 2>&1 &
        nc -l -k -p 3306 < /dev/zero > /dev/null 2>&1 &
        echo "Listening on ports: 5432, 3306, 5201 (iperf3)"
        ;;
    *)
        echo "Unknown tier: $TIER"
        ;;
esac

# Show network configuration
echo "Network configuration:"
ip addr show
ip route show

echo "Container ready for traffic"

# Keep container running
exec sleep infinity