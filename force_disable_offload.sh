#!/bin/bash
# Force disable ALL offloading on VM TAP interfaces
# This is required for OVS userspace datapath to handle TCP correctly

echo "🔨 FORCE Disabling ALL Offloading on VM TAP Interfaces"
echo "======================================================"

# Function to completely disable offloading
force_disable_offload() {
    local iface=$1
    echo "  Force disabling ALL offloading on $iface..."

    # Method 1: Disable everything we can name
    local features="rx tx sg tso ufo gso gro lro rxvlan txvlan rxhash ntuple rxhash rx-checksumming tx-checksumming"
    features="$features scatter-gather tcp-segmentation-offload udp-fragmentation-offload"
    features="$features generic-segmentation-offload generic-receive-offload"
    features="$features large-receive-offload rx-vlan-offload tx-vlan-offload"
    features="$features receive-hashing highdma tx-nocache-copy"
    features="$features tx-gso-robust tx-ipip-segmentation tx-sit-segmentation"
    features="$features tx-udp_tnl-segmentation tx-mpls-segmentation"
    features="$features tx-tcp-segmentation tx-tcp6-segmentation"

    for feat in $features; do
        sudo ethtool -K "$iface" "$feat" off 2>/dev/null
    done

    # Method 2: Use simplified flags
    sudo ethtool --offload "$iface" rx off tx off 2>/dev/null
    sudo ethtool -K "$iface" gso off 2>/dev/null
    sudo ethtool -K "$iface" tso off 2>/dev/null
    sudo ethtool -K "$iface" gro off 2>/dev/null

    # Method 3: Disable at different levels
    sudo ethtool -K "$iface" tx-checksum-ipv4 off 2>/dev/null
    sudo ethtool -K "$iface" tx-checksum-ipv6 off 2>/dev/null
    sudo ethtool -K "$iface" tx-checksum-ip-generic off 2>/dev/null
    sudo ethtool -K "$iface" tx-checksum-sctp off 2>/dev/null
}

# Find and fix VM TAP interfaces
echo ""
echo "1️⃣ Finding VM TAP interfaces..."

for vm_name in vpc-a-vm vpc-b-vm; do
    if sudo virsh list --name | grep -q "$vm_name"; then
        tap=$(sudo virsh dumpxml "$vm_name" 2>/dev/null | grep -oP "target dev='(tap[^']+|vnet[^']+)" | cut -d"'" -f2)
        if [ -n "$tap" ]; then
            echo ""
            echo "Processing $vm_name (interface: $tap)"
            echo "  Before:"
            sudo ethtool -k "$tap" 2>/dev/null | grep -E "tcp-segmentation|generic-segmentation|generic-receive|checksumming:" | grep ": on" | head -5

            force_disable_offload "$tap"

            echo "  After:"
            remaining=$(sudo ethtool -k "$tap" 2>/dev/null | grep -E "segmentation|receive-offload|checksumming" | grep ": on" | wc -l)
            if [ "$remaining" -eq 0 ]; then
                echo "    ✅ ALL offloading disabled"
            else
                echo "    ⚠️  Still enabled:"
                sudo ethtool -k "$tap" 2>/dev/null | grep ": on" | head -5
            fi
        fi
    fi
done

# Also check if we need to restart the TAP interface
echo ""
echo "2️⃣ Restarting TAP interfaces to apply changes..."

for vm_name in vpc-a-vm vpc-b-vm; do
    if sudo virsh list --name | grep -q "$vm_name"; then
        tap=$(sudo virsh dumpxml "$vm_name" 2>/dev/null | grep -oP "target dev='(tap[^']+|vnet[^']+)" | cut -d"'" -f2)
        if [ -n "$tap" ]; then
            echo "  Bouncing $tap..."
            sudo ip link set "$tap" down
            sleep 0.5
            sudo ip link set "$tap" up

            # Re-disable after bringing up (sometimes settings reset)
            force_disable_offload "$tap"
        fi
    fi
