#!/bin/bash
# Fix TCP connectivity issues between containers and VMs
# This script ensures all offloading is properly disabled on TAP interfaces

echo "🔧 Fixing TCP connectivity for VMs and containers"
echo "================================================"

# Function to disable all offloading on an interface
disable_all_offloading() {
    local iface=$1
    echo "  Disabling offloading on $iface..."

    # Try multiple methods to ensure offloading is disabled

    # Method 1: Individual features
    for feature in rx tx sg tso ufo gso gro lro rxvlan txvlan rxhash; do
        sudo ethtool -K "$iface" "$feature" off 2>/dev/null
    done

    # Method 2: Combined rx/tx
    sudo ethtool --offload "$iface" rx off tx off 2>/dev/null

    # Method 3: Checksumming
    sudo ethtool -K "$iface" rx-checksumming off 2>/dev/null
    sudo ethtool -K "$iface" tx-checksumming off 2>/dev/null

    # Method 4: Segmentation
    sudo ethtool -K "$iface" tx-tcp-segmentation off 2>/dev/null
    sudo ethtool -K "$iface" tx-tcp6-segmentation off 2>/dev/null
    sudo ethtool -K "$iface" generic-segmentation-offload off 2>/dev/null
    sudo ethtool -K "$iface" generic-receive-offload off 2>/dev/null

    # Method 5: Large receive offload
    sudo ethtool -K "$iface" large-receive-offload off 2>/dev/null
}

# Function to check offloading status
check_offloading() {
    local iface=$1
    echo "  Current settings for $iface:"
    sudo ethtool -k "$iface" 2>/dev/null | grep -E "tx-checksumming|rx-checksumming|scatter-gather|tcp-segmentation|generic-segmentation|generic-receive|large-receive" | grep ": on" | head -5
}

echo ""
echo "1️⃣ Finding and fixing VM TAP interfaces..."
for vm_name in vpc-a-vm vpc-b-vm; do
    if sudo virsh list --name | grep -q "$vm_name"; then
        echo "  Processing $vm_name..."

        # Get TAP interface
        tap=$(sudo virsh dumpxml "$vm_name" 2>/dev/null | grep -oP "target dev='(tap[^']+|vnet[^']+)" | cut -d"'" -f2)

        if [ -n "$tap" ]; then
            echo "    Interface: $tap"

            # Set OVN binding
            echo "    Setting OVN binding..."
            sudo ovs-vsctl set Interface "$tap" external_ids:iface-id="lsp-$vm_name" 2>/dev/null

            # Disable ALL offloading
            disable_all_offloading "$tap"

            # Verify
            remaining=$(sudo ethtool -k "$tap" 2>/dev/null | grep -E "checksumming|segmentation|offload" | grep ": on" | wc -l)
            if [ "$remaining" -eq 0 ]; then
                echo "    ✅ All offloading disabled"
            else
                echo "    ⚠️  Some offloading still enabled:"
                check_offloading "$tap"
            fi
        fi
    fi
done

echo ""
echo "2️⃣ Finding and fixing container veth interfaces..."
# Get all veth interfaces connected to OVS
for veth in $(sudo ovs-vsctl list-ports br-int | grep "^veth"); do
    echo "  Processing $veth..."
    disable_all_offloading "$veth"

    # Also disable on peer interface if we can find it
    peer=$(sudo ip link show "$veth" 2>/dev/null | grep -oP 'link/ether.*peer \K[^ ]+' || true)
    if [ -n "$peer" ]; then
        echo "    Peer interface: $peer"
        disable_all_offloading "$peer"
    fi
done

echo ""
echo "3️⃣ Checking OVS datapath mode..."
# Make sure OVS is using the right datapath
datapath=$(sudo ovs-vsctl get bridge br-int datapath_type 2>/dev/null)
echo "  Current datapath: ${datapath:-system}"
if [ "$datapath" != "netdev" ]; then
    echo "  ⚠️  Consider using userspace datapath for better compatibility:"
    echo "     sudo ovs-vsctl set bridge br-int datapath_type=netdev"
fi

echo ""
echo "4️⃣ Testing TCP connectivity..."

# Test from container to VM
test_connectivity() {
    local src=$1
    local dst_ip=$2
    local dst_name=$3

    echo -n "  $src → $dst_name ($dst_ip): "

    # Try TCP connection with timeout
    if sudo docker exec "$src" timeout 2 bash -c "echo '' | nc -w 1 $dst_ip 22" 2>/dev/null; then
        echo "✅ TCP works (SSH port reachable)"
    else
        # Check if ICMP works
        if sudo docker exec "$src" ping -c 1 -W 1 "$dst_ip" >/dev/null 2>&1; then
            echo "❌ ICMP works but TCP fails (offloading issue)"
        else
            echo "❌ No connectivity"
        fi
    fi
}

# Test specific paths
if sudo docker ps | grep -q vpc-b-db && sudo virsh list --name | grep -q vpc-b-vm; then
    test_connectivity "vpc-b-db" "10.1.1.20" "vpc-b-vm"
fi

if sudo docker ps | grep -q vpc-a-web && sudo virsh list --name | grep -q vpc-a-vm; then
    test_connectivity "vpc-a-web" "10.0.1.20" "vpc-a-vm"
fi

echo ""
echo "5️⃣ Additional debugging info..."

# Check MTU
echo "  MTU settings:"
for vm_name in vpc-a-vm vpc-b-vm; do
    if sudo virsh list --name | grep -q "$vm_name"; then
        tap=$(sudo virsh dumpxml "$vm_name" 2>/dev/null | grep -oP "target dev='(tap[^']+|vnet[^']+)" | cut -d"'" -f2)
        if [ -n "$tap" ]; then
            mtu=$(ip link show "$tap" 2>/dev/null | grep -oP 'mtu \K[0-9]+')
            echo "    $tap (VM $vm_name): MTU=$mtu"
        fi
    fi
done

echo ""
echo "✅ Fix complete!"
echo ""
echo "If TCP still doesn't work, try:"
echo "  1. Restart the VMs: make vpc-vms-restart"
echo "  2. Check firewall in VMs: sudo iptables -L (should be empty/ACCEPT)"
echo "  3. Check SSH is listening: ss -tlnp | grep :22"
echo "  4. Try with smaller MTU: sudo ip link set dev <interface> mtu 1400"