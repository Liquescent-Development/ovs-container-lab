#!/bin/bash
# Quick TCP debugging between container and VM

echo "🔍 TCP Connectivity Debug"
echo "========================="

# Check specific case: vpc-b-db to vpc-b-vm
echo ""
echo "Testing vpc-b-db (container) → vpc-b-vm (10.1.1.20):"

# 1. Check if VM interface has offloading enabled
echo ""
echo "1️⃣ VM TAP interface offloading status:"
tap=$(sudo virsh dumpxml vpc-b-vm 2>/dev/null | grep -oP "target dev='(tap[^']+|vnet[^']+)" | cut -d"'" -f2)
if [ -n "$tap" ]; then
    echo "  Interface: $tap"
    echo "  Critical offloading settings:"
    sudo ethtool -k "$tap" 2>/dev/null | grep -E "tx-checksumming|rx-checksumming|tcp-segmentation|generic-segmentation|generic-receive" | head -10
else
    echo "  ❌ Could not find TAP interface"
fi

# 2. Check container veth offloading
echo ""
echo "2️⃣ Container veth interface offloading status:"
# Find vpc-b-db container's veth
container_id=$(sudo docker inspect vpc-b-db --format '{{.Id}}' 2>/dev/null | cut -c1-12)
if [ -n "$container_id" ]; then
    # Look for veth on host side
    veth=$(sudo ovs-vsctl list-ports br-int | grep "veth.*${container_id:0:8}" | head -1)
    if [ -z "$veth" ]; then
        # Try alternate naming
        veth=$(sudo ovs-vsctl list-ports br-int | grep "^veth" | while read v; do
            if sudo ip link show "$v" 2>/dev/null | grep -q "$container_id"; then
                echo "$v"
                break
            fi
        done)
    fi

    if [ -n "$veth" ]; then
        echo "  Interface: $veth"
        echo "  Critical offloading settings:"
        sudo ethtool -k "$veth" 2>/dev/null | grep -E "tx-checksumming|rx-checksumming|tcp-segmentation|generic-segmentation|generic-receive" | head -10
    else
        echo "  ⚠️  Could not identify container veth"
    fi
fi

# 3. Test actual connectivity
echo ""
echo "3️⃣ Connectivity tests:"

echo -n "  ICMP (ping): "
if sudo docker exec vpc-b-db ping -c 1 -W 1 10.1.1.20 >/dev/null 2>&1; then
    echo "✅ Works"
else
    echo "❌ Failed"
fi

echo -n "  TCP port 22 (nc): "
if sudo docker exec vpc-b-db timeout 2 nc -zv 10.1.1.20 22 2>&1 | grep -q succeeded; then
    echo "✅ Works"
else
    echo "❌ Failed"
fi

echo -n "  SSH handshake: "
result=$(sudo docker exec vpc-b-db timeout 2 ssh -o ConnectTimeout=1 -o StrictHostKeyChecking=no -o PasswordAuthentication=no ubuntu@10.1.1.20 2>&1 || true)
if echo "$result" | grep -q "Permission denied"; then
    echo "✅ Works (auth failed = TCP works)"
elif echo "$result" | grep -q "Connection timed out\|Connection refused"; then
    echo "❌ Failed (timeout/refused)"
else
    echo "⚠️  Uncertain: $result"
fi

# 4. Check MTU
echo ""
echo "4️⃣ MTU comparison:"
if [ -n "$tap" ]; then
    vm_mtu=$(ip link show "$tap" 2>/dev/null | grep -oP 'mtu \K[0-9]+')
    echo "  VM TAP ($tap): MTU=$vm_mtu"
fi

container_mtu=$(sudo docker exec vpc-b-db ip link show eth0 2>/dev/null | grep -oP 'mtu \K[0-9]+')
echo "  Container (eth0): MTU=$container_mtu"

bridge_mtu=$(ip link show br-int 2>/dev/null | grep -oP 'mtu \K[0-9]+')
echo "  OVS Bridge (br-int): MTU=$bridge_mtu"

# 5. Check OVS datapath mode
echo ""
echo "5️⃣ OVS Configuration:"
datapath=$(sudo ovs-vsctl get bridge br-int datapath_type 2>/dev/null || echo "system")
echo "  Datapath type: $datapath"
if [ "$datapath" != "netdev" ]; then
    echo "  ⚠️  Using kernel datapath - may have offloading issues"
fi

# 6. Quick fix attempt
echo ""
echo "6️⃣ Attempting quick fix..."
if [ -n "$tap" ]; then
    echo "  Disabling all offloading on $tap..."
    for feature in rx tx sg tso ufo gso gro lro rxvlan txvlan rxhash; do
        sudo ethtool -K "$tap" "$feature" off 2>/dev/null
    done

    echo -n "  Re-testing TCP: "
    if sudo docker exec vpc-b-db timeout 2 nc -zv 10.1.1.20 22 2>&1 | grep -q succeeded; then
        echo "✅ NOW WORKS!"
    else
        echo "❌ Still failing"
        echo ""
        echo "  Try these additional steps:"
        echo "    1. Set userspace datapath: sudo ovs-vsctl set bridge br-int datapath_type=netdev"
        echo "    2. Restart OVS: sudo systemctl restart openvswitch-switch"
        echo "    3. Recreate VM: make vpc-vms-destroy && make vpc-vms"
    fi
fi

echo ""
echo "========================="