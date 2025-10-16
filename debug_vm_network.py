#!/usr/bin/env python3
"""
Debug VM network connectivity issues with OVS/OVN
"""

import subprocess
import re
import sys

def run_command(cmd, check=False):
    """Run command and return output"""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=check)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        return f"Error: {e.stderr}"

def debug_vm_network():
    """Debug VM network setup"""
    print("🔍 VM Network Debug Report")
    print("="*60)

    # 1. Check running VMs
    print("\n1️⃣ Running VMs:")
    vm_list = run_command(['sudo', 'virsh', 'list', '--name'])
    if vm_list:
        vms = [vm for vm in vm_list.split('\n') if vm]
        for vm in vms:
            print(f"  • {vm}")
    else:
        print("  ❌ No VMs running")
        return

    # 2. Check VM TAP interfaces
    print("\n2️⃣ VM TAP Interfaces:")
    for vm in vms:
        xml_output = run_command(['sudo', 'virsh', 'dumpxml', vm])
        tap_matches = re.findall(r"target dev='(tap[^']+|vnet[^']+)'", xml_output)
        if tap_matches:
            tap_iface = tap_matches[0]
            print(f"  {vm}: {tap_iface}")

            # Check if interface exists
            ip_link = run_command(['ip', 'link', 'show', tap_iface])
            if "does not exist" in ip_link:
                print(f"    ❌ Interface {tap_iface} does not exist!")
            else:
                print(f"    ✅ Interface exists")

            # Check if connected to OVS
            ovs_port = run_command(['sudo', 'ovs-vsctl', 'port-to-br', tap_iface])
            if ovs_port and "no port named" not in ovs_port:
                print(f"    ✅ Connected to OVS bridge: {ovs_port}")
            else:
                print(f"    ❌ NOT connected to OVS!")
        else:
            print(f"  {vm}: No TAP interface found")

    # 3. Check OVS bridge and ports
    print("\n3️⃣ OVS Bridge Status:")
    bridges = run_command(['sudo', 'ovs-vsctl', 'list-br'])
    if bridges:
        for bridge in bridges.split('\n'):
            print(f"  Bridge: {bridge}")
            ports = run_command(['sudo', 'ovs-vsctl', 'list-ports', bridge])
            if ports:
                for port in ports.split('\n'):
                    if port:
                        # Check if it's a VM interface
                        is_vm_port = any(port.startswith(prefix) for prefix in ['tap', 'vnet'])
                        marker = "🖥️" if is_vm_port else "  "
                        print(f"    {marker} {port}")

                        # Get external_ids for VM ports
                        if is_vm_port:
                            external_ids = run_command(['sudo', 'ovs-vsctl', 'get', 'Interface', port, 'external_ids'])
                            if external_ids and external_ids != '{}':
                                print(f"        external_ids: {external_ids}")
                            else:
                                print(f"        ⚠️  No external_ids set (needed for OVN binding)")

    # 4. Check OVN configuration
    print("\n4️⃣ OVN Configuration:")

    # Check if OVN is configured
    ovn_remote = run_command(['sudo', 'ovs-vsctl', 'get', 'open_vswitch', '.', 'external_ids:ovn-remote'])
    if ovn_remote and ovn_remote != '""':
        print(f"  OVN Remote: {ovn_remote}")
    else:
        print("  ❌ OVN not configured on this chassis")

    # Check OVN logical switches
    print("\n  Logical Switches:")
    ls_list = run_command(['sudo', 'docker', 'exec', 'ovn-central', 'ovn-nbctl', 'ls-list'])
    if ls_list:
        for line in ls_list.split('\n'):
            if line:
                print(f"    {line}")

    # Check OVN logical ports for VMs
    print("\n  VM Logical Ports:")
    for vm in vms:
        lsp_name = f"lsp-{vm}"
        port_info = run_command(['sudo', 'docker', 'exec', 'ovn-central', 'ovn-nbctl', 'lsp-get-addresses', lsp_name])
        if port_info and "lsp-get-addresses" not in port_info:
            print(f"    {lsp_name}: {port_info}")

            # Check port binding
            binding = run_command(['sudo', 'docker', 'exec', 'ovn-central', 'ovn-sbctl', 'show'])
            if binding and vm in binding:
                print(f"      ✅ Port appears in SB database")
            else:
                print(f"      ❌ Port NOT bound in SB database")
        else:
            print(f"    {lsp_name}: ❌ Not found in NB database")

    # 5. Check for common issues
    print("\n5️⃣ Common Issues Check:")

    # Check if ovn-controller is running
    ovn_controller = run_command(['sudo', 'systemctl', 'is-active', 'ovn-controller'])
    if ovn_controller == "active":
        print("  ✅ ovn-controller is running")
    else:
        print(f"  ❌ ovn-controller is {ovn_controller}")

    # Check if VM ports have proper external_ids for OVN
    print("\n  VM Port OVN Integration:")
    for vm in vms:
        xml_output = run_command(['sudo', 'virsh', 'dumpxml', vm])
        tap_matches = re.findall(r"target dev='(tap[^']+|vnet[^']+)'", xml_output)
        if tap_matches:
            tap_iface = tap_matches[0]

            # Check iface-id (required for OVN binding)
            iface_id = run_command(['sudo', 'ovs-vsctl', 'get', 'Interface', tap_iface, 'external_ids:iface-id'])
            if iface_id and iface_id != '""':
                print(f"    {vm} ({tap_iface}): iface-id = {iface_id}")
                if iface_id.strip('"') == f"lsp-{vm}":
                    print(f"      ✅ Correctly mapped to OVN port")
                else:
                    print(f"      ❌ iface-id doesn't match OVN port name")
            else:
                print(f"    {vm} ({tap_iface}): ❌ Missing iface-id (CRITICAL)")
                print(f"      Fix with: sudo ovs-vsctl set Interface {tap_iface} external_ids:iface-id=lsp-{vm}")

    # 6. Suggest fixes
    print("\n6️⃣ Suggested Fixes:")
    fixes_needed = False

    for vm in vms:
        xml_output = run_command(['sudo', 'virsh', 'dumpxml', vm])
        tap_matches = re.findall(r"target dev='(tap[^']+|vnet[^']+)'", xml_output)
        if tap_matches:
            tap_iface = tap_matches[0]

            # Check if connected to OVS
            ovs_port = run_command(['sudo', 'ovs-vsctl', 'port-to-br', tap_iface])
            if not ovs_port or "no port named" in ovs_port:
                print(f"\n  🔧 Connect {vm} to OVS:")
                print(f"     sudo ovs-vsctl add-port br-int {tap_iface}")
                fixes_needed = True

            # Check iface-id
            iface_id = run_command(['sudo', 'ovs-vsctl', 'get', 'Interface', tap_iface, 'external_ids:iface-id'])
            if not iface_id or iface_id == '""':
                print(f"\n  🔧 Set OVN binding for {vm}:")
                print(f"     sudo ovs-vsctl set Interface {tap_iface} external_ids:iface-id=lsp-{vm}")
                fixes_needed = True

    if not fixes_needed:
        print("  ✅ No obvious issues found")

    print("\n" + "="*60)

if __name__ == "__main__":
    debug_vm_network()