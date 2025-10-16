#!/usr/bin/env python3
"""
Fix VM TAP interface offloading settings for OVS compatibility
Disables offloading features that prevent TCP traffic from working correctly
"""

import subprocess
import re
import logging
import sys

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class VMOffloadingFixer:
    """Manages offloading settings for VM TAP interfaces"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        # Offloading features that need to be disabled for OVS
        self.offload_features = [
            'rx',      # RX checksumming
            'tx',      # TX checksumming
            'sg',      # scatter-gather
            'tso',     # TCP segmentation offload
            'gso',     # generic segmentation offload
            'gro',     # generic receive offload
            'rxvlan',  # RX vlan offload
            'txvlan',  # TX vlan offload
            'rxhash'   # RX hashing
        ]

    def run_command(self, cmd, check=True):
        """Execute a command and return output"""
        self.logger.debug(f"Running: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=check)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Command failed: {e}")
            if e.stderr:
                self.logger.error(f"stderr: {e.stderr}")
            if check:
                raise
            return None

    def find_vm_tap_interfaces(self):
        """Find TAP interfaces used by VMs"""
        tap_interfaces = []

        # Method 1: Check virsh dumpxml for each VM
        try:
            # Get list of running VMs
            vm_list = self.run_command(['sudo', 'virsh', 'list', '--name'])
            if vm_list:
                for vm_name in vm_list.split('\n'):
                    if vm_name and 'vpc' in vm_name:  # Focus on our VPC VMs
                        # Get VM XML configuration
                        xml_output = self.run_command(['sudo', 'virsh', 'dumpxml', vm_name], check=False)
                        if xml_output:
                            # Look for tap interfaces in the XML
                            matches = re.findall(r"target dev='(tap[^']+)'", xml_output)
                            if not matches:
                                # Sometimes they're named vnet*
                                matches = re.findall(r"target dev='(vnet[^']+)'", xml_output)
                            for iface in matches:
                                tap_interfaces.append((vm_name, iface))
                                self.logger.info(f"Found interface {iface} for VM {vm_name}")
        except Exception as e:
            self.logger.warning(f"Could not get VM interfaces from virsh: {e}")

        # Method 2: Check OVS for tap/vnet interfaces
        try:
            ovs_ports = self.run_command(['sudo', 'ovs-vsctl', 'list-ports', 'br-int'])
            if ovs_ports:
                for port in ovs_ports.split('\n'):
                    if port.startswith('tap') or port.startswith('vnet'):
                        # Try to match with a VM
                        vm_name = "unknown"
                        for vm, iface in tap_interfaces:
                            if iface == port:
                                vm_name = vm
                                break
                        if vm_name == "unknown":
                            tap_interfaces.append((vm_name, port))
                            self.logger.info(f"Found additional interface {port} in OVS")
        except Exception as e:
            self.logger.warning(f"Could not get OVS ports: {e}")

        return tap_interfaces

    def check_offloading_status(self, interface):
        """Check current offloading settings for an interface"""
        try:
            output = self.run_command(['sudo', 'ethtool', '-k', interface], check=False)
            if output:
                status = {}
                for line in output.split('\n'):
                    for feature in self.offload_features:
                        if feature in line.lower():
                            if 'on' in line.lower():
                                status[feature] = 'on'
                            elif 'off' in line.lower():
                                status[feature] = 'off'
                return status
        except Exception as e:
            self.logger.error(f"Failed to check offloading for {interface}: {e}")
        return {}

    def disable_offloading(self, interface):
        """Disable offloading features for an interface"""
        self.logger.info(f"Disabling offloading for {interface}...")

        failed_features = []
        succeeded_features = []

        for feature in self.offload_features:
            cmd = ['sudo', 'ethtool', '-K', interface, feature, 'off']
            result = self.run_command(cmd, check=False)
            if result is None:
                # Command failed, but some features might not be supported
                self.logger.debug(f"Could not disable {feature} on {interface} (may not be supported)")
                failed_features.append(feature)
            else:
                succeeded_features.append(feature)

        # Also disable with simplified command for common features
        self.run_command(['sudo', 'ethtool', '--offload', interface, 'rx', 'off', 'tx', 'off'], check=False)

        if succeeded_features:
            self.logger.info(f"Disabled features on {interface}: {', '.join(succeeded_features)}")

        return len(succeeded_features) > 0

    def fix_all_vm_interfaces(self):
        """Find and fix offloading for all VM TAP interfaces"""
        print("\n🔧 Fixing VM TAP Interface Offloading Settings")
        print("="*50)

        # Find VM interfaces
        tap_interfaces = self.find_vm_tap_interfaces()

        if not tap_interfaces:
            print("❌ No VM TAP interfaces found")
            print("   Make sure VMs are running: make vpc-vms")
            return False

        print(f"\nFound {len(tap_interfaces)} VM interface(s):")
        for vm_name, iface in tap_interfaces:
            print(f"  • {iface} ({vm_name})")

        print("\nChecking and fixing offloading settings...")

        fixed_count = 0
        for vm_name, iface in tap_interfaces:
            print(f"\n📍 Interface: {iface} (VM: {vm_name})")

            # Check current status
            before_status = self.check_offloading_status(iface)
            if before_status:
                enabled_features = [f for f, status in before_status.items() if status == 'on']
                if enabled_features:
                    print(f"   Currently enabled: {', '.join(enabled_features)}")
                else:
                    print("   All features already disabled")

            # Disable offloading
            if self.disable_offloading(iface):
                fixed_count += 1

                # Verify changes
                after_status = self.check_offloading_status(iface)
                if after_status:
                    still_enabled = [f for f, status in after_status.items() if status == 'on']
                    if still_enabled:
                        print(f"   ⚠️  Still enabled: {', '.join(still_enabled)}")
                    else:
                        print("   ✅ All offloading disabled")
            else:
                print(f"   ❌ Failed to modify settings")

        print(f"\n✅ Fixed {fixed_count}/{len(tap_interfaces)} interfaces")

        if fixed_count == len(tap_interfaces):
            print("\n🎉 Success! TCP traffic should now work for VMs")
            print("Test with: make test")
        else:
            print("\n⚠️  Some interfaces could not be fixed")
            print("You may need to restart the VMs")

        return True

    def monitor_and_fix(self):
        """Continuously monitor and fix new VM interfaces"""
        print("\n👀 Monitoring for new VM interfaces...")
        print("Press Ctrl+C to stop")

        fixed_interfaces = set()

        try:
            while True:
                tap_interfaces = self.find_vm_tap_interfaces()

                for vm_name, iface in tap_interfaces:
                    if iface not in fixed_interfaces:
                        print(f"\n🆕 New interface detected: {iface} ({vm_name})")
                        if self.disable_offloading(iface):
                            fixed_interfaces.add(iface)
                            print(f"   ✅ Fixed offloading for {iface}")

                import time
                time.sleep(5)  # Check every 5 seconds

        except KeyboardInterrupt:
            print("\n\n✋ Monitoring stopped")
            return True

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Fix VM TAP interface offloading for OVS")
    parser.add_argument('--monitor', action='store_true',
                       help='Continuously monitor and fix new interfaces')
    parser.add_argument('--check-only', action='store_true',
                       help='Only check current settings without fixing')

    args = parser.parse_args()

    fixer = VMOffloadingFixer()

    if args.monitor:
        fixer.monitor_and_fix()
    elif args.check_only:
        tap_interfaces = fixer.find_vm_tap_interfaces()
        if tap_interfaces:
            print("\n📊 Current Offloading Status:")
            print("="*50)
            for vm_name, iface in tap_interfaces:
                print(f"\n{iface} ({vm_name}):")
                status = fixer.check_offloading_status(iface)
                if status:
                    for feature, state in status.items():
                        if state == 'on':
                            print(f"  ❌ {feature}: {state}")
                        else:
                            print(f"  ✅ {feature}: {state}")
        else:
            print("No VM TAP interfaces found")
    else:
        fixer.fix_all_vm_interfaces()

if __name__ == "__main__":
    main()