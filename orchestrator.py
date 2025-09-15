#!/usr/bin/env python3
"""
OVS Container Lab Orchestrator

A unified orchestration tool for managing the OVN/OVS container lab environment.
Replaces multiple shell scripts with a single Python application.
"""

import argparse
import json
import logging
import subprocess
import sys
import time
from typing import Dict, List, Optional
import os
import random
from datetime import datetime, timezone
from pathlib import Path

# Import network config manager if available
try:
    from network_config_manager import NetworkConfigManager
    CONFIG_MANAGER_AVAILABLE = True
except ImportError:
    CONFIG_MANAGER_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("network_config_manager not available, using legacy configuration")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class NetworkReconciler:
    """Handles network state reconciliation for containers"""

    def __init__(self, ovn_manager):
        self.ovn = ovn_manager
        self.logger = logging.getLogger(__name__)

    def get_container_network_state(self, container_name: str) -> dict:
        """Check the network state of a container"""
        state = {
            "exists": False,
            "has_interface": False,
            "ovs_port_exists": False,
            "ovn_port_exists": False,
            "ip_address": None,
            "needs_repair": False
        }

        # Check if container exists and is running
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Running}}", container_name],
                capture_output=True, text=True, check=True
            )
            state["exists"] = result.stdout.strip() == "true"
        except subprocess.CalledProcessError:
            return state

        if not state["exists"]:
            return state

        # Check if container has eth1 interface
        cmd = ["docker", "exec", container_name, "ip", "link", "show", "eth1"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        state["has_interface"] = (result.returncode == 0)

        # Check if veth exists in OVS (need to run inside ovs container)
        # Special handling for traffic generators to avoid name collision
        if container_name.startswith("traffic-gen"):
            veth_name = f"veth-tg-{container_name[-1]}"
        else:
            veth_name = f"veth-{container_name[:8]}"
        result = subprocess.run(
            ["docker", "exec", "ovs", "ovs-vsctl", "list-ports", "br-int"],
            capture_output=True, text=True
        )
        state["ovs_port_exists"] = veth_name in result.stdout

        # Check if OVN port exists
        port_name = f"lsp-{container_name}"
        try:
            self.ovn.run_nbctl(["lsp-get-addresses", port_name], quiet_errors=True)
            state["ovn_port_exists"] = True
        except subprocess.CalledProcessError:
            state["ovn_port_exists"] = False

        # Determine if repair is needed
        state["needs_repair"] = state["exists"] and (
            not state["has_interface"] or
            not state["ovs_port_exists"] or
            not state["ovn_port_exists"]
        )

        return state

    def cleanup_stale_ovs_ports(self):
        """Remove OVS ports for containers that no longer exist"""
        self.logger.info("Cleaning up stale OVS ports...")

        # Get all OVS ports (from inside OVS container)
        result = subprocess.run(
            ["docker", "exec", "ovs", "ovs-vsctl", "list-ports", "br-int"],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            return

        ports = result.stdout.strip().split('\n')

        for port in ports:
            if port.startswith("veth-"):
                # Extract container name from veth name
                container_name_prefix = port[5:]  # Remove "veth-" prefix

                # Check if any container matches this prefix
                result = subprocess.run(
                    ["docker", "ps", "--format", "{{.Names}}"],
                    capture_output=True, text=True
                )
                container_names = result.stdout.strip().split('\n')

                # Check if any running container matches
                port_has_container = any(
                    name[:8] == container_name_prefix
                    for name in container_names if name
                )

                if not port_has_container:
                    self.logger.info(f"Removing stale OVS port: {port}")
                    subprocess.run(
                        ["docker", "exec", "ovs", "ovs-vsctl", "del-port", "br-int", port],
                        check=False
                    )

    def cleanup_stale_ovn_ports(self):
        """Remove OVN logical ports for containers that no longer exist"""
        self.logger.info("Cleaning up stale OVN ports...")

        # Get all running containers
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True
        )
        running_containers = set(result.stdout.strip().split('\n'))

        # Get all logical switches
        switches = self.ovn.run_nbctl(["ls-list"]).strip().split('\n')

        for switch_line in switches:
            if switch_line:
                switch_name = switch_line.split()[1].strip('()')

                # Get ports on this switch
                ports = self.ovn.run_nbctl(["lsp-list", switch_name]).strip().split('\n')

                for port_line in ports:
                    if port_line and port_line.startswith("lsp-"):
                        port_name = port_line.split()[1].strip('()')
                        container_name = port_name[4:]  # Remove "lsp-" prefix

                        if container_name not in running_containers:
                            self.logger.info(f"Removing stale OVN port: {port_name}")
                            try:
                                self.ovn.run_nbctl(["lsp-del", port_name])
                            except subprocess.CalledProcessError:
                                pass

    def reconcile_container(self, container_name: str, ip_address: str, switch_name: str, mac_address: Optional[str] = None):
        """Reconcile network state for a single container"""
        state = self.get_container_network_state(container_name)

        # Get MAC from config if available
        if not mac_address and self.ovn.config_manager:
            container_config = self.ovn.config_manager.get_container_config(container_name)
            if container_config:
                mac_address = container_config.mac

        if not state["exists"]:
            self.logger.info(f"Container {container_name} does not exist, skipping")
            return False

        if not state["needs_repair"]:
            self.logger.info(f"Container {container_name} network is healthy")
            return True

        self.logger.info(f"Repairing network for container {container_name}")

        # Always clean up ALL existing state before reconnecting
        # This ensures we don't have partial or inconsistent configurations

        # Get container PID for cleanup
        try:
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Pid}}", container_name],
                capture_output=True, text=True, check=True
            )
            container_pid = result.stdout.strip()
        except subprocess.CalledProcessError:
            self.logger.error(f"Failed to get PID for container {container_name}")
            return False

        # Clean up container's eth1 interface if it exists
        if state["has_interface"]:
            self.logger.info(f"Removing existing eth1 interface from container {container_name}")
            subprocess.run(
                ["sudo", "nsenter", "-t", container_pid, "-n", "ip", "link", "delete", "eth1"],
                check=False, stderr=subprocess.DEVNULL
            )

        # Clean up OVS port
        # Special handling for traffic generators to avoid name collision
        if container_name.startswith("traffic-gen"):
            veth_name = f"veth-tg-{container_name[-1]}"
        else:
            veth_name = f"veth-{container_name[:8]}"
        if state["ovs_port_exists"]:
            self.logger.info(f"Removing existing OVS port {veth_name}")
            subprocess.run(
                ["sudo", "ovs-vsctl", "del-port", "br-int", veth_name],
                check=False, stderr=subprocess.DEVNULL
            )

        # Clean up host veth interface if it exists
        subprocess.run(
            ["sudo", "ip", "link", "delete", veth_name],
            check=False, stderr=subprocess.DEVNULL
        )

        # Clean up OVN logical port
        port_name = f"lsp-{container_name}"
        if state["ovn_port_exists"]:
            self.logger.info(f"Removing existing OVN port {port_name}")
            try:
                self.ovn.run_nbctl(["lsp-del", port_name])
            except subprocess.CalledProcessError:
                pass

        # Now reconnect from scratch with MAC address
        if self.ovn.connect_container_to_bridge(container_name, ip_address, "br-int", mac_address):
            if self.ovn.bind_container_to_ovn(container_name, switch_name, ip_address, mac_address):
                self.logger.info(f"Successfully repaired network for {container_name}")
                return True

        self.logger.error(f"Failed to repair network for {container_name}")
        return False

    def reconcile_all(self):
        """Reconcile network state for all containers"""
        self.logger.info("Starting network reconciliation...")

        # First, clean up stale ports
        self.cleanup_stale_ovs_ports()
        self.cleanup_stale_ovn_ports()

        # Get container configurations from config manager
        containers = []

        if self.ovn.config_manager:
            # Use configuration file
            for container_name, container_config in self.ovn.config_manager.containers.items():
                switch_name = container_config.switch
                ip_address = container_config.ip
                containers.append((container_name, ip_address, switch_name))
        else:
            # Fallback to hardcoded for backwards compatibility
            self.logger.warning("No config manager, using hardcoded container list")
            containers = [
                # VPC-A containers
                ("vpc-a-web", "10.0.1.10", "ls-vpc-a-web"),
                ("vpc-a-app", "10.0.2.10", "ls-vpc-a-app"),
                ("vpc-a-db", "10.0.3.10", "ls-vpc-a-db"),
                ("traffic-gen-a", "10.0.4.10", "ls-vpc-a-test"),

                # VPC-B containers
                ("vpc-b-web", "10.1.1.10", "ls-vpc-b-web"),
                ("vpc-b-app", "10.1.2.10", "ls-vpc-b-app"),
                ("vpc-b-db", "10.1.3.10", "ls-vpc-b-db"),
                ("traffic-gen-b", "10.1.4.10", "ls-vpc-b-test"),

                # NAT Gateway
                ("nat-gateway", "192.168.100.254", "ls-transit"),
            ]

        success_count = 0
        fail_count = 0

        for container_name, ip_address, switch_name in containers:
            try:
                if self.reconcile_container(container_name, ip_address, switch_name):
                    success_count += 1
                else:
                    fail_count += 1
            except Exception as e:
                self.logger.error(f"Error reconciling {container_name}: {e}")
                fail_count += 1

        self.logger.info(f"Reconciliation complete: {success_count} successful, {fail_count} failed")

        # Restart OVN controller to ensure flows are properly installed
        if success_count > 0:
            self.logger.info("Restarting OVN controller to apply flow changes...")
            subprocess.run(["sudo", "systemctl", "restart", "ovn-controller"], check=False)
            import time
            time.sleep(2)  # Give controller time to reconnect and install flows

        return fail_count == 0


