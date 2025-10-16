#!/bin/bash
# Ensure OVS bridge is using userspace datapath for VMs
# This fixes TCP issues by ensuring consistent datapath mode

echo "🔧 Fixing OVS Userspace Datapath for VMs"
echo "=========================================="

# Check current datapath type
echo ""
echo "1️⃣ Checking current OVS bridge configuration..."
current_datapath=$(sudo ovs-vsctl get bridge br-int datapath_type 2>/dev/null || echo "system")
echo "  Current datapath type: $current_datapath"

if [ "$current_datapath" != "netdev" ]; then
    echo "  ❌ Bridge is NOT using userspace datapath!"
    echo "  🔄 Switching to userspace (netdev) datapath..."

    # Set bridge to use userspace datapath
    sudo ovs-vsctl set bridge br-int datapath_type=netdev

    echo "  ✅ Bridge switched to userspace datapath"
else
    echo "  ✅ Bridge is already using userspace datapath"
fi

# Ensure fail-mode is set correctly for userspace
echo ""
echo "2️⃣ Setting bridge fail-mode for userspace..."
sudo ovs-vsctl set bridge br-int fail-mode=secure
echo "  ✅ Bridge fail-mode set to 'secure'"

# Check and reconnect VM TAP interfaces
echo ""
echo "3️⃣ Reconnecting VM TAP interfaces to userspace bridge..."

for vm_name in vpc-a-vm vpc-b-vm; do
    if sudo virsh list --name | grep -q "$vm_name"; then
        echo "  Processing $vm_name..."

        # Get TAP interface
        tap=$(sudo virsh dumpxml "$vm_name" 2>/dev/null | grep -oP "target dev='(tap[^']+|vnet[^']+)" | cut -d"'" -f2)

        if [ -n "$tap" ]; then
            echo "    TAP interface: $tap"

            # Check if it's on the bridge
            if sudo ovs-vsctl port-to-br "$tap" 2>/dev/null | grep -q br-int; then
                echo "    Already on br-int"

                # Remove and re-add to ensure userspace datapath
                echo "    Reconnecting to ensure userspace mode..."
                sudo ovs-vsctl --if-exists del-port br-int "$tap"
                sudo ovs-vsctl add-port br-int "$tap"

                # Set the OVN binding
                sudo ovs-vsctl set Interface "$tap" external_ids:iface-id="lsp-$vm_name"

                echo "    ✅ Reconnected to userspace bridge"
            else
                echo "    Not on bridge, adding..."
                sudo ovs-vsctl add-port br-int "$tap"
                sudo ovs-vsctl set Interface "$tap" external_ids:iface-id="lsp-$vm_name"
                echo "    ✅ Added to userspace bridge"
            fi

            # Since we're in userspace, offloading MUST be disabled
            echo "    Disabling all offloading (required for userspace)..."
            for feature in rx tx sg tso ufo gso gro lro rxvlan txvlan rxhash; do
                sudo ethtool -K "$tap" "$feature" off 2>/dev/null
            done
        fi
    fi
done

# Check container interfaces are also properly configured
echo ""
echo "4️⃣ Verifying container veth interfaces..."

for veth in $(sudo ovs-vsctl list-ports br-int | grep "^veth"); do
    echo "  $veth: Disabling offloading..."
    for feature in rx tx sg tso ufo gso gro lro; do
        sudo ethtool -K "$veth" "$feature" off 2>/dev/null
    done
done

# Restart OVS to ensure clean state
echo ""
echo "5️⃣ Restarting OVS to apply changes..."
sudo systemctl restart openvswitch-switch
sleep 3

# Re-add ports after restart
echo ""
echo "6️⃣ Re-adding ports after OVS restart..."

# Ensure bridge exists with userspace datapath
sudo ovs-vsctl --may-exist add-br br-int -- set bridge br-int datapath_type=netdev fail-mode=secure

# Re-add VM interfaces
for vm_name in vpc-a-vm vpc-b-vm; do
    if sudo virsh list --name | grep -q "$vm_name"; then
        tap=$(sudo virsh dumpxml "$vm_name" 2>/dev/null | grep -oP "target dev='(tap[^']+|vnet[^']+)" | cut -d"'" -f2)
        if [ -n "$tap" ]; then
            echo "  Re-adding $tap for $vm_name..."
            sudo ovs-vsctl --may-exist add-port br-int "$tap"
            sudo ovs-vsctl set Interface "$tap" external_ids:iface-id="lsp-$vm_name"

            # Disable offloading again
            for feature in rx tx sg tso gso gro; do
                sudo ethtool -K "$tap" "$feature" off 2>/dev/null
            done
        fi
    fi
done

# Verify final state
echo ""
echo "7️⃣ Final verification..."
final_datapath=$(sudo ovs-vsctl get bridge br-int datapath_type)
echo "  Bridge datapath: $final_datapath"

if [ "$final_datapath" = "netdev" ]; then
    echo "  ✅ Bridge is using userspace datapath"
else
    echo "  ❌ Bridge is NOT using userspace datapath"
fi

# Test connectivity
echo ""
echo "8️⃣ Testing TCP connectivity..."

test_tcp() {
    local src=$1
    local dst_ip=$2
    local dst_name=$3

    echo -n "  $src → $dst_name ($dst_ip): "

    if sudo docker exec "$src" timeout 2 nc -zv "$dst_ip" 22 2>&1 | grep -q succeeded; then
        echo "✅ TCP works!"
    else
        if sudo docker exec "$src" ping -c 1 -W 1 "$dst_ip" >/dev/null 2>&1; then
            echo "❌ ICMP works but TCP fails"
        else
            echo "❌ No connectivity"
        fi
    fi
}

# Test from containers to VMs
if sudo docker ps | grep -q vpc-b-db; then
    test_tcp "vpc-b-db" "10.1.1.20" "vpc-b-vm"
fi

if sudo docker ps | grep -q vpc-a-web; then
    test_tcp "vpc-a-web" "10.0.1.20" "vpc-a-vm"
fi

echo ""
echo "✅ Userspace datapath configuration complete!"
echo ""
echo "If TCP still doesn't work:"
echo "  1. Restart the VMs: make vpc-vms-restart"
echo "  2. Check OVN controller: sudo systemctl status ovn-controller"
echo "  3. Re-run: make fix-vm-network"