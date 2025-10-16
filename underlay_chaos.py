#!/usr/bin/env python3
"""
Underlay Network Chaos Engineering for OVS Container Lab
Demonstrates how underlay failures affect overlay tunnels
"""

import subprocess
import time
import sys
import logging
import argparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class UnderlayChaosTester:
    """Manages underlay network failures to demonstrate tunnel impact"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def run_command(self, cmd, check=True, capture=True):
        """Execute a command and return output"""
        self.logger.debug(f"Running: {' '.join(cmd)}")
        try:
            if capture:
                result = subprocess.run(cmd, check=check, capture_output=True, text=True)
                return result.stdout.strip()
            else:
                result = subprocess.run(cmd, check=check)
                return None
        except subprocess.CalledProcessError as e:
            self.logger.error(f"Command failed: {e}")
            if capture:
                self.logger.error(f"stderr: {e.stderr}")
            if check:
                raise
            return None

    def get_ovs_chassis_info(self):
        """Get OVS chassis information including tunnel endpoints"""
        info = {}
        try:
            # Get OVS configuration from the host
            ovs_show = self.run_command(["sudo", "ovs-vsctl", "show"])
            info['ovs_config'] = ovs_show

            # Get OVN chassis information
            ovn_chassis = self.run_command(["sudo", "ovs-vsctl", "get", "open_vswitch", ".", "external_ids:system-id"])
            info['chassis_id'] = ovn_chassis.strip('"')

            # Get encap type
            encap_type = self.run_command(["sudo", "ovs-vsctl", "get", "open_vswitch", ".", "external_ids:ovn-encap-type"])
            info['encap_type'] = encap_type.strip('"')

            # Get encap IP
            encap_ip = self.run_command(["sudo", "ovs-vsctl", "get", "open_vswitch", ".", "external_ids:ovn-encap-ip"], check=False)
            if encap_ip:
                info['encap_ip'] = encap_ip.strip('"')

            # List all ports to find GENEVE tunnels
            ports = self.run_command(["sudo", "ovs-vsctl", "list-ports", "br-int"])
            tunnel_ports = []
            if ports:
                for port in ports.split('\n'):
                    if 'ovn-' in port or 'genev' in port.lower():
                        tunnel_ports.append(port)
                        # Get port details
                        port_info = self.run_command(["sudo", "ovs-vsctl", "get", "interface", port, "options"], check=False)
                        if port_info:
                            self.logger.info(f"Tunnel port {port}: {port_info}")
            info['tunnel_ports'] = tunnel_ports

        except Exception as e:
            self.logger.error(f"Failed to get OVS info: {e}")

        return info

    def simulate_underlay_link_down(self, duration=60):
        """Simulate underlay link failure by blocking tunnel traffic"""
        print("\n🔌 UNDERLAY FAILURE SCENARIO: Link Down")
        print("="*50)
        print("This simulates a complete underlay network failure")
        print("where GENEVE tunnel packets cannot reach their destination.")
        print("")

        # Get current state
        info = self.get_ovs_chassis_info()
        tunnel_ports = info.get('tunnel_ports', [])

        if not tunnel_ports:
            print("❌ No tunnel ports found. Checking for OVN configuration...")
            # Try to find OVN-related interfaces
            all_interfaces = self.run_command(["sudo", "ip", "link", "show"])
            print("Looking for GENEVE interfaces in system...")

        print(f"📊 Current tunnel configuration:")
        print(f"   Encap Type: {info.get('encap_type', 'unknown')}")
        print(f"   Chassis ID: {info.get('chassis_id', 'unknown')}")
        if tunnel_ports:
            print(f"   Tunnel Ports: {', '.join(tunnel_ports)}")
        print("")

        print("🔨 Simulating underlay failure...")

        # Method 1: Block GENEVE traffic using iptables
        print("   Step 1: Blocking GENEVE (UDP port 6081) traffic...")
        self.run_command(["sudo", "iptables", "-I", "OUTPUT", "-p", "udp", "--dport", "6081", "-j", "DROP"])
        self.run_command(["sudo", "iptables", "-I", "INPUT", "-p", "udp", "--sport", "6081", "-j", "DROP"])

        # Method 2: If using specific tunnel interfaces, bring them down
        if tunnel_ports:
            print(f"   Step 2: Disabling tunnel ports in OVS...")
            for port in tunnel_ports:
                self.run_command(["sudo", "ovs-vsctl", "set", "interface", port, "admin_state=down"], check=False)

        # Method 3: Add packet loss to all traffic between OVS instances
        print("   Step 3: Adding 100% packet loss to inter-chassis communication...")
        # Find IPs used for OVN communication
        ovn_ips = ["172.30.0.5", "192.168.100.5"]  # OVN central IPs from docker-compose
        for ip in ovn_ips:
            self.run_command(["sudo", "iptables", "-I", "OUTPUT", "-d", ip, "-j", "DROP"], check=False)
            self.run_command(["sudo", "iptables", "-I", "INPUT", "-s", ip, "-j", "DROP"], check=False)

        print(f"\n⏱️  Underlay failure active for {duration} seconds...")
        print("   Monitor your overlay tunnels - they should show as DOWN")
        print("   Check: sudo ovs-vsctl show")
        print("   Check: sudo ovs-appctl ofproto/list-tunnels")
        print("")

        # Wait for the specified duration
        for i in range(duration, 0, -10):
            print(f"   {i} seconds remaining...")
            time.sleep(min(10, i))

        print("\n🔄 Restoring underlay connectivity...")

        # Restore iptables rules
        print("   Removing iptables blocks...")
        self.run_command(["sudo", "iptables", "-D", "OUTPUT", "-p", "udp", "--dport", "6081", "-j", "DROP"], check=False)
        self.run_command(["sudo", "iptables", "-D", "INPUT", "-p", "udp", "--sport", "6081", "-j", "DROP"], check=False)

        for ip in ovn_ips:
            self.run_command(["sudo", "iptables", "-D", "OUTPUT", "-d", ip, "-j", "DROP"], check=False)
            self.run_command(["sudo", "iptables", "-D", "INPUT", "-s", ip, "-j", "DROP"], check=False)

        # Re-enable tunnel ports
        if tunnel_ports:
            print("   Re-enabling tunnel ports...")
            for port in tunnel_ports:
                self.run_command(["sudo", "ovs-vsctl", "set", "interface", port, "admin_state=up"], check=False)

        print("\n✅ Underlay connectivity restored")
        print("   Tunnels should be coming back UP")
        print("")

    def simulate_vlan_mismatch(self, duration=60):
        """Simulate VLAN tag mismatch causing tunnel failure"""
        print("\n🏷️  UNDERLAY FAILURE SCENARIO: VLAN Tag Mismatch")
        print("="*50)
        print("This simulates a VLAN configuration mismatch where")
        print("the underlay expects untagged traffic but receives tagged,")
        print("or vice versa, causing tunnel packets to be dropped.")
        print("Admin state will remain UP but link state will be affected.")
        print("")

        # Get all GENEVE tunnel interfaces
        ports = self.run_command(["sudo", "ovs-vsctl", "list-ports", "br-int"])
        geneve_tunnels = []
        if ports:
            for port in ports.split('\n'):
                if port:
                    iface_type = self.run_command(["sudo", "ovs-vsctl", "get", "interface", port, "type"], check=False)
                    if iface_type and "geneve" in iface_type.lower():
                        geneve_tunnels.append(port)

        if not geneve_tunnels:
            print("❌ No GENEVE tunnels found!")
            print("   Run 'make setup-tunnels' first to create tunnels")
            return

        print("📊 Found GENEVE tunnels:")
        for tunnel in geneve_tunnels:
            print(f"   • {tunnel}")

        print("\n🔨 Simulating VLAN mismatch that affects tunnel connectivity...")

        # Method 1: Modify the remote_ip of tunnels to an unreachable address
        # This simulates the effect of VLAN mismatch where packets can't reach destination
        print("   Step 1: Saving current tunnel configurations...")
        tunnel_configs = {}
        for tunnel in geneve_tunnels:
            options = self.run_command(["sudo", "ovs-vsctl", "get", "interface", tunnel, "options"], check=False)
            tunnel_configs[tunnel] = options
            print(f"      {tunnel}: {options}")

        print("\n   Step 2: Modifying tunnel endpoints to simulate unreachability due to VLAN mismatch...")
        # Change remote IPs to unreachable addresses (simulating VLAN isolation)
        for tunnel in geneve_tunnels:
            # Parse current options
            current_options = tunnel_configs[tunnel]
            # Check if we have options and they contain remote_ip
            if current_options and "remote_ip" in current_options:
                # Change to a bogus IP that simulates wrong VLAN (169.254.x.x link-local range)
                bogus_ip = "169.254.99.99"
                try:
                    self.run_command(["sudo", "ovs-vsctl", "set", "interface", tunnel,
                                    f"options:remote_ip={bogus_ip}"], check=False)
                    print(f"      {tunnel}: remote_ip changed to {bogus_ip} (unreachable)")
                except Exception as e:
                    self.logger.error(f"Failed to modify tunnel {tunnel}: {e}")
                    print(f"      {tunnel}: Failed to modify (continuing anyway)")

        # Method 2: Block GENEVE traffic at netfilter level to simulate VLAN drops
        print("\n   Step 3: Blocking GENEVE traffic to simulate VLAN filtering...")
        self.run_command(["sudo", "iptables", "-I", "OUTPUT", "-p", "udp", "--dport", "6081",
                         "-m", "statistic", "--mode", "random", "--probability", "0.7", "-j", "DROP"], check=False)
        self.run_command(["sudo", "iptables", "-I", "INPUT", "-p", "udp", "--sport", "6081",
                         "-m", "statistic", "--mode", "random", "--probability", "0.7", "-j", "DROP"], check=False)

        # Method 3: Add packet corruption to simulate VLAN tag corruption
        print("   Step 4: Adding packet corruption to simulate VLAN header issues...")
        # Find the main network interface
        try:
            interfaces = self.run_command(["ip", "route", "show", "default"])
            main_iface = "eth0"  # fallback
            if interfaces and "dev" in interfaces:
                parts = interfaces.split()
                try:
                    idx = parts.index("dev")
                    if idx < len(parts) - 1:
                        main_iface = parts[idx + 1]
                except (ValueError, IndexError):
                    pass

            print(f"      Using interface: {main_iface}")

            # Add netem corruption specifically for GENEVE
            self.run_command(["sudo", "tc", "qdisc", "add", "dev", main_iface, "root", "handle", "1:", "prio"], check=False)
            self.run_command(["sudo", "tc", "filter", "add", "dev", main_iface, "parent", "1:", "protocol", "ip",
                             "u32", "match", "ip", "protocol", "17", "0xff",  # UDP
                             "match", "ip", "dport", "6081", "0xffff",       # GENEVE port
                             "flowid", "1:3"], check=False)
            self.run_command(["sudo", "tc", "qdisc", "add", "dev", main_iface, "parent", "1:3", "handle", "30:",
                             "netem", "corrupt", "30%"], check=False)
        except Exception as e:
            self.logger.warning(f"Failed to add traffic control rules: {e}")
            print(f"      Warning: Could not add traffic corruption (continuing anyway)")

        print(f"\n⏱️  VLAN mismatch active for {duration} seconds...")
        print("   Symptoms you should observe:")
        print("   • Tunnel link state should show as DOWN")
        print("   • Admin state remains UP (configuration is valid)")
        print("   • High packet loss/corruption on overlay network")
        print("   • Metrics should reflect link_state changes")
        print("")

        # Wait for the specified duration, checking status periodically
        check_interval = min(10, duration // 3)
        for i in range(duration, 0, -check_interval):
            if i < duration:  # Don't check immediately
                print(f"\n   Checking tunnel status ({i}s remaining)...")
                for tunnel in geneve_tunnels[:2]:  # Check first 2 tunnels
                    link_state = self.run_command(["sudo", "ovs-vsctl", "get", "interface", tunnel, "link_state"], check=False)
                    admin_state = self.run_command(["sudo", "ovs-vsctl", "get", "interface", tunnel, "admin_state"], check=False)
                    print(f"      {tunnel}: admin={admin_state}, link={link_state}")
            else:
                print(f"   {i} seconds remaining...")
            time.sleep(min(check_interval, i))

        print("\n🔄 Restoring correct VLAN configuration...")

        # Restore original tunnel configurations
        print("   Step 1: Restoring original tunnel endpoints...")
        for tunnel, original_options in tunnel_configs.items():
            if original_options and original_options != '{}':
                # Parse and restore original remote_ip
                import re
                match = re.search(r'remote_ip="?([^",}]+)"?', original_options)
                if match:
                    original_remote_ip = match.group(1)
                    self.run_command(["sudo", "ovs-vsctl", "set", "interface", tunnel,
                                    f"options:remote_ip={original_remote_ip}"], check=False)
                    print(f"      {tunnel}: restored remote_ip to {original_remote_ip}")

        # Clean up iptables rules
        print("\n   Step 2: Removing iptables blocks...")
        self.run_command(["sudo", "iptables", "-D", "OUTPUT", "-p", "udp", "--dport", "6081",
                         "-m", "statistic", "--mode", "random", "--probability", "0.7", "-j", "DROP"], check=False)
        self.run_command(["sudo", "iptables", "-D", "INPUT", "-p", "udp", "--sport", "6081",
                         "-m", "statistic", "--mode", "random", "--probability", "0.7", "-j", "DROP"], check=False)

        # Clean up tc rules
        print("   Step 3: Removing traffic control rules...")
        # Find the main interface again for cleanup
        try:
            interfaces = self.run_command(["ip", "route", "show", "default"])
            main_iface = "eth0"  # fallback
            if interfaces and "dev" in interfaces:
                parts = interfaces.split()
                try:
                    idx = parts.index("dev")
                    if idx < len(parts) - 1:
                        main_iface = parts[idx + 1]
                except (ValueError, IndexError):
                    pass
            self.run_command(["sudo", "tc", "qdisc", "del", "dev", main_iface, "root"], check=False)
        except Exception as e:
            self.logger.warning(f"Failed to remove traffic control rules: {e}")

        print("\n✅ VLAN configuration restored to normal")
        print("   Tunnel connectivity should stabilize within a few seconds")

        # Final check
        print("\n   Final tunnel status:")
        for tunnel in geneve_tunnels:
            link_state = self.run_command(["sudo", "ovs-vsctl", "get", "interface", tunnel, "link_state"], check=False)
            admin_state = self.run_command(["sudo", "ovs-vsctl", "get", "interface", tunnel, "admin_state"], check=False)
            print(f"      {tunnel}: admin={admin_state}, link={link_state}")

        print("")

    def check_tunnel_status(self):
        """Check and display current tunnel status"""
        print("\n📊 Current Tunnel Status:")
        print("-" * 40)

        # First check for GENEVE interfaces in OVS
        print("\n🚇 GENEVE Tunnels in OVS:")
        ports = self.run_command(["sudo", "ovs-vsctl", "list-ports", "br-int"], check=False)
        if ports:
            geneve_ports = []
            for port in ports.split('\n'):
                if port:
                    iface_type = self.run_command(["sudo", "ovs-vsctl", "get", "interface", port, "type"], check=False)
                    if iface_type and "geneve" in iface_type.lower():
                        geneve_ports.append(port)
                        # Get tunnel details
                        options = self.run_command(["sudo", "ovs-vsctl", "get", "interface", port, "options"], check=False)
                        admin_state = self.run_command(["sudo", "ovs-vsctl", "get", "interface", port, "admin_state"], check=False)
                        link_state = self.run_command(["sudo", "ovs-vsctl", "get", "interface", port, "link_state"], check=False)
                        print(f"  • {port}:")
                        if options:
                            print(f"    Options: {options}")
                        if admin_state:
                            print(f"    Admin: {admin_state}")
                        if link_state:
                            print(f"    Link: {link_state}")

            if not geneve_ports:
                print("  ❌ No GENEVE tunnels found")
                print("  💡 Run 'make setup-tunnels' to create demonstration tunnels")
        else:
            print("  ❌ No ports found on br-int")

        # Show OVS tunnel status
        print("\n📋 OpenFlow Tunnel Information:")
        tunnels = self.run_command(["sudo", "ovs-appctl", "ofproto/list-tunnels"], check=False)
        if tunnels:
            print(tunnels)
        else:
            print("  No OpenFlow tunnel information available")

        # Show OVN tunnel status if OVN is configured
        ovn_configured = self.run_command(["sudo", "ovs-vsctl", "get", "open_vswitch", ".",
                                         "external_ids:ovn-remote"], check=False)
        if ovn_configured and ovn_configured != '""':
            print("\n🔧 OVN Configuration:")
            print(f"  OVN Remote: {ovn_configured}")
            encap_type = self.run_command(["sudo", "ovs-vsctl", "get", "open_vswitch", ".",
                                          "external_ids:ovn-encap-type"], check=False)
            if encap_type:
                print(f"  Encap Type: {encap_type}")
            encap_ip = self.run_command(["sudo", "ovs-vsctl", "get", "open_vswitch", ".",
                                        "external_ids:ovn-encap-ip"], check=False)
            if encap_ip:
                print(f"  Encap IP: {encap_ip}")

        print("")

def main():
    parser = argparse.ArgumentParser(description="Underlay Network Chaos Testing")
    parser.add_argument("scenario", choices=["link-down", "vlan-mismatch", "status"],
                       help="Chaos scenario to run")
    parser.add_argument("--duration", type=int, default=60,
                       help="Duration of the chaos test in seconds (default: 60)")

    args = parser.parse_args()

    tester = UnderlayChaosTester()

    if args.scenario == "link-down":
        tester.simulate_underlay_link_down(args.duration)
    elif args.scenario == "vlan-mismatch":
        tester.simulate_vlan_mismatch(args.duration)
    elif args.scenario == "status":
        tester.check_tunnel_status()

if __name__ == "__main__":
    main()