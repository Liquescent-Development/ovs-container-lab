#!/usr/bin/env python3
"""
Setup real GENEVE tunnels for the OVS Container Lab
Creates actual tunnel interfaces that can be monitored and manipulated
"""

import subprocess
import json
import sys
import logging
import argparse

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TunnelManager:
    """Manages GENEVE tunnel creation and configuration"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.bridge_name = "br-int"
        self.tunnels = []

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
            if capture and e.stderr:
                self.logger.error(f"stderr: {e.stderr}")
            if check:
                raise
            return None

    def check_bridge_exists(self):
        """Ensure br-int bridge exists"""
        bridges = self.run_command(["sudo", "ovs-vsctl", "list-br"])
        if self.bridge_name not in bridges.split('\n'):
            self.logger.info(f"Creating bridge {self.bridge_name}")
            self.run_command(["sudo", "ovs-vsctl", "add-br", self.bridge_name])
            # Set bridge to use OpenFlow 1.3
            self.run_command(["sudo", "ovs-vsctl", "set", "bridge", self.bridge_name,
                            "protocols=OpenFlow10,OpenFlow11,OpenFlow12,OpenFlow13"])
        return True

    def create_geneve_tunnel(self, tunnel_name, remote_ip, local_ip=None, key=None):
        """Create a GENEVE tunnel interface

        Args:
            tunnel_name: Name for the tunnel interface
            remote_ip: Remote endpoint IP address
            local_ip: Local endpoint IP address (optional)
            key: GENEVE VNI/key (optional)
        """
        self.logger.info(f"Creating GENEVE tunnel: {tunnel_name} to {remote_ip}")

        # Build options for the tunnel
        options = [f"remote_ip={remote_ip}"]
        if local_ip:
            options.append(f"local_ip={local_ip}")
        if key:
            options.append(f"key={key}")

        options_str = ",".join(options)

        # Check if tunnel already exists
        existing_ports = self.run_command(["sudo", "ovs-vsctl", "list-ports", self.bridge_name])
        if tunnel_name in existing_ports.split('\n'):
            self.logger.info(f"Tunnel {tunnel_name} already exists, removing first")
            self.run_command(["sudo", "ovs-vsctl", "del-port", self.bridge_name, tunnel_name], check=False)

        # Add the tunnel port
        cmd = ["sudo", "ovs-vsctl", "add-port", self.bridge_name, tunnel_name,
               "--", "set", "interface", tunnel_name, "type=geneve", f"options:{options_str}"]

        result = self.run_command(cmd, check=False)

        # Verify tunnel was created
        iface_type = self.run_command(["sudo", "ovs-vsctl", "get", "interface", tunnel_name, "type"], check=False)
        if iface_type and "geneve" in iface_type:
            self.logger.info(f"✅ Tunnel {tunnel_name} created successfully")
            self.tunnels.append({
                "name": tunnel_name,
                "remote_ip": remote_ip,
                "local_ip": local_ip,
                "key": key
            })
            return True
        else:
            self.logger.error(f"❌ Failed to create tunnel {tunnel_name}")
            return False

    def setup_demo_tunnels(self):
        """Setup demonstration GENEVE tunnels between simulated VPCs"""
        print("\n🚇 Setting up GENEVE Tunnels for Demonstration")
        print("="*50)

        # Ensure bridge exists
        self.check_bridge_exists()

        # Create tunnels between different "sites" or "VPCs"
        # These simulate tunnels that would exist between OVS instances

        # Tunnel 1: Simulating VPC-A to VPC-B connection
        self.create_geneve_tunnel(
            tunnel_name="geneve-vpc-a-b",
            remote_ip="10.1.0.1",  # VPC-B endpoint (simulated)
            local_ip="10.0.0.1",   # VPC-A endpoint (simulated)
            key="100"              # VNI for VPC interconnect
        )

        # Tunnel 2: Simulating VPC-A to External/Cloud
        self.create_geneve_tunnel(
            tunnel_name="geneve-vpc-a-ext",
            remote_ip="192.168.100.254",  # External gateway
            local_ip="10.0.0.1",          # VPC-A endpoint
            key="200"                     # VNI for external access
        )

        # Tunnel 3: Simulating VPC-B to External/Cloud
        self.create_geneve_tunnel(
            tunnel_name="geneve-vpc-b-ext",
            remote_ip="192.168.100.254",  # External gateway
            local_ip="10.1.0.1",          # VPC-B endpoint
            key="300"                     # VNI for external access
        )

        # Tunnel 4: Management/Control plane tunnel
        self.create_geneve_tunnel(
            tunnel_name="geneve-control",
            remote_ip="172.30.0.5",       # OVN central
            local_ip="172.30.0.1",        # Local chassis
            key="0"                       # VNI 0 for control plane
        )

        print("\n📊 Tunnel Summary:")
        print("-" * 40)
        for tunnel in self.tunnels:
            print(f"  • {tunnel['name']}:")
            print(f"    Local: {tunnel['local_ip'] or 'auto'}")
            print(f"    Remote: {tunnel['remote_ip']}")
            print(f"    VNI: {tunnel['key'] or 'none'}")

        return True

    def show_tunnel_status(self):
        """Display current tunnel status and statistics"""
        print("\n📊 GENEVE Tunnel Status")
        print("="*50)

        # Get all ports on bridge
        ports = self.run_command(["sudo", "ovs-vsctl", "list-ports", self.bridge_name])
        if not ports:
            print("No ports found on bridge")
            return

        tunnel_ports = []
        for port in ports.split('\n'):
            if not port:
                continue
            # Check if it's a tunnel port
            iface_type = self.run_command(["sudo", "ovs-vsctl", "get", "interface", port, "type"], check=False)
            if iface_type and "geneve" in iface_type.lower():
                tunnel_ports.append(port)

        if not tunnel_ports:
            print("❌ No GENEVE tunnels found")
            print("\nRun 'make setup-tunnels' to create demonstration tunnels")
            return

        print(f"Found {len(tunnel_ports)} GENEVE tunnel(s):\n")

        for port in tunnel_ports:
            print(f"🚇 Tunnel: {port}")
            print("-" * 30)

            # Get tunnel options
            options = self.run_command(["sudo", "ovs-vsctl", "get", "interface", port, "options"], check=False)
            if options:
                print(f"  Options: {options}")

            # Get operational state
            admin_state = self.run_command(["sudo", "ovs-vsctl", "get", "interface", port, "admin_state"], check=False)
            link_state = self.run_command(["sudo", "ovs-vsctl", "get", "interface", port, "link_state"], check=False)

            if admin_state:
                print(f"  Admin State: {admin_state}")
            if link_state:
                print(f"  Link State: {link_state}")

            # Get statistics
            stats = self.run_command(["sudo", "ovs-vsctl", "get", "interface", port, "statistics"], check=False)
            if stats and stats != "{}":
                try:
                    # Parse statistics
                    stats_dict = {}
                    # Remove curly braces and split by comma
                    stats_clean = stats.strip('{}')
                    for stat in stats_clean.split(','):
                        if '=' in stat:
                            key, value = stat.split('=', 1)
                            stats_dict[key.strip()] = value.strip()

                    # Display key statistics
                    if 'rx_packets' in stats_dict or 'tx_packets' in stats_dict:
                        print(f"  Statistics:")
                        if 'rx_packets' in stats_dict:
                            print(f"    RX Packets: {stats_dict['rx_packets']}")
                        if 'tx_packets' in stats_dict:
                            print(f"    TX Packets: {stats_dict['tx_packets']}")
                        if 'rx_bytes' in stats_dict:
                            print(f"    RX Bytes: {stats_dict['rx_bytes']}")
                        if 'tx_bytes' in stats_dict:
                            print(f"    TX Bytes: {stats_dict['tx_bytes']}")
                except:
                    print(f"  Statistics: {stats}")

            print()

        # Show OpenFlow tunnel information
        print("\n📋 OpenFlow Tunnel Information:")
        print("-" * 40)
        ofproto_tunnels = self.run_command(["sudo", "ovs-appctl", "ofproto/list-tunnels"], check=False)
        if ofproto_tunnels:
            print(ofproto_tunnels)
        else:
            print("No OpenFlow tunnel information available")

    def remove_tunnels(self):
        """Remove all GENEVE tunnels"""
        print("\n🧹 Removing GENEVE tunnels...")

        # Get all ports on bridge
        ports = self.run_command(["sudo", "ovs-vsctl", "list-ports", self.bridge_name])
        if not ports:
            print("No ports found on bridge")
            return

        removed_count = 0
        for port in ports.split('\n'):
            if not port:
                continue
            # Check if it's a tunnel port
            iface_type = self.run_command(["sudo", "ovs-vsctl", "get", "interface", port, "type"], check=False)
            if iface_type and "geneve" in iface_type.lower():
                self.logger.info(f"Removing tunnel: {port}")
                self.run_command(["sudo", "ovs-vsctl", "del-port", self.bridge_name, port], check=False)
                removed_count += 1

        print(f"✅ Removed {removed_count} tunnel(s)")

def main():
    parser = argparse.ArgumentParser(description="GENEVE Tunnel Management for OVS Lab")
    parser.add_argument("action", choices=["setup", "status", "remove"],
                       help="Action to perform")

    args = parser.parse_args()

    manager = TunnelManager()

    if args.action == "setup":
        manager.setup_demo_tunnels()
        print("\n✅ Tunnels created successfully")
        print("\nYou can now:")
        print("  • Run 'make chaos-tunnel-status' to see tunnel status")
        print("  • Run 'make chaos-underlay-down' to simulate tunnel failure")
        print("  • Run 'make chaos-vlan-down' to simulate VLAN mismatch")
        print("  • Check metrics at http://localhost:9475/metrics")

    elif args.action == "status":
        manager.show_tunnel_status()

    elif args.action == "remove":
        manager.remove_tunnels()

if __name__ == "__main__":
    main()