#!/bin/bash
# Test TCP connectivity between containers and VMs on the same subnet

echo "🔍 Testing TCP between containers and VMs on same subnet"
echo "========================================================="

# Test from vpc-b-web (should be on same subnet as vpc-b-vm)
echo ""
echo "1️⃣ Testing from vpc-b-web (10.1.1.0/24) to vpc-b-vm (10.1.1.20):"

# Check container IP
echo "  Container IP:"
sudo docker exec vpc-b-web ip addr show eth0 | grep inet

echo ""
echo "  Connectivity tests:"

# ICMP test
echo -n "    ICMP (ping): "
if sudo docker exec vpc-b-web ping -c 1 -W 1 10.1.1.20 >/dev/null 2>&1; then
    echo "✅ Works"
else
    echo "❌ Failed"
fi

# TCP test with netcat
echo -n "    TCP port 22 (nc): "
if sudo docker exec vpc-b-web timeout 2 nc -zv 10.1.1.20 22 2>&1 | grep -q succeeded; then
    echo "✅ Works"
else
    echo "❌ Failed"
fi

# Try actual SSH connection
echo -n "    SSH connection: "
result=$(sudo docker exec vpc-b-web timeout 3 ssh -o ConnectTimeout=2 -o StrictHostKeyChecking=no ubuntu@10.1.1.20 echo "connected" 2>&1 || true)
if echo "$result" | grep -q "connected"; then
    echo "✅ Works completely!"
elif echo "$result" | grep -q "Permission denied\|password"; then
    echo "✅ TCP works (auth needed)"
elif echo "$result" | grep -q "Connection timed out"; then
    echo "❌ TCP timeout"
elif echo "$result" | grep -q "Connection refused"; then
    echo "❌ TCP refused (SSH not running?)"
else
    echo "❌ Failed: ${result:0:50}..."
fi

# Also test from vpc-a-web to vpc-a-vm
echo ""
echo "2️⃣ Testing from vpc-a-web (10.0.1.0/24) to vpc-a-vm (10.0.1.20):"

# Check container IP
echo "  Container IP:"
sudo docker exec vpc-a-web ip addr show eth0 | grep inet

echo ""
echo "  Connectivity tests:"

# ICMP test
echo -n "    ICMP (ping): "
if sudo docker exec vpc-a-web ping -c 1 -W 1 10.0.1.20 >/dev/null 2>&1; then
    echo "✅ Works"
else
    echo "❌ Failed"
fi

# TCP test
echo -n "    TCP port 22 (nc): "
if sudo docker exec vpc-a-web timeout 2 nc -zv 10.0.1.20 22 2>&1 | grep -q succeeded; then
    echo "✅ Works"
else
    echo "❌ Failed"
fi

# Check if it's a routing issue (test cross-subnet)
echo ""
echo "3️⃣ Cross-subnet routing test (should go through router):"
echo "  From vpc-b-db (10.1.3.0/24) to vpc-b-vm (10.1.1.20):"

# Show the route
echo "    Route from container:"
sudo docker exec vpc-b-db ip route get 10.1.1.20 | head -1

# Test connectivity
echo -n "    ICMP: "
if sudo docker exec vpc-b-db ping -c 1 -W 2 10.1.1.20 >/dev/null 2>&1; then
    echo "✅ Works (routing OK)"
else
    echo "❌ Failed (routing issue?)"
fi

echo -n "    TCP: "
if sudo docker exec vpc-b-db timeout 3 nc -zv 10.1.1.20 22 2>&1 | grep -q succeeded; then
    echo "✅ Works"
else
    echo "❌ Failed"
fi

# Debug TAP interface state
echo ""
echo "4️⃣ VM TAP interface details:"

for vm_name in vpc-b-vm vpc-a-vm; do
    if sudo virsh list --name | grep -q "$vm_name"; then
        tap=$(sudo virsh dumpxml "$vm_name" 2>/dev/null | grep -oP "target dev='(tap[^']+|vnet[^']+)" | cut -d"'" -f2)
        if [ -n "$tap" ]; then
            echo "  $vm_name TAP: $tap"

            # Check if it's in OVS
            bridge=$(sudo ovs-vsctl port-to-br "$tap" 2>/dev/null || echo "not in OVS")
            echo "    Bridge: $bridge"

            # Check OVN binding
            iface_id=$(sudo ovs-vsctl get Interface "$tap" external_ids:iface-id 2>/dev/null | tr -d '"')
            echo "    OVN binding: ${iface_id:-none}"

            # Check key offloading
            tso=$(sudo ethtool -k "$tap" 2>/dev/null | grep "tcp-segmentation-offload" | grep -o "on\|off")
            gso=$(sudo ethtool -k "$tap" 2>/dev/null | grep "generic-segmentation-offload" | grep -o "on\|off")
            echo "    TSO: ${tso:-unknown}, GSO: ${gso:-unknown}"
        fi
    fi
done

# Check datapath mode
echo ""
echo "5️⃣ OVS Bridge configuration:"
datapath=$(sudo ovs-vsctl get bridge br-int datapath_type 2>/dev/null || echo "system")
echo "  Datapath type: $datapath"

if [ "$datapath" != "netdev" ]; then
    echo "  ⚠️  NOT using userspace datapath - this could be the issue!"
fi

# Check for flow issues
echo ""
echo "6️⃣ Checking OVS flows for TCP traffic:"
echo "  Flows matching TCP (port 22):"
sudo ovs-ofctl dump-flows br-int | grep -E "tcp.*tp_dst=22|tcp.*22" | head -3 || echo "    No specific TCP flows found"

echo ""
echo "  Total flow count:"
flow_count=$(sudo ovs-ofctl dump-flows br-int | grep -c "^" || echo 0)
echo "    $flow_count flows"

echo ""
echo "========================================================="
echo ""
echo "Summary:"
echo "  - If same-subnet works but cross-subnet fails: routing issue"
echo "  - If no TCP works at all: datapath/offloading issue"
echo "  - If some TCP works: likely firewall or MTU issue"