class OVNManager:
    """Manages OVN topology and configuration"""

    def __init__(self, config_manager=None):
        # Use config manager if available
        self.config_manager = config_manager

        # Since we're running ovn-nbctl INSIDE the ovn-central container via docker exec,
        # we use 127.0.0.1 to connect to the local OVN databases
        if config_manager and config_manager.ovn_cluster:
            # Use cluster connection strings
            self.nb_db = config_manager.ovn_cluster.nb_connection
            self.sb_db = config_manager.ovn_cluster.sb_connection
        else:
            # Default single-node setup
            self.nb_db = "tcp://127.0.0.1:6641"
            self.sb_db = "tcp://127.0.0.1:6642"

        # Tenant mapping for VPCs
        if config_manager:
            # Build from config
            self.tenant_mapping = {}
            self.tenant_info = {}
            for vpc_name, vpc in config_manager.vpcs.items():
                self.tenant_mapping[vpc_name] = vpc.tenant
                if vpc.tenant not in self.tenant_info:
                    self.tenant_info[vpc.tenant] = {
                        "name": f"Customer {vpc.tenant}",
                        "vpc_id": vpc_name,
                        "billing_id": f"cust-{vpc.tenant}",
                        "environment": "production"
                    }
        else:
            # Legacy hardcoded mapping
            self.tenant_mapping = {
                "vpc-a": "tenant-1",
                "vpc-b": "tenant-2"
            }
            self.tenant_info = {
                "tenant-1": {
                    "name": "Customer A",
                    "vpc_id": "vpc-a",
                    "billing_id": "cust-001",
                    "environment": "production"
                },
                "tenant-2": {
                    "name": "Customer B",
                    "vpc_id": "vpc-b",
                    "billing_id": "cust-002",
                    "environment": "production"
                }
            }

    def run_nbctl(self, args: List[str], quiet_errors: bool = False) -> str:
        """Execute ovn-nbctl command inside ovn-central container"""
        # Use the default connection (unix socket) which is more reliable
        cmd = ["docker", "exec", "ovn-central", "ovn-nbctl"] + args
        logger.debug(f"Running: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            if not quiet_errors:
                logger.error(f"Command failed: {e.stderr}")
            raise

    def run_sbctl(self, args: List[str]) -> str:
        """Execute ovn-sbctl command inside ovn-central container"""
        # Use the default connection (unix socket) which is more reliable
        cmd = ["docker", "exec", "ovn-central", "ovn-sbctl"] + args
        logger.debug(f"Running: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed: {e.stderr}")
            raise

    def generate_mac_address(self) -> str:
        """Generate a random MAC address"""
        # Use locally administered address (second nibble = 2)
        mac = [0x02,
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff),
               random.randint(0x00, 0xff)]
        return ':'.join(f'{byte:02x}' for byte in mac)

    def setup_topology(self, create_containers=False):
        """Configure OVN logical topology for multi-VPC"""
        logger.info("Setting up OVN topology...")

        if self.config_manager:
            self._setup_topology_from_config()
        else:
            self._setup_topology_hardcoded()

        # Configure external connectivity for gateway router
        self._setup_external_connectivity()

        logger.info("OVN topology setup complete")

        # Create test containers if requested
        if create_containers:
            self.create_test_containers()

    def _setup_topology_from_config(self):
        """Setup topology based on configuration file"""
        logger.info("Setting up topology from configuration...")

        # Create gateway router
        transit_config = self.config_manager.config.get('transit', {})
        gateway_router = transit_config.get('gateway_router', {})
        self._create_logical_router(
            gateway_router.get('name', 'lr-gateway'),
            "External gateway router",
            tenant_id="shared"
        )

        # Create transit switch
        transit_cidr = transit_config.get('cidr', '192.168.100.0/24')
        self._create_logical_switch("ls-transit", transit_cidr, tenant_id="shared")

        # Create VPC routers and switches
        for vpc_name, vpc_config in self.config_manager.vpcs.items():
            router_name = vpc_config.router['name']
            tenant_id = vpc_config.tenant

            # Create VPC router
            self._create_logical_router(router_name, f"{vpc_name} router", tenant_id=tenant_id, vpc_id=vpc_name)

            # Create switches for this VPC
            for i, switch_config in enumerate(vpc_config.switches):
                switch_name = switch_config['name']
                switch_cidr = switch_config['cidr']
                tier = switch_config.get('tier', 'default')
                self._create_logical_switch(switch_name, switch_cidr, tenant_id=tenant_id, vpc_id=vpc_name, tier=tier)

                # Connect router to switch
                # Calculate gateway IP (first IP in subnet)
                import ipaddress
                network = ipaddress.ip_network(switch_cidr)
                gateway_ip = str(list(network.hosts())[0]) + "/" + str(network.prefixlen)
                # Generate MAC based on VPC and switch index
                # For vpc-a: 00:00:00:01:01:01, 00:00:00:01:02:01, etc
                # For vpc-b: 00:00:00:02:01:01, 00:00:00:02:02:01, etc
                vpc_num = 1 if 'vpc-a' in vpc_name else 2 if 'vpc-b' in vpc_name else 99
                gateway_mac = f"00:00:00:{vpc_num:02x}:{i+1:02x}:01"
                self._connect_router_to_switch(router_name, switch_name, gateway_ip, gateway_mac)

            # Connect VPC router to transit network
            vpc_transit_ip = f"192.168.100.{10 + ord(vpc_name[-1]) - ord('a')}/24"  # vpc-a: .10, vpc-b: .20
            vpc_transit_mac = f"00:00:00:00:00:{10 + ord(vpc_name[-1]) - ord('a'):02x}"
            self._connect_router_to_switch(router_name, "ls-transit", vpc_transit_ip, vpc_transit_mac)

        # Connect gateway router to transit
        self._connect_router_to_switch(
            gateway_router.get('name', 'lr-gateway'),
            "ls-transit",
            "192.168.100.1/24",
            gateway_router.get('mac', '00:00:00:00:00:01')
        )

        # Add routes based on VPCs
        self._setup_routes_from_config()

    def _setup_routes_from_config(self):
        """Setup routes based on configuration"""
        logger.info("Adding routes from configuration...")

        gateway_name = self.config_manager.config.get('transit', {}).get('gateway_router', {}).get('name', 'lr-gateway')

        # For each VPC, add routes
        for vpc_name, vpc_config in self.config_manager.vpcs.items():
            router_name = vpc_config.router['name']
            vpc_cidr = vpc_config.cidr
            vpc_transit_ip = f"192.168.100.{10 + ord(vpc_name[-1]) - ord('a')}"

            # Gateway needs route to VPC
            self._add_route_if_needed(gateway_name, vpc_cidr, vpc_transit_ip)

            # VPC needs default route to gateway
            self._add_route_if_needed(router_name, "0.0.0.0/0", "192.168.100.1")

            # Inter-VPC routes
            for other_vpc_name, other_vpc_config in self.config_manager.vpcs.items():
                if other_vpc_name != vpc_name:
                    other_vpc_cidr = other_vpc_config.cidr
                    other_vpc_transit_ip = f"192.168.100.{10 + ord(other_vpc_name[-1]) - ord('a')}"
                    self._add_route_if_needed(router_name, other_vpc_cidr, other_vpc_transit_ip)

    def _add_route_if_needed(self, router, prefix, nexthop):
        """Add route if it doesn't already exist"""
        try:
            existing_routes = self.run_nbctl(["lr-route-list", router])
            if prefix in existing_routes and nexthop in existing_routes:
                logger.debug(f"Route {prefix} via {nexthop} already exists on {router}")
            else:
                self.run_nbctl(["lr-route-add", router, prefix, nexthop])
                logger.info(f"Added route: {router} {prefix} -> {nexthop}")
        except subprocess.CalledProcessError as e:
            if "duplicate" in str(e.stderr):
                logger.debug(f"Route {prefix} already exists on {router}")
            else:
                raise

    def _setup_topology_hardcoded(self):
        """Fallback to hardcoded topology for backwards compatibility"""
        logger.warning("Using hardcoded topology - consider using configuration file")

        # Create logical routers with tenant ownership
        logger.info("Creating logical routers...")
        self._create_logical_router("lr-gateway", "External gateway router", tenant_id="shared")
        self._create_logical_router("lr-vpc-a", "VPC-A router", tenant_id="tenant-1", vpc_id="vpc-a")
        self._create_logical_router("lr-vpc-b", "VPC-B router", tenant_id="tenant-2", vpc_id="vpc-b")

        # Create logical switches for each VPC tier
        logger.info("Creating logical switches...")

        # VPC-A switches (Tenant 1)
        self._create_logical_switch("ls-vpc-a-web", "10.0.1.0/24", tenant_id="tenant-1", vpc_id="vpc-a", tier="web")
        self._create_logical_switch("ls-vpc-a-app", "10.0.2.0/24", tenant_id="tenant-1", vpc_id="vpc-a", tier="app")
        self._create_logical_switch("ls-vpc-a-db", "10.0.3.0/24", tenant_id="tenant-1", vpc_id="vpc-a", tier="db")
        self._create_logical_switch("ls-vpc-a-test", "10.0.4.0/24", tenant_id="tenant-1", vpc_id="vpc-a", tier="test")

        # VPC-B switches (Tenant 2)
        self._create_logical_switch("ls-vpc-b-web", "10.1.1.0/24", tenant_id="tenant-2", vpc_id="vpc-b", tier="web")
        self._create_logical_switch("ls-vpc-b-app", "10.1.2.0/24", tenant_id="tenant-2", vpc_id="vpc-b", tier="app")
        self._create_logical_switch("ls-vpc-b-db", "10.1.3.0/24", tenant_id="tenant-2", vpc_id="vpc-b", tier="db")
        self._create_logical_switch("ls-vpc-b-test", "10.1.4.0/24", tenant_id="tenant-2", vpc_id="vpc-b", tier="test")

        # Transit switch for inter-VPC routing (shared between tenants)
        self._create_logical_switch("ls-transit", "192.168.100.0/24", tenant_id="shared")

        # Connect routers to switches
        logger.info("Connecting routers to switches...")

        # Connect VPC-A router to its switches
        self._connect_router_to_switch("lr-vpc-a", "ls-vpc-a-web", "10.0.1.1/24", "00:00:00:01:01:01")
        self._connect_router_to_switch("lr-vpc-a", "ls-vpc-a-app", "10.0.2.1/24", "00:00:00:01:02:01")
        self._connect_router_to_switch("lr-vpc-a", "ls-vpc-a-db", "10.0.3.1/24", "00:00:00:01:03:01")
        self._connect_router_to_switch("lr-vpc-a", "ls-vpc-a-test", "10.0.4.1/24", "00:00:00:01:04:01")

        # Connect VPC-B router to its switches
        self._connect_router_to_switch("lr-vpc-b", "ls-vpc-b-web", "10.1.1.1/24", "00:00:00:02:01:01")
        self._connect_router_to_switch("lr-vpc-b", "ls-vpc-b-app", "10.1.2.1/24", "00:00:00:02:02:01")
        self._connect_router_to_switch("lr-vpc-b", "ls-vpc-b-db", "10.1.3.1/24", "00:00:00:02:03:01")
        self._connect_router_to_switch("lr-vpc-b", "ls-vpc-b-test", "10.1.4.1/24", "00:00:00:02:04:01")

        # Connect routers to transit network
        self._connect_router_to_switch("lr-gateway", "ls-transit", "192.168.100.1/24", "00:00:00:00:00:01")
        self._connect_router_to_switch("lr-vpc-a", "ls-transit", "192.168.100.10/24", "00:00:00:00:00:10")
        self._connect_router_to_switch("lr-vpc-b", "ls-transit", "192.168.100.20/24", "00:00:00:00:00:20")

        # Add routes
        logger.info("Adding routes...")

        # Define all routes
        routes = [
            ("lr-gateway", "10.0.0.0/16", "192.168.100.10"),
            ("lr-gateway", "10.1.0.0/16", "192.168.100.20"),
            ("lr-vpc-a", "0.0.0.0/0", "192.168.100.1"),
            ("lr-vpc-b", "0.0.0.0/0", "192.168.100.1"),
            ("lr-vpc-a", "10.1.0.0/16", "192.168.100.20"),
            ("lr-vpc-b", "10.0.0.0/16", "192.168.100.10"),
        ]

        for router, prefix, nexthop in routes:
            self._add_route_if_needed(router, prefix, nexthop)

    def _create_logical_router(self, name: str, comment: str = "", tenant_id: str = "", vpc_id: str = ""):
        """Create a logical router if it doesn't exist with tenant tracking"""
        try:
            existing = self.run_nbctl(["lr-list"])
            if name not in existing:
                self.run_nbctl(["lr-add", name])

                # Set external IDs for tenant tracking
                external_ids = []
                if comment:
                    external_ids.append(f"comment=\"{comment}\"")
                if tenant_id:
                    external_ids.append(f"tenant-id={tenant_id}")
                if vpc_id:
                    external_ids.append(f"vpc-id={vpc_id}")

                if external_ids:
                    for ext_id in external_ids:
                        self.run_nbctl(["set", "logical_router", name, f"external_ids:{ext_id}"])

                logger.info(f"Created logical router: {name} (tenant: {tenant_id or 'shared'})")
            else:
                logger.debug(f"Logical router {name} already exists")
        except Exception as e:
            logger.error(f"Failed to create logical router {name}: {e}")
            raise

    def _create_logical_switch(self, name: str, subnet: str = "", tenant_id: str = "", vpc_id: str = "", tier: str = ""):
        """Create a logical switch if it doesn't exist with tenant tracking"""
        try:
            existing = self.run_nbctl(["ls-list"])
            if name not in existing:
                self.run_nbctl(["ls-add", name])
                if subnet:
                    self.run_nbctl(["set", "logical_switch", name, f"other_config:subnet=\"{subnet}\""])

                # Set external IDs for tenant tracking
                if tenant_id:
                    self.run_nbctl(["set", "logical_switch", name, f"external_ids:tenant-id={tenant_id}"])
                if vpc_id:
                    self.run_nbctl(["set", "logical_switch", name, f"external_ids:vpc-id={vpc_id}"])
                if tier:
                    self.run_nbctl(["set", "logical_switch", name, f"external_ids:tier={tier}"])

                logger.info(f"Created logical switch: {name} ({subnet}) [tenant: {tenant_id or 'shared'}]")
            else:
                logger.debug(f"Logical switch {name} already exists")
        except Exception as e:
            logger.error(f"Failed to create logical switch {name}: {e}")
            raise

    def _setup_external_connectivity(self):
        """Configure external connectivity through NAT Gateway container"""
        logger.info("Configuring external connectivity through NAT Gateway...")

        # Get NAT gateway config if available
        nat_gateway_config = None
        if self.config_manager:
            nat_gateway_config = self.config_manager.get_container_config("nat-gateway")

        if nat_gateway_config:
            # Use configuration-based values with consistent naming
            port_name = "lsp-nat-gateway"  # Use standard lsp- prefix for consistency
            ip_address = nat_gateway_config.ip
            mac_address = nat_gateway_config.mac
            switch_name = nat_gateway_config.switch
            if not switch_name.startswith("ls-"):
                switch_name = f"ls-{switch_name}"
        else:
            # Fallback to defaults if no config
            port_name = "lsp-nat-gateway"
            ip_address = "192.168.100.254"
            mac_address = "02:00:00:00:00:fe"
            switch_name = "ls-transit"

        try:
            # Create OVN logical switch port for NAT Gateway on transit network
            existing_ports = self.run_nbctl(["lsp-list", switch_name])
            if port_name not in existing_ports:
                # Use configured MAC and IP
                self.run_nbctl(["lsp-add", switch_name, port_name])
                self.run_nbctl(["lsp-set-addresses", port_name, f"{mac_address} {ip_address}"])
                # Disable port security to allow routing of VPC traffic
                self.run_nbctl(["lsp-set-port-security", port_name, ""])
                logger.info(f"Created OVN port for NAT Gateway: {port_name} with MAC {mac_address} and IP {ip_address}")

            # Add default route on gateway router to NAT Gateway
            try:
                existing_routes = self.run_nbctl(["lr-route-list", "lr-gateway"])
                if "0.0.0.0/0" not in existing_routes:
                    # Route all external traffic to NAT Gateway container
                    self.run_nbctl(["lr-route-add", "lr-gateway", "0.0.0.0/0", ip_address])
                    logger.info(f"Added default route to NAT Gateway ({ip_address})")
            except subprocess.CalledProcessError as e:
                logger.warning(f"Failed to add default route: {e}")

            logger.info("External connectivity configured through NAT Gateway")

        except Exception as e:
            logger.error(f"Failed to setup external connectivity: {e}")
            logger.warning("Continuing without external connectivity")

    def _connect_router_to_switch(self, router: str, switch: str, ip: str, mac: str):
        """Connect a logical router to a logical switch"""
        try:
            # Check if router port already exists
            rport = f"{router}-{switch}"
            existing_ports = self.run_nbctl(["lrp-list", router])
            if rport not in existing_ports:
                self.run_nbctl(["lrp-add", router, rport, mac, ip])
                logger.info(f"Created router port: {rport}")
            else:
                logger.debug(f"Router port {rport} already exists")

            # Check if switch port already exists
            sport = f"{switch}-{router}"
            existing_switch_ports = self.run_nbctl(["lsp-list", switch])
            if sport not in existing_switch_ports:
                self.run_nbctl(["lsp-add", switch, sport])
                self.run_nbctl(["lsp-set-type", sport, "router"])
                self.run_nbctl(["lsp-set-addresses", sport, "router"])
                self.run_nbctl(["lsp-set-options", sport, f"router-port={rport}"])
                logger.info(f"Created switch port: {sport}")
            else:
                logger.debug(f"Switch port {sport} already exists")

            logger.debug(f"Connected {router} to {switch} at {ip}")
        except Exception as e:
            logger.error(f"Failed to connect {router} to {switch}: {e}")
            raise

    def create_test_containers(self):
        """Start test containers from docker-compose and attach them to OVS"""
        logger.info("Starting test containers...")

        # Start containers using docker-compose
        cmd = ["docker", "compose", "--profile", "testing", "--profile", "vpc", "up", "-d"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            logger.info("Test containers started successfully")
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to start test containers: {e.stderr}")
            return False

        # Wait for containers to be ready
        time.sleep(3)

        logger.info("Test containers ready. Use 'ovs-docker' to attach them to OVS bridges")
        return True


    def get_tenant_from_vpc(self, vpc_name: str) -> str:
        """Get tenant ID from VPC name"""
        # Special handling for traffic generators
        if vpc_name.startswith("traffic-gen-"):
            vpc_letter = vpc_name.split('-')[-1]  # Get 'a' or 'b' from traffic-gen-a/b
            return self.tenant_mapping.get(f"vpc-{vpc_letter}", "unknown")
        vpc_id = vpc_name.split('-')[1] if '-' in vpc_name else vpc_name
        return self.tenant_mapping.get(f"vpc-{vpc_id}", "unknown")

    def get_tenant_info(self, tenant_id: str) -> dict:
        """Get detailed tenant information"""
        return self.tenant_info.get(tenant_id, {})

    def set_port_tenant_ownership(self, port_name: str, tenant_id: str, vpc_id: str = ""):
        """Set tenant ownership on a logical switch port"""
        try:
            # Set external IDs for tenant tracking on the port
            self.run_nbctl(["set", "logical_switch_port", port_name, f"external_ids:tenant-id={tenant_id}"])
            if vpc_id:
                self.run_nbctl(["set", "logical_switch_port", port_name, f"external_ids:vpc-id={vpc_id}"])

            # Add creation timestamp
            timestamp = datetime.now(timezone.utc).isoformat()
            self.run_nbctl(["set", "logical_switch_port", port_name, f"external_ids:created-at={timestamp}"])
            self.run_nbctl(["set", "logical_switch_port", port_name, f"external_ids:created-by=orchestrator"])

            logger.info(f"Set tenant ownership for port {port_name}: tenant={tenant_id}, vpc={vpc_id}")
        except Exception as e:
            logger.error(f"Failed to set tenant ownership for port {port_name}: {e}")

    def show_topology(self):
        """Display current OVN topology"""
        logger.info("Current OVN topology:")
        print("\nLogical Routers:")
        print(self.run_nbctl(["lr-list"]))
        print("\nLogical Switches:")
        print(self.run_nbctl(["ls-list"]))
        print("\nNorthbound DB:")
        print(self.run_nbctl(["show"]))

    def show_tenant_ownership(self):
        """Display tenant ownership information for all resources"""
        print("\n" + "="*60)
        print("TENANT OWNERSHIP INFORMATION")
        print("="*60)

        # Show tenant info
        print("\nTenant Assignments:")
        for tenant_id, info in self.tenant_info.items():
            print(f"  {tenant_id}:")
            print(f"    Name: {info['name']}")
            print(f"    VPC: {info['vpc_id']}")
            print(f"    Billing ID: {info['billing_id']}")
            print(f"    Environment: {info['environment']}")

        # Show logical routers with tenant ownership
        print("\nLogical Routers:")
        try:
            routers = self.run_nbctl(["lr-list"]).strip().split('\n')
            for router_line in routers:
                if router_line:
                    router_name = router_line.split()[1].strip('()')
                    try:
                        tenant_id = self.run_nbctl(["get", "logical_router", router_name, "external_ids:tenant-id"]).strip().strip('"')
                        vpc_id = self.run_nbctl(["get", "logical_router", router_name, "external_ids:vpc-id"]).strip().strip('"')
                        print(f"  {router_name}: tenant={tenant_id or 'none'}, vpc={vpc_id or 'none'}")
                    except:
                        print(f"  {router_name}: no tenant info")
        except Exception as e:
            logger.error(f"Failed to get router info: {e}")

        # Show logical switches with tenant ownership
        print("\nLogical Switches:")
        try:
            switches = self.run_nbctl(["ls-list"]).strip().split('\n')
            for switch_line in switches:
                if switch_line:
                    switch_name = switch_line.split()[1].strip('()')
                    try:
                        tenant_id = self.run_nbctl(["get", "logical_switch", switch_name, "external_ids:tenant-id"]).strip().strip('"')
                        vpc_id = self.run_nbctl(["get", "logical_switch", switch_name, "external_ids:vpc-id"]).strip().strip('"')
                        tier = self.run_nbctl(["get", "logical_switch", switch_name, "external_ids:tier"]).strip().strip('"')
                        print(f"  {switch_name}: tenant={tenant_id or 'none'}, vpc={vpc_id or 'none'}, tier={tier or 'none'}")
                    except:
                        print(f"  {switch_name}: no tenant info")
        except Exception as e:
            logger.error(f"Failed to get switch info: {e}")

        # Show OVS interfaces with tenant ownership
        print("\nOVS Interfaces:")
        try:
            result = subprocess.run(["sudo", "ovs-vsctl", "list", "interface"], capture_output=True, text=True)
            if result.returncode == 0:
                interfaces = result.stdout.split('\n\n')
                for interface in interfaces:
                    if 'veth' in interface:
                        lines = interface.split('\n')
                        name = ""
                        external_ids = {}
                        for line in lines:
                            if line.startswith('name'):
                                name = line.split(':')[1].strip().strip('"')
                            elif line.startswith('external_ids'):
                                ext_str = line.split(':', 1)[1].strip()
                                if ext_str != '{}':
                                    # Parse external_ids
                                    ext_str = ext_str.strip('{}')
                                    for pair in ext_str.split(', '):
                                        if '=' in pair:
                                            key, val = pair.split('=', 1)
                                            external_ids[key.strip('"')] = val.strip('"')
                        if name and 'tenant-id' in external_ids:
                            print(f"  {name}: tenant={external_ids.get('tenant-id', 'none')}, vpc={external_ids.get('vpc-id', 'none')}")
        except Exception as e:
            logger.error(f"Failed to get OVS interface info: {e}")

        print("="*60)

    def setup_ovs_chassis(self):
        """Configure host OVS to connect to OVN and start ovn-controller via systemd"""
        logger.info("Setting up OVS as OVN chassis...")

        # Get OVN central IP
        cmd = ["docker", "inspect", "ovn-central", "-f", "{{range.NetworkSettings.Networks}}{{.IPAddress}}{{end}}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        ovn_ip = result.stdout.strip().split('\n')[0]  # Get first IP if multiple networks

        if not ovn_ip:
            logger.error("Cannot find OVN central IP address")
            return False

        logger.info(f"OVN Central IP: {ovn_ip}")

        # Get host IP for encapsulation
        # Use the IP that can reach the OVN central container
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect((ovn_ip, 6642))
        host_ip = s.getsockname()[0]
        s.close()
        logger.info(f"Using host IP for encapsulation: {host_ip}")

        # First configure OVS BEFORE starting ovn-controller
        logger.info("Configuring OVS to connect to OVN...")
        ovs_commands = [
            ["ovs-vsctl", "set", "open_vswitch", ".", f"external_ids:ovn-remote=tcp:{ovn_ip}:6642"],
            ["ovs-vsctl", "set", "open_vswitch", ".", f"external_ids:ovn-encap-ip={host_ip}"],
            ["ovs-vsctl", "set", "open_vswitch", ".", "external_ids:ovn-encap-type=geneve"],
            ["ovs-vsctl", "set", "open_vswitch", ".", "external_ids:system-id=chassis-host"],
        ]

        for cmd in ovs_commands:
            subprocess.run(["sudo"] + cmd, check=True)

        # Ensure br-int exists with userspace datapath
        subprocess.run([
            "sudo", "ovs-vsctl", "--may-exist", "add-br", "br-int",
            "--", "set", "bridge", "br-int", "datapath_type=netdev", "fail-mode=secure"
        ], check=True)

        # No need for external bridge configuration when using NAT Gateway container
        logger.info("External connectivity will be handled by NAT Gateway container")

        # Clean up any stale chassis that might have been created by previous runs
        logger.info("Cleaning up any stale chassis entries...")
        try:
            result = subprocess.run(
                ["docker", "exec", "ovn-central", "ovn-sbctl", "--format=csv", "--no-headings", "--columns=name,hostname", "list", "chassis"],
                capture_output=True, text=True
            )
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split(',')
                    if len(parts) >= 2:
                        chassis_name = parts[0].strip('"')
                        hostname = parts[1].strip('"')
                        # Delete any chassis from our host that isn't "chassis-host"
                        if hostname == "lima-ovs-lab" and chassis_name != "chassis-host":
                            logger.info(f"Removing stale chassis: {chassis_name}")
                            subprocess.run(
                                ["docker", "exec", "ovn-central", "ovn-sbctl", "chassis-del", chassis_name],
                                capture_output=True
                            )
        except Exception as e:
            logger.debug(f"Chassis cleanup: {e}")

        # Now start ovn-controller via systemd with correct config
        logger.info("Starting ovn-controller via systemd...")
        subprocess.run(["sudo", "systemctl", "restart", "ovn-controller"], check=True)

        # Wait for connection
        logger.info("Waiting for chassis registration...")
        time.sleep(5)

        # Verify chassis registration
        chassis_list = self.run_sbctl(["list", "chassis"])

        # Check if our chassis exists
        if "chassis-host" in chassis_list:
            logger.info("Chassis successfully registered with OVN")

            # Verify ovn-controller is connected
            result = subprocess.run(["sudo", "ovn-appctl", "-t", "ovn-controller", "connection-status"],
                                  capture_output=True, text=True)
            if result.returncode == 0 and "connected" in result.stdout.lower():
                logger.info("OVN controller is connected to southbound DB")
                return True
            else:
                logger.warning(f"OVN controller connection status: {result.stdout}")
                return True
        else:
            logger.error("Chassis registration failed")

            # Debug info
            result = subprocess.run(["sudo", "systemctl", "status", "ovn-controller"],
                                  capture_output=True, text=True)
            logger.error(f"ovn-controller status:\n{result.stdout}")

            # Check OVS configuration
            result = subprocess.run(["sudo", "ovs-vsctl", "get", "open_vswitch", ".", "external_ids"],
                                  capture_output=True, text=True)
            logger.info(f"OVS external_ids: {result.stdout}")

            return False

    def connect_container_to_bridge(self, container_name: str, ip_address: str, bridge: str = "br-int", mac_address: Optional[str] = None):
        """Connect a container directly to an OVS bridge without OVN"""
        logger.info(f"Connecting {container_name} to bridge {bridge} with IP {ip_address}")

        # Try to get MAC from config if not provided
        if not mac_address and self.config_manager:
            container_config = self.config_manager.get_container_config(container_name)
            if container_config:
                mac_address = container_config.mac
                logger.info(f"Using MAC from config: {mac_address}")

        try:
            # Get container PID
            result = subprocess.run(
                ["docker", "inspect", "-f", "{{.State.Pid}}", container_name],
                capture_output=True, text=True, check=True
            )
            container_pid = result.stdout.strip()

            if not container_pid or container_pid == "0":
                logger.error(f"Container {container_name} is not running")
                return False

            # Create veth pair
            # Special handling for traffic generators to avoid name collision
            if container_name.startswith("traffic-gen"):
                veth_host = f"veth-tg-{container_name[-1]}"
            else:
                veth_host = f"veth-{container_name[:8]}"
            veth_container = f"eth1"

            # Delete any existing veth pair
            subprocess.run(["sudo", "ip", "link", "delete", veth_host], check=False, stderr=subprocess.DEVNULL)

            # Create new veth pair
            subprocess.run([
                "sudo", "ip", "link", "add", veth_host, "type", "veth", "peer", "name", veth_container
            ], check=True)

            # Move container end to the container's network namespace
            subprocess.run([
                "sudo", "ip", "link", "set", veth_container, "netns", container_pid
            ], check=True)

            # Configure container interface
            subnet_prefix = ".".join(ip_address.split(".")[:-1])

            # Set MAC address if provided
            if mac_address:
                logger.info(f"Setting MAC address {mac_address} on {veth_container}")
                subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "link", "set", veth_container, "address", mac_address], check=True)

            subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "addr", "add", f"{ip_address}/24", "dev", veth_container], check=True)
            subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "link", "set", veth_container, "up"], check=True)

            # Add default route if it's not a local bridge network
            if bridge == "br-int":
                subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "route", "add", "default", "via", f"{subnet_prefix}.1"], check=False)

            # Add host end to OVS bridge (use --may-exist to handle if already there)
            subprocess.run(["sudo", "ovs-vsctl", "--may-exist", "add-port", bridge, veth_host], check=True)
            subprocess.run(["sudo", "ip", "link", "set", veth_host, "up"], check=True)

            # Disable checksum offloading to fix TCP with userspace OVS
            # This is critical for TCP to work with userspace datapath
            # Based on OVS mailing list discussions for userspace (non-DPDK) datapath
            logger.info(f"Disabling checksum offloading on {veth_host} for TCP compatibility")

            # Disable both TX and RX on host side
            subprocess.run(["sudo", "ethtool", "-K", veth_host, "tx", "off", "rx", "off"], check=False, stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "ethtool", "-K", veth_host, "tso", "off", "gso", "off"], check=False, stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "ethtool", "-K", veth_host, "gro", "off", "lro", "off"], check=False, stderr=subprocess.DEVNULL)

            # Disable on container side
            subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ethtool", "-K", veth_container, "tx", "off", "rx", "off"], check=False, stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ethtool", "-K", veth_container, "tso", "off", "gso", "off"], check=False, stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ethtool", "-K", veth_container, "gro", "off", "lro", "off"], check=False, stderr=subprocess.DEVNULL)

            logger.info(f"Successfully connected {container_name} to {bridge}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to connect container: {e}")
            return False

    def bind_container_to_ovn(self, container_name: str, switch_name: str, ip_address: str, mac_address: Optional[str] = None):
        """Bind a container to an OVN logical switch port"""
        logger.info(f"========================================")
        logger.info(f"Binding container {container_name} to OVN switch {switch_name} with IP {ip_address}")

        # Try to get MAC from config manager first
        if not mac_address and self.config_manager:
            container_config = self.config_manager.get_container_config(container_name)
            if container_config:
                mac_address = container_config.mac
                logger.info(f"Using MAC from config: {mac_address}")

        # Check if port already exists and if container is already connected
        port_name = f"lsp-{container_name}"

        # Check if the logical switch port already exists
        try:
            existing_addresses = self.run_nbctl(["lsp-get-addresses", port_name], quiet_errors=True)
            port_exists = True
            logger.info(f"Port {port_name} already exists with addresses: {existing_addresses}")
            # Extract MAC from existing port if we don't have one from config
            if existing_addresses and not mac_address:
                mac_address = existing_addresses.split()[0]
        except subprocess.CalledProcessError:
            port_exists = False
            logger.info(f"Port {port_name} does not exist, will create it")

        # Check if container already has the interface
        cmd = ["docker", "exec", container_name, "ip", "link", "show", "eth1"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        container_connected = (result.returncode == 0)

        if port_exists and container_connected:
            logger.info(f"Container {container_name} is already fully connected to OVN, skipping")
            return True

        # Create logical switch port if it doesn't exist
        if not port_exists:
            try:
                # Generate MAC if not provided
                if not mac_address:
                    mac_address = self.generate_mac_address()
                    logger.info(f"Generated MAC address for {container_name}: {mac_address}")

                self.run_nbctl(["lsp-add", switch_name, port_name])
                self.run_nbctl(["lsp-set-addresses", port_name, f"{mac_address} {ip_address}"])

                # NAT gateway needs port security disabled to forward traffic from VPCs
                if container_name == "nat-gateway":
                    self.run_nbctl(["lsp-set-port-security", port_name, ""])
                    logger.info(f"Disabled port security for NAT gateway to allow forwarding")
                else:
                    # CRITICAL: Set port security to match addresses or traffic will be dropped!
                    self.run_nbctl(["lsp-set-port-security", port_name, f"{mac_address} {ip_address}"])

                # Set tenant ownership on the port
                tenant_id = self.get_tenant_from_vpc(container_name)
                # Special handling for traffic generators
                if container_name.startswith("traffic-gen-"):
                    vpc_id = f"vpc-{container_name.split('-')[-1]}"
                else:
                    vpc_id = f"vpc-{container_name.split('-')[1]}" if '-' in container_name else ""
                self.set_port_tenant_ownership(port_name, tenant_id, vpc_id)

                logger.info(f"Created logical switch port {port_name} [tenant: {tenant_id}]")
            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to create port: {e}")
                return False

        # Skip physical connection if container already has the interface
        if container_connected:
            logger.info(f"Container {container_name} already has eth1 interface, skipping physical connection")
            # Double-check that the OVS side is also connected
            if container_name.startswith("traffic-gen"):
                expected_veth = f"veth-tg-{container_name[-1]}"
            else:
                expected_veth = f"veth-{container_name[:8]}"
            check_ovs = subprocess.run(["sudo", "ovs-vsctl", "list-ports", "br-int"], capture_output=True, text=True)
            if expected_veth not in check_ovs.stdout:
                logger.warning(f"Container {container_name} has eth1 but veth {expected_veth} not in OVS! State inconsistent.")
                # Don't return - try to fix it
            else:
                # Set ALL external_ids to bind the OVS port to the OVN logical port
                logger.info(f"Setting external_ids for existing interface {expected_veth}")
                tenant_id = self.get_tenant_from_vpc(container_name)
                if container_name.startswith("traffic-gen-"):
                    vpc_id = f"vpc-{container_name.split('-')[-1]}"
                else:
                    vpc_id = f"vpc-{container_name.split('-')[1]}" if '-' in container_name else ""

                # Set all external_ids at once
                cmd = [
                    "sudo", "ovs-vsctl",
                    "set", "interface", expected_veth,
                    f"external_ids:iface-id={port_name}",
                    f"external_ids:tenant-id={tenant_id}",
                    f"external_ids:container={container_name}"
                ]
                if vpc_id:
                    cmd.append(f"external_ids:vpc-id={vpc_id}")

                subprocess.run(cmd, check=True)
                return True

        # Ensure we have a MAC address for the physical interface
        if not mac_address:
            mac_address = self.generate_mac_address()
            logger.info(f"Generated MAC address for {container_name}: {mac_address}")

        # Get container PID for namespace operations
        cmd = ["docker", "inspect", "-f", "{{.State.Pid}}", container_name]
        result = subprocess.run(cmd, capture_output=True, text=True)
        container_pid = result.stdout.strip()

        if not container_pid or container_pid == "0":
            logger.error(f"Cannot get PID for container {container_name}")
            return False

        try:
            # Create veth pair and attach to container namespace
            # Use last 8 chars to avoid collision between traffic-gen-a and traffic-gen-b
            if container_name.startswith("traffic-gen"):
                veth_host = f"veth-tg-{container_name[-1]}"
            else:
                veth_host = f"veth-{container_name[:8]}"
            veth_cont = "eth1"

            # Delete if exists (but only if not attached to OVS)
            # Check if veth exists and is attached to OVS
            check_ovs = subprocess.run(["sudo", "ovs-vsctl", "list-ports", "br-int"], capture_output=True, text=True)
            if veth_host in check_ovs.stdout:
                logger.warning(f"veth {veth_host} already attached to OVS, this shouldn't happen! Container state may be inconsistent.")
                # Don't delete it - something is wrong
                return False
            subprocess.run(["sudo", "ip", "link", "del", veth_host], capture_output=True)

            # Create veth pair
            result = subprocess.run(["sudo", "ip", "link", "add", veth_host, "type", "veth", "peer", "name", veth_cont],
                                  capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to create veth pair for {container_name}: {result.stderr}")
                return False

            # Move one end to container namespace
            result = subprocess.run(["sudo", "ip", "link", "set", veth_cont, "netns", container_pid],
                                  capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to move veth to container namespace for {container_name}: {result.stderr}")
                # Clean up the veth pair
                subprocess.run(["sudo", "ip", "link", "del", veth_host], capture_output=True)
                return False

            # Configure container interface
            result = subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "link", "set", veth_cont, "address", mac_address],
                                  capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to set MAC address for {container_name}: {result.stderr}")
                subprocess.run(["sudo", "ip", "link", "del", veth_host], capture_output=True)
                return False

            result = subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "addr", "add", f"{ip_address}/24", "dev", veth_cont],
                                  capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to add IP address for {container_name}: {result.stderr}")
                subprocess.run(["sudo", "ip", "link", "del", veth_host], capture_output=True)
                return False

            result = subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "link", "set", veth_cont, "up"],
                                  capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to bring up interface for {container_name}: {result.stderr}")
                subprocess.run(["sudo", "ip", "link", "del", veth_host], capture_output=True)
                return False

            # Add default route in container
            gateway = ".".join(ip_address.split(".")[:3]) + ".1"
            subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "route", "add", "default", "via", gateway], capture_output=True)

            # Attach host end to OVS integration bridge
            # First check if port already exists
            result = subprocess.run(["sudo", "ovs-vsctl", "list-ports", "br-int"], capture_output=True, text=True)
            if veth_host not in result.stdout:
                # Prepare all external_ids for atomic operation
                tenant_id = self.get_tenant_from_vpc(container_name)
                if container_name.startswith("traffic-gen-"):
                    vpc_id = f"vpc-{container_name.split('-')[-1]}"
                else:
                    vpc_id = f"vpc-{container_name.split('-')[1]}" if '-' in container_name else ""

                # Add port with ALL external_ids in one atomic operation to avoid race condition
                cmd = [
                    "sudo", "ovs-vsctl",
                    "add-port", "br-int", veth_host,
                    "--", "set", "Interface", veth_host,
                    f"external_ids:iface-id={port_name}",
                    f"external_ids:tenant-id={tenant_id}",
                    f"external_ids:container={container_name}"
                ]
                if vpc_id:
                    cmd.append(f"external_ids:vpc-id={vpc_id}")

                result = subprocess.run(cmd, capture_output=True, text=True)
                if result.returncode != 0:
                    logger.error(f"Failed to add port to OVS for {container_name}: {result.stderr}")
                    subprocess.run(["sudo", "ip", "link", "del", veth_host], capture_output=True)
                    return False
            else:
                # Port exists, update ALL external_ids to ensure consistency
                tenant_id = self.get_tenant_from_vpc(container_name)
                if container_name.startswith("traffic-gen-"):
                    vpc_id = f"vpc-{container_name.split('-')[-1]}"
                else:
                    vpc_id = f"vpc-{container_name.split('-')[1]}" if '-' in container_name else ""

                # Update all external_ids at once
                cmd = [
                    "sudo", "ovs-vsctl",
                    "set", "interface", veth_host,
                    f"external_ids:iface-id={port_name}",
                    f"external_ids:tenant-id={tenant_id}",
                    f"external_ids:container={container_name}"
                ]
                if vpc_id:
                    cmd.append(f"external_ids:vpc-id={vpc_id}")

                subprocess.run(cmd, check=True)

            subprocess.run(["sudo", "ip", "link", "set", veth_host, "up"], check=True)

            # Disable checksum offloading to fix TCP with userspace OVS
            # This is critical for TCP to work with userspace datapath
            # Based on OVS mailing list discussions for userspace (non-DPDK) datapath
            logger.info(f"Disabling checksum offloading on {veth_host} for TCP compatibility")

            # Disable both TX and RX on host side
            subprocess.run(["sudo", "ethtool", "-K", veth_host, "tx", "off", "rx", "off"], check=False, stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "ethtool", "-K", veth_host, "tso", "off", "gso", "off"], check=False, stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "ethtool", "-K", veth_host, "gro", "off", "lro", "off"], check=False, stderr=subprocess.DEVNULL)

            # Disable on container side
            subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ethtool", "-K", veth_cont, "tx", "off", "rx", "off"], check=False, stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ethtool", "-K", veth_cont, "tso", "off", "gso", "off"], check=False, stderr=subprocess.DEVNULL)
            subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ethtool", "-K", veth_cont, "gro", "off", "lro", "off"], check=False, stderr=subprocess.DEVNULL)

            # Verify the interface actually exists in the container
            verify_cmd = ["docker", "exec", container_name, "ip", "addr", "show", "eth1"]
            result = subprocess.run(verify_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to verify eth1 in container {container_name} after setup")
                return False

            logger.info(f"✅ Container {container_name} successfully bound to OVN port {port_name}")
            logger.info(f"========================================")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"❌ Command failed while binding {container_name}: {e}")
            logger.info(f"========================================")
            # Try to clean up
            subprocess.run(["sudo", "ip", "link", "del", veth_host], capture_output=True)
            return False
        except Exception as e:
            logger.error(f"❌ Unexpected error binding {container_name}: {e}")
            logger.info(f"========================================")
            return False

    def setup_nat_gateway_networking(self):
        """Setup NAT Gateway with proper networking for external connectivity"""
        logger.info("Setting up NAT Gateway networking...")

        try:
            # 1. First ensure NAT Gateway container is running
            result = subprocess.run(["docker", "ps", "-q", "-f", "name=nat-gateway"],
                                  capture_output=True, text=True)
            if not result.stdout.strip():
                logger.info("Starting NAT Gateway container...")
                subprocess.run(["docker", "compose", "up", "-d", "nat-gateway"], check=True)
                time.sleep(3)

            # 2. NAT Gateway already connected to bridge network via docker-compose
            logger.info("NAT Gateway already on bridge network for internet access")

            # 3. Connect NAT Gateway to OVS/OVN for internal routing
            logger.info("Connecting NAT Gateway to OVN transit network...")
            # Use eth1 since eth0 is now the bridge network
            subprocess.run([
                "sudo", "/usr/bin/ovs-docker", "add-port", "br-int", "eth1",
                "nat-gateway", "--ipaddress=192.168.100.254/24"
            ], check=False)  # Ignore if already connected

            # 4. Get the actual MAC address of the NAT Gateway interface
            logger.info("Getting NAT Gateway MAC address...")
            mac_result = subprocess.run([
                "docker", "exec", "nat-gateway", "ip", "link", "show", "eth1"
            ], capture_output=True, text=True)

            nat_gateway_mac = None
            for line in mac_result.stdout.splitlines():
                if "link/ether" in line:
                    nat_gateway_mac = line.split()[1]
                    break

            if nat_gateway_mac:
                # Update OVN with the actual MAC address - use config if available
                nat_gateway_config = self.config_manager.get_container_config("nat-gateway") if self.config_manager else None
                ip_address = nat_gateway_config.ip if nat_gateway_config else "192.168.100.254"

                logger.info(f"Updating OVN with NAT Gateway MAC: {nat_gateway_mac}")
                subprocess.run([
                    "docker", "exec", "ovn-central", "ovn-nbctl",
                    "lsp-set-addresses", "lsp-nat-gateway",
                    f"{nat_gateway_mac} {ip_address}"
                ], check=False)

            # 5. Bind the OVN logical port to the physical interface
            logger.info("Binding NAT Gateway OVN port...")
            container_id = subprocess.run(["docker", "ps", "-q", "-f", "name=nat-gateway"],
                                        capture_output=True, text=True).stdout.strip()
            if container_id:
                # Find the actual interface name created by ovs-docker
                result = subprocess.run([
                    "sudo", "ovs-vsctl", "list-ports", "br-int"
                ], capture_output=True, text=True)

                # Look for the interface that matches the container
                for port in result.stdout.splitlines():
                    # Check if this port belongs to nat-gateway
                    check_result = subprocess.run([
                        "sudo", "ovs-vsctl", "get", "interface", port, "external_ids:container_id"
                    ], capture_output=True, text=True)
                    if "nat-gateway" in check_result.stdout:
                        # This is our interface, bind it to OVN with consistent naming
                        subprocess.run([
                            "sudo", "ovs-vsctl", "set", "interface", port,
                            f"external_ids:iface-id=lsp-nat-gateway"
                        ], check=False)
                        logger.info(f"NAT Gateway port {port} bound to OVN")
                        break

            # 6. Add routes in NAT Gateway for VPC subnets
            logger.info("Configuring NAT Gateway routes...")
            # Routes will be configured by entrypoint.sh

            logger.info("NAT Gateway networking setup complete")
            return True

        except Exception as e:
            logger.error(f"Failed to setup NAT Gateway networking: {e}")
            return False

    def setup_container_networking(self):
        """Set up OVN networking for all test containers (excluding traffic generators)"""
        logger.info("Setting up container networking via OVN...")

        # Setup NAT Gateway first
        self.setup_nat_gateway_networking()

        # Get container configuration from config manager or use defaults
        container_configs = []

        if self.config_manager:
            # Use configuration file for persistent MACs and IPs
            logger.info("Using container configuration from config file")
            for container_name, container_config in self.config_manager.containers.items():
                # Skip traffic generators - they have their own setup method
                if container_config.type != "traffic-generator":
                    container_configs.append({
                        "name": container_name,
                        "switch": container_config.switch,
                        "ip": container_config.ip,
                        "mac": container_config.mac  # Use persistent MAC from config
                    })
        else:
            # Fallback to hardcoded for backwards compatibility
            logger.warning("No config manager, using hardcoded container list")
            container_configs = [
                # VPC-A containers (no traffic generators here)
                {"name": "vpc-a-web", "switch": "ls-vpc-a-web", "ip": "10.0.1.10", "mac": None},
                {"name": "vpc-a-app", "switch": "ls-vpc-a-app", "ip": "10.0.2.10", "mac": None},
                {"name": "vpc-a-db", "switch": "ls-vpc-a-db", "ip": "10.0.3.10", "mac": None},
                # VPC-B containers (no traffic generators here)
                {"name": "vpc-b-web", "switch": "ls-vpc-b-web", "ip": "10.1.1.10", "mac": None},
                {"name": "vpc-b-app", "switch": "ls-vpc-b-app", "ip": "10.1.2.10", "mac": None},
                {"name": "vpc-b-db", "switch": "ls-vpc-b-db", "ip": "10.1.3.10", "mac": None},
            ]

        successful = 0
        failed = 0
        skipped = 0

        for config in container_configs:
            # Check if container exists and is running
            result = subprocess.run(["docker", "ps", "-q", "-f", f"name={config['name']}"], capture_output=True, text=True)
            if result.stdout.strip():
                # Use MAC from config (persistent) or let bind_container_to_ovn handle it
                success = self.bind_container_to_ovn(
                    config["name"],
                    config["switch"],
                    config["ip"],
                    config.get("mac")  # Pass MAC from config, or None to generate
                )
                if success:
                    successful += 1
                else:
                    failed += 1
                    logger.error(f"FAILED to bind container {config['name']} to OVN")
            else:
                logger.warning(f"Container {config['name']} not found or not running")
                skipped += 1

        if failed > 0:
            logger.error(f"Container networking setup had failures: {successful} successful, {failed} failed, {skipped} not running")
        elif skipped > 0:
            logger.info(f"Container networking setup complete: {successful} containers bound successfully ({skipped} containers not running)")
        else:
            logger.info(f"Container networking setup complete: {successful} containers bound successfully")

    def setup_traffic_generators_only(self):
        """Set up OVN networking ONLY for traffic generator containers"""
        logger.info("Setting up traffic generator networking via OVN...")

        # Get traffic generator configuration
        traffic_gen_configs = []

        if self.config_manager:
            # Use configuration file for persistent MACs and IPs
            logger.info("Using traffic generator configuration from config file")
            for container_name, container_config in self.config_manager.containers.items():
                # Only include traffic generators
                if container_config.type == "traffic-generator":
                    traffic_gen_configs.append({
                        "name": container_name,
                        "switch": container_config.switch,
                        "ip": container_config.ip,
                        "mac": container_config.mac  # Use persistent MAC from config
                    })
        else:
            # Fallback to hardcoded for backwards compatibility
            logger.warning("No config manager, using hardcoded traffic generator list")
            traffic_gen_configs = [
                {"name": "traffic-gen-a", "switch": "ls-vpc-a-test", "ip": "10.0.4.10", "mac": None},
                {"name": "traffic-gen-b", "switch": "ls-vpc-b-test", "ip": "10.1.4.10", "mac": None},
            ]

        successful = 0
        failed = 0
        for config in traffic_gen_configs:
            # Check if container exists
            result = subprocess.run(["docker", "ps", "-q", "-f", f"name={config['name']}"], capture_output=True, text=True)
            if result.stdout.strip():
                # Check if already has network - BE IDEMPOTENT!
                check_cmd = ["docker", "exec", config['name'], "ip", "link", "show", "eth1"]
                check_result = subprocess.run(check_cmd, capture_output=True, text=True)
                if check_result.returncode == 0:
                    logger.info(f"Traffic generator {config['name']} already has network interface, skipping")
                    successful += 1
                    continue

                # Use MAC from config (persistent) or let bind_container_to_ovn handle it
                success = self.bind_container_to_ovn(
                    config["name"],
                    config["switch"],
                    config["ip"],
                    config.get("mac")  # Pass MAC from config, or None to generate
                )
                if success:
                    successful += 1
                else:
                    failed += 1
                    logger.error(f"FAILED to bind traffic generator {config['name']} to OVN")
            else:
                logger.warning(f"Traffic generator {config['name']} not found")
                failed += 1

        if failed > 0:
            logger.error(f"Traffic generator setup FAILED: {successful} successful, {failed} failed")
            return False
        else:
            logger.info(f"Traffic generator setup complete: {successful} generators bound successfully")
            return True