done

# Make sure we're really in userspace mode
echo ""
echo "3️⃣ Verifying OVS datapath mode..."
datapath=$(sudo ovs-vsctl get bridge br-int datapath_type 2>/dev/null)
echo "  Datapath: $datapath"

if [ "$datapath" != "netdev" ]; then
    echo "  ❌ NOT in userspace mode! Fixing..."
    sudo ovs-vsctl set bridge br-int datapath_type=netdev
    sudo systemctl restart openvswitch-switch
    sleep 2

    # Re-add TAP interfaces after restart
    for vm_name in vpc-a-vm vpc-b-vm; do
        if sudo virsh list --name | grep -q "$vm_name"; then
            tap=$(sudo virsh dumpxml "$vm_name" 2>/dev/null | grep -oP "target dev='(tap[^']+|vnet[^']+)" | cut -d"'" -f2)
            if [ -n "$tap" ]; then
                sudo ovs-vsctl --may-exist add-port br-int "$tap"
                sudo ovs-vsctl set Interface "$tap" external_ids:iface-id="lsp-$vm_name"
                force_disable_offload "$tap"
            fi
        fi
    done
fi

# Test connectivity
echo ""
echo "4️⃣ Testing TCP connectivity..."

test_tcp() {
    local src=$1
    local dst_ip=$2
    local vm_name=$3

    echo -n "  $src → $vm_name ($dst_ip): "

    # First test ICMP
    if ! sudo docker exec "$src" ping -c 1 -W 1 "$dst_ip" >/dev/null 2>&1; then
        echo "❌ ICMP failed"
        return
    fi

    # Test TCP with multiple methods
    if sudo docker exec "$src" timeout 2 bash -c "echo '' | nc -w 1 $dst_ip 22" 2>/dev/null; then
        echo "✅ TCP WORKS!"
    elif sudo docker exec "$src" timeout 2 nc -zv "$dst_ip" 22 2>&1 | grep -q succeeded; then
        echo "✅ TCP WORKS!"
    else
        echo "❌ ICMP works but TCP fails"

        # One more check - verify offloading is really off
        tap=$(sudo virsh dumpxml "$vm_name" 2>/dev/null | grep -oP "target dev='(tap[^']+|vnet[^']+)" | cut -d"'" -f2)
        if [ -n "$tap" ]; then
            tso=$(sudo ethtool -k "$tap" 2>/dev/null | grep "tcp-segmentation-offload:" | grep -o "on\|off" | head -1)
            gso=$(sudo ethtool -k "$tap" 2>/dev/null | grep "generic-segmentation-offload:" | grep -o "on\|off" | head -1)
            echo "      Check: TSO=$tso, GSO=$gso"
            if [ "$tso" = "on" ] || [ "$gso" = "on" ]; then
                echo "      🔄 Offloading still on! Trying once more..."
                force_disable_offload "$tap"

                # Test again
                if sudo docker exec "$src" timeout 2 nc -zv "$dst_ip" 22 2>&1 | grep -q succeeded; then
                    echo "      ✅ NOW IT WORKS!"
                else
                    echo "      ❌ Still failing"
                fi
            fi
        fi
    fi
}

# Test from same-subnet containers
test_tcp "vpc-b-web" "10.1.1.20" "vpc-b-vm"
test_tcp "vpc-a-web" "10.0.1.20" "vpc-a-vm"

# Test cross-subnet
test_tcp "vpc-b-db" "10.1.1.20" "vpc-b-vm"

echo ""
echo "======================================================"
echo ""
echo "If TCP still doesn't work after this:"
echo "  1. Try detaching and reattaching the network interface:"
echo "     sudo virsh detach-interface vpc-b-vm bridge --mac <mac>"
echo "     sudo virsh attach-interface vpc-b-vm bridge br-int --model virtio"
echo "  2. Or restart the VM: make vpc-vms-restart"
echo "  3. Check VM firewall: sudo iptables -L -n (in VM console)"