# DockerNetworkManager removed - was trying to use non-existent "openvswitch" driver
# Containers should be attached directly to OVS bridges instead


class NetworkChecker:
    """Comprehensive network state checker"""

    def __init__(self, config_manager=None):
        self.config_manager = config_manager

    def check_all(self):
        """Run all network checks"""
        print("\n" + "="*60)
        print("NETWORK DIAGNOSTIC CHECK")
        print("="*60)

        issues = []

        # Check OVS
        print("\n1. OVS Bridge Status:")
        print("-" * 40)
        ovs_issues = self._check_ovs()
        issues.extend(ovs_issues)

        # Check OVN
        print("\n2. OVN Logical Configuration:")
        print("-" * 40)
        ovn_issues = self._check_ovn()
        issues.extend(ovn_issues)

        # Check bindings
        print("\n3. OVN Port Bindings:")
        print("-" * 40)
        binding_issues = self._check_bindings()
        issues.extend(binding_issues)

        # Check connectivity
        print("\n4. Container Connectivity:")
        print("-" * 40)
        conn_issues = self._check_connectivity()
        issues.extend(conn_issues)

        # Check NAT gateway
        print("\n5. NAT Gateway Status:")
        print("-" * 40)
        nat_issues = self._check_nat_gateway()
        issues.extend(nat_issues)

        # Summary
        print("\n" + "="*60)
        print("DIAGNOSTIC SUMMARY")
        print("="*60)
        if issues:
            print(f"\n❌ Found {len(issues)} issues:\n")
            for i, issue in enumerate(issues, 1):
                print(f"  {i}. {issue}")
        else:
            print("\n✅ All checks passed!")

        return len(issues) == 0

    def _check_ovs(self):
        """Check OVS configuration"""
        issues = []

        # Check if br-int exists
        result = subprocess.run(["sudo", "ovs-vsctl", "br-exists", "br-int"],
                              capture_output=True)
        if result.returncode != 0:
            print("  ❌ br-int bridge does not exist")
            issues.append("OVS integration bridge (br-int) missing")
        else:
            print("  ✓ br-int bridge exists")

        # Check ports on br-int
        result = subprocess.run(["sudo", "ovs-vsctl", "list-ports", "br-int"],
                              capture_output=True, text=True)
        ports = result.stdout.strip().split('\n') if result.stdout.strip() else []
        print(f"  ✓ {len(ports)} ports on br-int")

        # Check for external_ids on interfaces
        missing_iface_id = []
        for port in ports:
            if port and not port.startswith("ovn"):  # Skip OVN tunnel ports
                result = subprocess.run(
                    ["sudo", "ovs-vsctl", "get", "interface", port, "external_ids:iface-id"],
                    capture_output=True, text=True
                )
                if not result.stdout.strip() or result.returncode != 0:
                    missing_iface_id.append(port)

        if missing_iface_id:
            print(f"  ❌ {len(missing_iface_id)} ports missing iface-id: {', '.join(missing_iface_id)}")
            issues.append(f"OVS ports missing iface-id binding: {', '.join(missing_iface_id)}")
        else:
            print("  ✓ All ports have iface-id set")

        return issues

    def _check_ovn(self):
        """Check OVN logical configuration"""
        issues = []

        # Check logical routers
        result = subprocess.run(
            ["docker", "exec", "ovn-central", "ovn-nbctl", "lr-list"],
            capture_output=True, text=True
        )
        routers = [line.split()[1].strip('()') for line in result.stdout.strip().split('\n') if line]
        expected_routers = ["lr-gateway", "lr-vpc-a", "lr-vpc-b"]
        missing_routers = [r for r in expected_routers if r not in routers]

        if missing_routers:
            print(f"  ❌ Missing routers: {', '.join(missing_routers)}")
            issues.append(f"Missing logical routers: {', '.join(missing_routers)}")
        else:
            print(f"  ✓ All {len(expected_routers)} logical routers present")

        # Check logical switches
        result = subprocess.run(
            ["docker", "exec", "ovn-central", "ovn-nbctl", "ls-list"],
            capture_output=True, text=True
        )
        switches = [line.split()[1].strip('()') for line in result.stdout.strip().split('\n') if line]
        print(f"  ✓ {len(switches)} logical switches configured")

        # Check NAT gateway port
        result = subprocess.run(
            ["docker", "exec", "ovn-central", "ovn-nbctl", "lsp-get-addresses", "lsp-nat-gateway"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print("  ❌ NAT gateway port (lsp-nat-gateway) not found")
            issues.append("NAT gateway logical port missing")
        else:
            print(f"  ✓ NAT gateway port configured: {result.stdout.strip()}")

        return issues

    def _check_bindings(self):
        """Check OVN port bindings to chassis"""
        issues = []

        # Get all logical ports - note the type='' needs proper escaping
        result = subprocess.run(
            ["docker", "exec", "ovn-central", "ovn-sbctl", "find", "port_binding", "type=\"\""],
            capture_output=True, text=True
        )

        unbound_ports = []
        bound_ports = 0
        current_port = None

        for line in result.stdout.split('\n'):
            # Lines have format "key : value" with spaces
            if 'logical_port' in line and ':' in line:
                # Extract port name after the colon
                parts = line.split(':', 1)
                if len(parts) > 1:
                    current_port = parts[1].strip().strip('"')
            elif line.startswith('chassis') and ':' in line and current_port:
                # Extract chassis value after the colon (ignore additional_chassis, gateway_chassis, etc.)
                parts = line.split(':', 1)
                if len(parts) > 1:
                    chassis = parts[1].strip()
                    if chassis == '[]' or not chassis:
                        unbound_ports.append(current_port)
                    else:
                        bound_ports += 1
                    current_port = None  # Reset after processing

        if unbound_ports:
            print(f"  ❌ {len(unbound_ports)} ports not bound to chassis: {', '.join(unbound_ports[:5])}")
            issues.append(f"Unbound OVN ports: {', '.join(unbound_ports)}")
        else:
            print(f"  ✓ All {bound_ports} ports bound to chassis")

        return issues

    def _check_connectivity(self):
        """Check basic connectivity"""
        issues = []

        # Test one internal ping
        result = subprocess.run(
            ["docker", "exec", "vpc-a-web", "ping", "-c", "1", "-W", "1", "10.0.1.1"],
            capture_output=True
        )
        if result.returncode != 0:
            print("  ❌ Container cannot reach its gateway (10.0.1.1)")
            issues.append("Container to gateway connectivity failed")
        else:
            print("  ✓ Container can reach its gateway")

        # Check ARP entries
        result = subprocess.run(
            ["docker", "exec", "vpc-a-web", "arp", "-n"],
            capture_output=True, text=True
        )
        if "incomplete" in result.stdout:
            print("  ⚠ Incomplete ARP entries detected")
        else:
            print("  ✓ ARP resolution working")

        return issues

    def _check_nat_gateway(self):
        """Check NAT gateway configuration"""
        issues = []

        # Check if NAT gateway container is running
        result = subprocess.run(
            ["docker", "ps", "-q", "-f", "name=nat-gateway"],
            capture_output=True, text=True
        )
        if not result.stdout.strip():
            print("  ❌ NAT gateway container not running")
            issues.append("NAT gateway container not running")
            return issues
        else:
            print("  ✓ NAT gateway container running")

        # Check NAT gateway interfaces
        result = subprocess.run(
            ["docker", "exec", "nat-gateway", "ip", "addr", "show", "eth1"],
            capture_output=True, text=True
        )
        if "192.168.100.254" not in result.stdout:
            print("  ❌ NAT gateway missing expected IP (192.168.100.254)")
            issues.append("NAT gateway IP misconfigured")
        else:
            print("  ✓ NAT gateway has correct IP")

        # Check iptables NAT rules
        result = subprocess.run(
            ["docker", "exec", "nat-gateway", "iptables", "-t", "nat", "-L", "POSTROUTING", "-n"],
            capture_output=True, text=True
        )
        if "MASQUERADE" not in result.stdout:
            print("  ❌ NAT gateway missing MASQUERADE rule")
            issues.append("NAT gateway iptables rules missing")
        else:
            print("  ✓ NAT gateway has MASQUERADE rule")

        # CRITICAL: Check NAT gateway port security is disabled
        result = subprocess.run(
            ["docker", "exec", "ovn-central", "ovn-nbctl", "lsp-get-port-security", "lsp-nat-gateway"],
            capture_output=True, text=True
        )
        port_security = result.stdout.strip()
        if result.returncode != 0:
            print("  ⚠ Could not check NAT gateway port security")
        elif port_security:
            print(f"  ❌ NAT gateway port security is ENABLED: {port_security}")
            print("     This will block forwarded traffic from VPCs!")
            issues.append("NAT gateway port security must be disabled for traffic forwarding")
        else:
            print("  ✓ NAT gateway port security is disabled (required for forwarding)")

        # Check if NAT gateway can reach external
        result = subprocess.run(
            ["docker", "exec", "nat-gateway", "ping", "-c", "1", "-W", "1", "8.8.8.8"],
            capture_output=True
        )
        if result.returncode != 0:
            print("  ❌ NAT gateway cannot reach external (8.8.8.8)")
            issues.append("NAT gateway has no external connectivity")
        else:
            print("  ✓ NAT gateway can reach external")

        return issues


class TestRunner:
    """Runs connectivity and performance tests"""

    def __init__(self, config_manager=None):
        self.config_manager = config_manager

    def test_connectivity(self):
        """Test connectivity between VPCs"""
        print("\n" + "="*60)
        print("RUNNING CONNECTIVITY TESTS")
        print("="*60)

        # First check if containers exist
        cmd = ["docker", "ps", "--format", "{{.Names}}", "--filter", "label=ovs-lab=true"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        containers = result.stdout.strip().split('\n')

        if len(containers) < 2:
            logger.error("Test containers not found. Please run 'make test-start' first")
            return False

        # Get container IPs from config or use defaults
        container_ips = {}
        if self.config_manager:
            for container_name, container_config in self.config_manager.containers.items():
                container_ips[container_name] = container_config.ip
        else:
            # Fallback to hardcoded for backwards compatibility
            container_ips = {
                "vpc-a-web": "10.0.1.10",
                "vpc-a-app": "10.0.2.10",
                "vpc-a-db": "10.0.3.10",
                "vpc-b-web": "10.1.1.10",
                "vpc-b-app": "10.1.2.10",
                "vpc-b-db": "10.1.3.10",
            }

        # Internal connectivity tests
        internal_tests = [
            # Intra-VPC tests (same VPC, different subnets)
            ("vpc-a-web", "vpc-a-app", "VPC-A: web to app tier"),
            ("vpc-a-app", "vpc-a-db", "VPC-A: app to db tier"),

            ("vpc-b-web", "vpc-b-app", "VPC-B: web to app tier"),
            ("vpc-b-app", "vpc-b-db", "VPC-B: app to db tier"),

            # Inter-VPC tests (between VPCs)
            ("vpc-a-web", "vpc-b-web", "Inter-VPC: A-web to B-web"),
            ("vpc-a-app", "vpc-b-app", "Inter-VPC: A-app to B-app"),
        ]

        # External connectivity tests
        external_tests = [
            ("vpc-a-web", "8.8.8.8", "External: VPC-A to Internet (8.8.8.8)"),
            ("vpc-b-web", "8.8.8.8", "External: VPC-B to Internet (8.8.8.8)"),
            ("vpc-a-app", "1.1.1.1", "External: VPC-A to Cloudflare DNS"),
            ("vpc-b-app", "1.1.1.1", "External: VPC-B to Cloudflare DNS"),
        ]

        # Run internal connectivity tests
        print("\nInternal Connectivity Tests:")
        print("-"*60)
        internal_results = []
        for source, target, description in internal_tests:
            # Get target IP from our known mapping
            target_ip = container_ips.get(target)

            if target_ip:
                print(f"  Testing: {description:45}", end="", flush=True)
                result = self._test_ping(source, target_ip, description)
                status = "✅ PASS" if result else "❌ FAIL"
                print(f" {status}")
                internal_results.append((description, result))
            else:
                logger.warning(f"Could not find IP for {target}")
                internal_results.append((description, False))

        # Run external connectivity tests
        print("\nExternal Connectivity Tests:")
        print("-"*60)
        external_results = []
        for source, target_ip, description in external_tests:
            print(f"  Testing: {description:45}", end="", flush=True)
            result = self._test_ping(source, target_ip, description)
            status = "✅ PASS" if result else "❌ FAIL"
            print(f" {status}")
            external_results.append((description, result))

        # Print summary
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)

        internal_passed = sum(1 for _, r in internal_results if r)
        external_passed = sum(1 for _, r in external_results if r)
        total_internal = len(internal_results)
        total_external = len(external_results)

        print(f"\nInternal: {internal_passed}/{total_internal} passed")
        print(f"External: {external_passed}/{total_external} passed")
        print(f"Total: {internal_passed + external_passed}/{total_internal + total_external} passed")

        return (internal_passed == total_internal) and (external_passed == total_external)

    def _test_ping(self, source: str, target: str, description: str) -> bool:
        """Test ping connectivity between containers"""
        cmd = ["docker", "exec", source, "ping", "-c", "2", "-W", "2", target]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
            success = result.returncode == 0
            if success:
                logger.debug(f"{description}: Success")
            else:
                logger.warning(f"{description}: Failed")
            return success
        except subprocess.TimeoutExpired:
            logger.warning(f"{description}: Timeout")
            return False
        except Exception as e:
            logger.error(f"{description}: Error - {e}")
            return False

    def test_traffic_prerequisites(self):
        """Test that all prerequisites for traffic generation are met"""
        print("\n" + "="*60)
        print("TESTING TRAFFIC GENERATION PREREQUISITES")
        print("="*60)

        passed = 0
        failed = 0

        # 1. Check traffic generator containers exist and are running
        print("\n1. Checking traffic generator containers...")
        traffic_gens = ["traffic-gen-a", "traffic-gen-b"]
        for gen in traffic_gens:
            cmd = ["docker", "ps", "-q", "-f", f"name={gen}"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.stdout.strip():
                print(f"  ✓ {gen} is running")
                passed += 1
            else:
                print(f"  ✗ {gen} is NOT running - run 'make traffic-start' first")
                failed += 1

        # 2. Check VPC containers exist and are running
        print("\n2. Checking VPC containers...")
        vpc_containers = ["vpc-a-web", "vpc-a-app", "vpc-a-db", "vpc-b-web", "vpc-b-app", "vpc-b-db"]
        for container in vpc_containers:
            cmd = ["docker", "ps", "-q", "-f", f"name={container}"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.stdout.strip():
                print(f"  ✓ {container} is running")
                passed += 1
            else:
                print(f"  ✗ {container} is NOT running")
                failed += 1

        # 3. Check traffic generators have network interfaces
        print("\n3. Checking traffic generator network interfaces...")
        for gen in traffic_gens:
            # First check if container exists before trying to exec into it
            check_cmd = ["docker", "ps", "-q", "-f", f"name={gen}"]
            check_result = subprocess.run(check_cmd, capture_output=True, text=True)
            if not check_result.stdout.strip():
                print(f"  ✗ {gen} is not running - skipping interface check")
                failed += 1
                continue

            cmd = ["docker", "exec", gen, "ip", "addr", "show", "eth1"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0 and "inet " in result.stdout:
                ip = [line for line in result.stdout.split('\n') if 'inet ' in line][0].split()[1].split('/')[0]
                print(f"  ✓ {gen} has eth1 interface with IP {ip}")
                passed += 1
            else:
                print(f"  ✗ {gen} does NOT have eth1 interface - run 'make attach' to fix")
                failed += 1

        # 4. Check VPC containers are listening on expected ports
        print("\n4. Checking VPC container listeners...")
        port_checks = [
            ("vpc-a-web", ["80", "443", "5201"], "web"),
            ("vpc-a-app", ["8080", "8443", "5201"], "app"),
            ("vpc-a-db", ["3306", "5432", "5201"], "db"),
            ("vpc-b-web", ["80", "443", "5201"], "web"),
            ("vpc-b-app", ["8080", "8443", "5201"], "app"),
            ("vpc-b-db", ["3306", "5432", "5201"], "db"),
        ]

        for container, ports, tier in port_checks:
            cmd = ["docker", "exec", container, "sh", "-c", "netstat -tln 2>/dev/null || ss -tln"]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                listening_ports = []
                for port in ports:
                    if f":{port}" in result.stdout:
                        listening_ports.append(port)

                if len(listening_ports) == len(ports):
                    print(f"  ✓ {container} listening on all {tier} ports: {', '.join(ports)}")
                    passed += 1
                else:
                    missing = set(ports) - set(listening_ports)
                    print(f"  ✗ {container} missing listeners on ports: {', '.join(missing)}")
                    failed += 1
            else:
                print(f"  ✗ {container} - could not check listeners")
                failed += 1

        # 5. Test connectivity from traffic generators to VPC containers
        print("\n5. Testing connectivity from traffic generators to VPC containers...")
        connectivity_tests = [
            ("traffic-gen-a", "10.0.1.10", "traffic-gen-a → vpc-a-web"),
            ("traffic-gen-a", "10.0.2.10", "traffic-gen-a → vpc-a-app"),
            ("traffic-gen-a", "10.0.3.10", "traffic-gen-a → vpc-a-db"),
            ("traffic-gen-b", "10.1.1.10", "traffic-gen-b → vpc-b-web"),
            ("traffic-gen-b", "10.1.2.10", "traffic-gen-b → vpc-b-app"),
            ("traffic-gen-b", "10.1.3.10", "traffic-gen-b → vpc-b-db"),
        ]

        for source, target_ip, description in connectivity_tests:
            # Check if source container exists first
            check_cmd = ["docker", "ps", "-q", "-f", f"name={source}"]
            check_result = subprocess.run(check_cmd, capture_output=True, text=True)
            if not check_result.stdout.strip():
                print(f"  ✗ {description} - source container not running")
                failed += 1
                continue

            cmd = ["docker", "exec", source, "ping", "-c", "1", "-W", "2", target_ip]
            result = subprocess.run(cmd, capture_output=True, text=True)
            if result.returncode == 0:
                print(f"  ✓ {description}")
                passed += 1
            else:
                print(f"  ✗ {description} - FAILED")
                failed += 1

        # 6. Test port connectivity (not just ICMP)
        print("\n6. Testing port connectivity to VPC services...")
        port_tests = [
            ("traffic-gen-a", "10.0.1.10", "80", "HTTP to vpc-a-web"),
            ("traffic-gen-a", "10.0.2.10", "8080", "App port to vpc-a-app"),
            ("traffic-gen-b", "10.1.1.10", "80", "HTTP to vpc-b-web"),
            ("traffic-gen-b", "10.1.2.10", "8080", "App port to vpc-b-app"),
        ]

        for source, target_ip, port, description in port_tests:
            # Check if source container exists first
            check_cmd = ["docker", "ps", "-q", "-f", f"name={source}"]
            check_result = subprocess.run(check_cmd, capture_output=True, text=True)
            if not check_result.stdout.strip():
                print(f"  ✗ {description} (port {port}) - source container not running")
                failed += 1
                continue

            cmd = ["docker", "exec", source, "nc", "-zv", "-w", "2", target_ip, port]
            result = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            if result.stdout and ("succeeded" in result.stdout or "open" in result.stdout):
                print(f"  ✓ {description} (port {port})")
                passed += 1
            else:
                print(f"  ✗ {description} (port {port}) - FAILED")
                failed += 1

        # Summary
        print("\n" + "="*60)
        print("TRAFFIC TEST SUMMARY")
        print("="*60)
        print(f"Passed: {passed}")
        print(f"Failed: {failed}")
        print(f"Total:  {passed + failed}")

        if failed == 0:
            print("\n✅ All traffic generation prerequisites are met!")
            print("You can now run 'make traffic-run' to generate traffic")
            return True
        else:
            print(f"\n❌ {failed} prerequisites failed. Fix these issues before generating traffic.")
            if "traffic-gen" in str(failed):
                print("\nHint: Run 'make traffic-start' to start traffic generators")
            return False


class MonitoringManager:
    """Manages monitoring setup for OVS on the host"""

    def __init__(self):
        # Detect architecture
        import platform
        arch = platform.machine()
        if arch == "aarch64" or arch == "arm64":
            self.arch = "arm64"
        elif arch == "x86_64":
            self.arch = "amd64"
        else:
            raise ValueError(f"Unsupported architecture: {arch}")

        self.exporter_url = f"https://github.com/Liquescent-Development/ovs_exporter/releases/download/v2.3.1/ovs-exporter-2.3.1.linux-{self.arch}.tar.gz"
        self.service_name = "ovs-exporter"  # Note: service name uses hyphen

    def setup_ovs_exporter(self) -> bool:
        """Download and install OVS exporter on the host"""
        logger.info(f"Setting up OVS exporter on host (arch: {self.arch})...")

        try:
            # Clean up any previous installation attempts
            logger.info("Cleaning up any previous installation...")
            subprocess.run(["bash", "-c", "rm -rf /tmp/ovs-exporter*"], check=False)

            # Download the exporter package
            logger.info(f"Downloading OVS exporter for {self.arch}...")
            subprocess.run([
                "wget", "-q", "-O", f"/tmp/ovs-exporter-2.3.1.linux-{self.arch}.tar.gz",
                self.exporter_url
            ], check=True)

            # Extract the package
            logger.info("Extracting OVS exporter package...")
            subprocess.run([
                "tar", "xzf", f"/tmp/ovs-exporter-2.3.1.linux-{self.arch}.tar.gz", "-C", "/tmp"
            ], check=True)

            # Stop service first if running to avoid "text file busy"
            subprocess.run(["systemctl", "stop", self.service_name], check=False)

            # Copy the binary to /usr/local/bin
            logger.info("Installing OVS exporter binary...")
            subprocess.run([
                "cp", f"/tmp/ovs-exporter-2.3.1.linux-{self.arch}/ovs-exporter",
                "/usr/local/bin/ovs-exporter"
            ], check=True)

            subprocess.run([
                "chmod", "+x", "/usr/local/bin/ovs-exporter"
            ], check=True)

            # Sync system-id from OVS database to config file
            logger.info("Syncing system-id from OVS database to config file...")
            try:
                result = subprocess.run(
                    ["ovs-vsctl", "get", "open_vswitch", ".", "external_ids:system-id"],
                    capture_output=True, text=True, check=True
                )
                system_id = result.stdout.strip().strip('"')  # Remove quotes if present

                # Create the directory if it doesn't exist
                subprocess.run(["mkdir", "-p", "/etc/openvswitch"], check=True)

                # Write the system-id to the config file
                with open("/etc/openvswitch/system-id.conf", "w") as f:
                    f.write(system_id + "\n")

                logger.info(f"Synced system-id: {system_id}")
            except subprocess.CalledProcessError as e:
                logger.warning(f"Could not sync system-id: {e}")
                # Continue anyway - the exporter might work without it

            # Create systemd service file with proper flags
            logger.info("Creating systemd service...")
            service_content = """[Unit]
Description=OVS Exporter for Prometheus
After=network.target openvswitch-switch.service ovn-controller.service
Wants=openvswitch-switch.service

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/ovs-exporter \
  --web.listen-address=:9475 \
  --web.telemetry-path=/metrics \
  --ovs.timeout=2 \
  --ovs.poll-interval=15 \
  --log.level=info \
  --system.run.dir=/var/run/openvswitch \
  --database.vswitch.name=Open_vSwitch \
  --database.vswitch.socket.remote=unix:/var/run/openvswitch/db.sock \
  --database.vswitch.file.data.path=/etc/openvswitch/conf.db \
  --database.vswitch.file.log.path=/var/log/openvswitch/ovsdb-server.log \
  --database.vswitch.file.pid.path=/var/run/openvswitch/ovsdb-server.pid \
  --database.vswitch.file.system.id.path=/etc/openvswitch/system-id.conf \
  --service.vswitchd.file.log.path=/var/log/openvswitch/ovs-vswitchd.log \
  --service.vswitchd.file.pid.path=/var/run/openvswitch/ovs-vswitchd.pid \
  --service.ovncontroller.file.log.path=/var/log/ovn/ovn-controller.log \
  --service.ovncontroller.file.pid.path=/var/run/ovn/ovn-controller.pid
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
"""
            with open(f"/etc/systemd/system/{self.service_name}.service", "w") as f:
                f.write(service_content)

            # Reload systemd and start service
            logger.info("Starting OVS exporter service...")
            subprocess.run(["systemctl", "daemon-reload"], check=True)
            subprocess.run(["systemctl", "enable", self.service_name], check=True)
            subprocess.run(["systemctl", "restart", self.service_name], check=True)

            # Clean up temporary files
            logger.info("Cleaning up temporary files...")
            subprocess.run(["bash", "-c", f"rm -rf /tmp/ovs-exporter-2.3.1.linux-{self.arch}*"], check=False)

            # Verify the service is running
            time.sleep(2)
            result = subprocess.run(
                ["systemctl", "is-active", self.service_name],
                capture_output=True, text=True
            )

            if result.stdout.strip() == "active":
                logger.info("OVS exporter service is running")

                # Test the metrics endpoint
                try:
                    result = subprocess.run([
                        "curl", "-s", "http://localhost:9475/metrics"
                    ], capture_output=True, text=True, check=True)

                    if "ovs_" in result.stdout or "server_id" in result.stdout:
                        logger.info("OVS exporter metrics endpoint is working correctly")
                        return True
                    else:
                        logger.warning("Metrics endpoint accessible but no OVS metrics found")
                        return True
                except:
                    logger.warning("Could not verify metrics endpoint")

                return True
            else:
                logger.error(f"OVS exporter service is not active: {result.stdout.strip()}")
                # Try to get more info
                subprocess.run(["systemctl", "status", self.service_name, "-l"], check=False)
                return False

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to setup OVS exporter: {e}")
            return False
        except Exception as e:
            logger.error(f"Unexpected error setting up OVS exporter: {e}")
            return False

    def setup_node_exporter(self) -> bool:
        """Install and configure node_exporter on the host"""
        logger.info("Setting up node_exporter on host...")

        try:
            # Install node_exporter via apt
            subprocess.run([
                "apt-get", "install", "-y", "prometheus-node-exporter"
            ], check=True, capture_output=True)

            # Enable and start the service
            subprocess.run(["systemctl", "enable", "prometheus-node-exporter"], check=True)
            subprocess.run(["systemctl", "restart", "prometheus-node-exporter"], check=True)

            logger.info("Node exporter is running on port 9100")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to setup node_exporter: {e}")
            return False


class ChaosEngineer:
    """Implements chaos testing scenarios using Pumba"""

    def __init__(self):
        self.scenarios = {
            "packet-loss": self._packet_loss,
            "latency": self._add_latency,
            "bandwidth": self._limit_bandwidth,
            "partition": self._network_partition,
            "corruption": self._packet_corruption,
            "duplication": self._packet_duplication,
            "underlay-chaos": self._underlay_chaos,
            "overlay-test": self._overlay_resilience_test,
            "mixed": self._mixed_chaos,
        }

    def run_scenario(self, scenario: str, duration: int = 60, target: str = "vpc-.*"):
        """Run a chaos scenario using Pumba"""
        if scenario not in self.scenarios:
            logger.error(f"Unknown scenario: {scenario}")
            return False

        logger.info(f"Running chaos scenario: {scenario} for {duration}s on pattern: {target}")
        self.scenarios[scenario](target, duration)
        return True

    def _run_pumba(self, cmd: list, background: bool = False):
        """Execute Pumba command"""
        full_cmd = ["docker", "run", "--rm", "-v", "/var/run/docker.sock:/var/run/docker.sock", "gaiaadm/pumba"] + cmd

        if background:
            proc = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return proc
        else:
            result = subprocess.run(full_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Pumba command failed: {result.stderr}")
            return result

    def _packet_loss(self, target: str, duration: int):
        """Introduce packet loss using Pumba"""
        logger.info(f"Introducing 30% packet loss on containers matching: {target}")
        cmd = [
            "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
            "loss", "--percent", "30", f"re2:{target}"
        ]
        self._run_pumba(cmd)
        logger.info("Packet loss scenario completed")

    def _add_latency(self, target: str, duration: int):
        """Add network latency using Pumba"""
        logger.info(f"Adding 100ms latency with 20ms jitter on containers matching: {target}")
        cmd = [
            "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
            "delay", "--time", "100", "--jitter", "20", f"re2:{target}"
        ]
        self._run_pumba(cmd)
        logger.info("Latency scenario completed")

    def _limit_bandwidth(self, target: str, duration: int):
        """Limit network bandwidth using Pumba"""
        logger.info(f"Limiting bandwidth to 1mbit on containers matching: {target}")
        cmd = [
            "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
            "rate", "--rate", "1mbit", f"re2:{target}"
        ]
        self._run_pumba(cmd)
        logger.info("Bandwidth limit scenario completed")

    def _network_partition(self, target: str, duration: int):
        """Create network partition by pausing containers"""
        logger.info(f"Creating network partition by pausing containers matching: {target}")
        cmd = [
            "pause", "--duration", f"{duration}s", f"re2:{target}"
        ]
        self._run_pumba(cmd)
        logger.info("Network partition scenario completed")

    def _packet_corruption(self, target: str, duration: int):
        """Introduce packet corruption using Pumba"""
        logger.info(f"Introducing 5% packet corruption on containers matching: {target}")
        cmd = [
            "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
            "corrupt", "--percent", "5", f"re2:{target}"
        ]
        self._run_pumba(cmd)
        logger.info("Packet corruption scenario completed")

    def _packet_duplication(self, target: str, duration: int):
        """Introduce packet duplication using Pumba"""
        logger.info(f"Introducing 10% packet duplication on containers matching: {target}")
        cmd = [
            "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
            "duplicate", "--percent", "10", f"re2:{target}"
        ]
        self._run_pumba(cmd)
        logger.info("Packet duplication scenario completed")

    def _underlay_chaos(self, target: str, duration: int):
        """Test underlay network failure by targeting host OVS containers"""
        logger.info("Testing underlay network chaos - targeting OVS/OVN infrastructure")

        # Target the underlay infrastructure (OVS instances)
        underlay_targets = ["ovs-vpc-a", "ovs-vpc-b", "ovn-central"]

        for infra_target in underlay_targets:
            logger.info(f"Applying packet loss to underlay component: {infra_target}")
            cmd = [
                "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
                "loss", "--percent", "20", infra_target
            ]
            # Run in background to affect multiple targets simultaneously
            self._run_pumba(cmd, background=True)

        # Wait for duration
        time.sleep(duration)
        logger.info("Underlay chaos scenario completed - overlay should have shown resilience")

    def _overlay_resilience_test(self, target: str, duration: int):
        """Test overlay network resilience by introducing various failures"""
        logger.info("Testing overlay network resilience with combined failures")

        # Run multiple chaos scenarios simultaneously
        scenarios = [
            ["netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
             "loss", "--percent", "15", "re2:vpc-a-.*"],
            ["netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
             "delay", "--time", "50", "--jitter", "10", "re2:vpc-b-.*"],
            ["netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
             "corrupt", "--percent", "2", "re2:traffic-gen-.*"],
        ]

        procs = []
        for cmd in scenarios:
            proc = self._run_pumba(cmd, background=True)
            procs.append(proc)

        # Monitor during chaos
        logger.info(f"Running overlay resilience test for {duration} seconds...")
        logger.info("Monitor Grafana dashboards to observe overlay behavior during underlay chaos")

        # Wait for all scenarios to complete
        for proc in procs:
            proc.wait()

        logger.info("Overlay resilience test completed")

    def _mixed_chaos(self, target: str, duration: int):
        """Run mixed chaos scenarios for traffic-chaos mode"""
        logger.info("Running mixed chaos scenarios - heavy internal traffic stress test")

        # Run multiple chaos scenarios with varied intensity
        scenarios = [
            ["netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
             "loss", "--percent", "20", f"re2:{target}"],
            ["netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
             "delay", "--time", "100", "--jitter", "25", f"re2:{target}"],
            ["netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
             "corrupt", "--percent", "5", f"re2:{target}"],
            ["netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
             "duplicate", "--percent", "10", f"re2:{target}"],
        ]

        procs = []
        for i, cmd in enumerate(scenarios):
            # Stagger the start of each scenario slightly
            if i > 0:
                time.sleep(2)
            proc = self._run_pumba(cmd, background=True)
            procs.append(proc)

        logger.info(f"Mixed chaos running for {duration} seconds with packet loss, delay, corruption, and duplication")
        logger.info("Combined with heavy traffic generation, this simulates extreme network stress")

        # Wait for all scenarios to complete
        for proc in procs:
            if proc:
                proc.wait()

        logger.info("Mixed chaos scenario completed")


def main():
    """Main entry point"""
    # Initialize config manager if available
    config_manager = None
    if CONFIG_MANAGER_AVAILABLE:
        config_path = os.environ.get('NETWORK_CONFIG', 'network-config.yaml')
        if Path(config_path).exists():
            config_manager = NetworkConfigManager(config_path)
            if config_manager.load_config():
                logger.info(f"Loaded network config from {config_path}")
            else:
                logger.warning("Failed to load network config, using defaults")
                config_manager = None

    parser = argparse.ArgumentParser(description="OVS Container Lab Orchestrator")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Up command - comprehensive setup
    up_parser = subparsers.add_parser("up", help="Complete setup of OVS Container Lab")

    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Setup OVN topology")

    # Setup-chassis command
    chassis_parser = subparsers.add_parser("setup-chassis", help="Configure OVS as OVN chassis")

    # Bind-containers command
    bind_parser = subparsers.add_parser("bind-containers", help="Bind containers to OVN")

    # Bind-traffic-generators command
    bind_traffic_parser = subparsers.add_parser("bind-traffic-generators", help="Bind ONLY traffic generator containers to OVN")

    # Setup-monitoring command
    monitoring_parser = subparsers.add_parser("setup-monitoring", help="Setup monitoring exporters on host")

    # Test command
    test_parser = subparsers.add_parser("test", help="Run connectivity tests")

    # Check command
    check_parser = subparsers.add_parser("check", help="Run comprehensive network diagnostics")


    # Chaos command
    chaos_parser = subparsers.add_parser("chaos", help="Run chaos scenarios")
    chaos_parser.add_argument("scenario", choices=[
        "packet-loss", "latency", "bandwidth", "partition",
        "corruption", "duplication", "underlay-chaos", "overlay-test", "mixed"
    ])
    chaos_parser.add_argument("--duration", type=int, default=60, help="Duration in seconds")
    chaos_parser.add_argument("--target", default="vpc-.*", help="Target container regex pattern")

    # Reconcile command
    reconcile_parser = subparsers.add_parser("reconcile", help="Reconcile network state for all containers")
    reconcile_parser.add_argument("--container", help="Reconcile specific container only")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Execute commands
    if args.command == "setup":
        ovn = OVNManager(config_manager)
        ovn.setup_topology()

    elif args.command == "setup-chassis":
        ovn = OVNManager(config_manager)
        success = ovn.setup_ovs_chassis()
        return 0 if success else 1

    elif args.command == "bind-containers":
        ovn = OVNManager(config_manager)
        ovn.setup_container_networking()

    elif args.command == "bind-traffic-generators":
        ovn = OVNManager(config_manager)
        success = ovn.setup_traffic_generators_only()
        return 0 if success else 1

    elif args.command == "setup-monitoring":
        monitor = MonitoringManager()
        success = monitor.setup_ovs_exporter() and monitor.setup_node_exporter()
        return 0 if success else 1

    elif args.command == "test":
        tester = TestRunner(config_manager)
        success = tester.test_connectivity()
        return 0 if success else 1
    elif args.command == "check":
        checker = NetworkChecker(config_manager)
        success = checker.check_all()
        return 0 if success else 1


    elif args.command == "chaos":
        chaos = ChaosEngineer()
        chaos.run_scenario(args.scenario, args.duration, args.target)

    elif args.command == "up":
        # Comprehensive setup with proper order and error handling
        logger.info("🚀 Starting OVS Container Lab with proper orchestration...")

        # Step 1: Setup monitoring exporters (non-critical, can fail)
        logger.info("Step 1/6: Setting up monitoring exporters...")
        monitor = MonitoringManager()
        if not monitor.setup_ovs_exporter() or not monitor.setup_node_exporter():
            logger.error("❌ Monitoring setup failed. Cannot proceed.")
            return 1
        logger.info("✓ Monitoring exporters ready")

        # Step 2: Wait for OVN central to be healthy
        logger.info("Step 2/6: Waiting for OVN central to be ready...")
        max_wait = 30
        for i in range(max_wait):
            result = subprocess.run(
                ["docker", "exec", "ovn-central", "ovn-nbctl", "show"],
                capture_output=True, text=True
            )
            if result.returncode == 0:
                logger.info("✓ OVN central is ready")
                break
            if i == max_wait - 1:
                logger.error("❌ OVN central not ready after 30 seconds. Cannot proceed.")
                return 1
            time.sleep(1)

        # Step 3: Setup OVS chassis
        logger.info("Step 3/6: Configuring OVS as OVN chassis...")
        ovn = OVNManager(config_manager)
        if not ovn.setup_ovs_chassis():
            logger.error("❌ Failed to setup OVS chassis. Cannot proceed.")
            return 1
        logger.info("✓ OVS chassis configured")

        # Step 4: Wait for ALL containers to be running
        logger.info("Step 4/6: Waiting for all containers to be running...")
        required_containers = [
            "vpc-a-web", "vpc-a-app", "vpc-a-db", "traffic-gen-a",
            "vpc-b-web", "vpc-b-app", "vpc-b-db", "traffic-gen-b",
            "nat-gateway"
        ]

        max_wait = 30
        for i in range(max_wait):
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}"],
                capture_output=True, text=True
            )
            running = result.stdout.strip().split('\n')
            missing = [c for c in required_containers if c not in running]

            if not missing:
                logger.info("✓ All containers are running")
                break

            if i == max_wait - 1:
                logger.error(f"❌ Containers not running after 30 seconds: {missing}")
                logger.error("Cannot proceed without all containers.")
                return 1

            if i % 5 == 0:
                logger.info(f"  Waiting for containers: {missing}")
            time.sleep(1)

        # Step 5: NOW setup OVN topology (AFTER containers exist!)
        logger.info("Step 5/6: Creating OVN logical topology...")
        ovn.setup_topology()
        logger.info("✓ OVN topology created")

        # Step 6: Bind containers to OVN
        logger.info("Step 6/6: Binding containers to OVN...")
        ovn.setup_container_networking()

        # Also bind traffic generators
        logger.info("Binding traffic generators...")
        ovn.setup_traffic_generators_only()

        # Verify bindings are successful
        time.sleep(2)  # Brief wait for bindings to settle
        checker = NetworkChecker(config_manager)
        issues = checker._check_bindings()
        if issues:
            logger.error("❌ Port binding verification failed:")
            for issue in issues:
                logger.error(f"  {issue}")
            return 1

        logger.info("✅ OVS Container Lab is ready!")
        logger.info("")
        logger.info("Access points:")
        logger.info("  Grafana:    http://localhost:3000 (admin/admin)")
        logger.info("  Prometheus: http://localhost:9090")
        logger.info("")
        logger.info("Next steps:")
        logger.info("  make check        - Verify everything is configured correctly")
        logger.info("  make traffic-run  - Generate normal traffic")
        return 0

    elif args.command == "reconcile":
        ovn = OVNManager(config_manager)
        reconciler = NetworkReconciler(ovn)

        if args.container:
            # Find the container's configuration
            containers = [
                ("vpc-a-web", "10.0.1.10", "ls-vpc-a-web"),
                ("vpc-a-app", "10.0.2.10", "ls-vpc-a-app"),
                ("vpc-a-db", "10.0.3.10", "ls-vpc-a-db"),
                ("traffic-gen-a", "10.0.4.10", "ls-vpc-a-test"),
                ("vpc-b-web", "10.1.1.10", "ls-vpc-b-web"),
                ("vpc-b-app", "10.1.2.10", "ls-vpc-b-app"),
                ("vpc-b-db", "10.1.3.10", "ls-vpc-b-db"),
                ("traffic-gen-b", "10.1.4.10", "ls-vpc-b-test"),
                ("nat-gateway", "192.168.100.254", "ls-transit"),
            ]

            for name, ip, switch in containers:
                if name == args.container:
                    success = reconciler.reconcile_container(name, ip, switch)
                    return 0 if success else 1

            logger.error(f"Unknown container: {args.container}")
            return 1
        else:
            success = reconciler.reconcile_all()
            return 0 if success else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())