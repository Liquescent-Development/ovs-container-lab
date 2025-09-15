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

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)


class OVNManager:
    """Manages OVN topology and configuration"""

    def __init__(self):
        # Since we're running ovn-nbctl INSIDE the ovn-central container via docker exec,
        # we use 127.0.0.1 to connect to the local OVN databases
        self.nb_db = "tcp://127.0.0.1:6641"
        self.sb_db = "tcp://127.0.0.1:6642"

        # Tenant mapping for VPCs
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

    def run_nbctl(self, args: List[str]) -> str:
        """Execute ovn-nbctl command inside ovn-central container"""
        # Use the default connection (unix socket) which is more reliable
        cmd = ["docker", "exec", "ovn-central", "ovn-nbctl"] + args
        logger.debug(f"Running: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
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
            try:
                # Check if route already exists
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

        # Configure external connectivity for gateway router
        self._setup_external_connectivity()

        logger.info("OVN topology setup complete")

        # Create test containers if requested
        if create_containers:
            self.create_test_containers()

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

        try:
            # Create OVN logical switch port for NAT Gateway on transit network
            port_name = "ls-transit-nat-gateway"
            existing_ports = self.run_nbctl(["lsp-list", "ls-transit"])
            if port_name not in existing_ports:
                # Use dynamic MAC address
                self.run_nbctl(["lsp-add", "ls-transit", port_name])
                self.run_nbctl(["lsp-set-addresses", port_name, "dynamic 192.168.100.254"])
                # Disable port security to allow routing of VPC traffic
                self.run_nbctl(["lsp-set-port-security", port_name, ""])
                logger.info(f"Created OVN port for NAT Gateway: {port_name}")

            # Add default route on gateway router to NAT Gateway
            try:
                existing_routes = self.run_nbctl(["lr-route-list", "lr-gateway"])
                if "0.0.0.0/0" not in existing_routes:
                    # Route all external traffic to NAT Gateway container
                    self.run_nbctl(["lr-route-add", "lr-gateway", "0.0.0.0/0", "192.168.100.254"])
                    logger.info("Added default route to NAT Gateway (192.168.100.254)")
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
            from datetime import datetime
            timestamp = datetime.utcnow().isoformat() + "Z"
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

    def connect_container_to_bridge(self, container_name: str, ip_address: str, bridge: str = "br-int"):
        """Connect a container directly to an OVS bridge without OVN"""
        logger.info(f"Connecting {container_name} to bridge {bridge} with IP {ip_address}")

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
            subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "addr", "add", f"{ip_address}/24", "dev", veth_container], check=True)
            subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "link", "set", veth_container, "up"], check=True)

            # Add default route if it's not a local bridge network
            if bridge == "br-int":
                subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "route", "add", "default", "via", f"{subnet_prefix}.1"], check=False)

            # Add host end to OVS bridge
            subprocess.run(["sudo", "ovs-vsctl", "add-port", bridge, veth_host], check=True)
            subprocess.run(["sudo", "ip", "link", "set", veth_host, "up"], check=True)

            logger.info(f"Successfully connected {container_name} to {bridge}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to connect container: {e}")
            return False

    def bind_container_to_ovn(self, container_name: str, switch_name: str, ip_address: str, mac_address: Optional[str] = None):
        """Bind a container to an OVN logical switch port"""
        logger.info(f"Binding container {container_name} to OVN switch {switch_name}...")

        # Check if port already exists and if container is already connected
        port_name = f"lsp-{container_name}"

        # Check if the logical switch port already exists
        try:
            existing_addresses = self.run_nbctl(["lsp-get-addresses", port_name])
            port_exists = True
            logger.info(f"Port {port_name} already exists with addresses: {existing_addresses}")
            # Extract MAC from existing port
            if existing_addresses:
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
            return

        # Create logical switch port if it doesn't exist
        if not port_exists:
            try:
                # Generate MAC if not provided
                if not mac_address:
                    mac_address = self.generate_mac_address()
                    logger.info(f"Generated MAC address for {container_name}: {mac_address}")

                self.run_nbctl(["lsp-add", switch_name, port_name])
                self.run_nbctl(["lsp-set-addresses", port_name, f"{mac_address} {ip_address}"])

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
                return

        # Skip physical connection if container already has the interface
        if container_connected:
            logger.info(f"Container {container_name} already has eth1 interface, skipping physical connection")
            return

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

            # Delete if exists
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
                # Add port with external_ids in one atomic operation to avoid race condition
                result = subprocess.run([
                    "sudo", "ovs-vsctl",
                    "add-port", "br-int", veth_host,
                    "--", "set", "Interface", veth_host, f"external_ids:iface-id={port_name}"
                ], capture_output=True, text=True)
                if result.returncode != 0:
                    logger.error(f"Failed to add port to OVS for {container_name}: {result.stderr}")
                    subprocess.run(["sudo", "ip", "link", "del", veth_host], capture_output=True)
                    return False
            else:
                # Port exists, just update external_ids
                subprocess.run(["sudo", "ovs-vsctl", "set", "interface", veth_host, f"external_ids:iface-id={port_name}"], check=True)

            # Also set tenant ownership on the OVS interface
            tenant_id = self.get_tenant_from_vpc(container_name)
            subprocess.run(["sudo", "ovs-vsctl", "set", "interface", veth_host, f"external_ids:tenant-id={tenant_id}"], check=True)
            # Special handling for traffic generators
            if container_name.startswith("traffic-gen-"):
                vpc_id = f"vpc-{container_name.split('-')[-1]}"
            else:
                vpc_id = f"vpc-{container_name.split('-')[1]}" if '-' in container_name else ""
            if vpc_id:
                subprocess.run(["sudo", "ovs-vsctl", "set", "interface", veth_host, f"external_ids:vpc-id={vpc_id}"], check=True)

            subprocess.run(["sudo", "ip", "link", "set", veth_host, "up"], check=True)

            # Verify the interface actually exists in the container
            verify_cmd = ["docker", "exec", container_name, "ip", "addr", "show", "eth1"]
            result = subprocess.run(verify_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                logger.error(f"Failed to verify eth1 in container {container_name} after setup")
                return False

            logger.info(f"Container {container_name} successfully bound to OVN port {port_name}")
            return True

        except subprocess.CalledProcessError as e:
            logger.error(f"Command failed while binding {container_name}: {e}")
            # Try to clean up
            subprocess.run(["sudo", "ip", "link", "del", veth_host], capture_output=True)
            return False
        except Exception as e:
            logger.error(f"Unexpected error binding {container_name}: {e}")
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
                # Update OVN with the actual MAC address
                logger.info(f"Updating OVN with NAT Gateway MAC: {nat_gateway_mac}")
                subprocess.run([
                    "docker", "exec", "ovn-central", "ovn-nbctl",
                    "lsp-set-addresses", "ls-transit-nat-gateway",
                    f"{nat_gateway_mac} 192.168.100.254"
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
                        # This is our interface, bind it to OVN
                        subprocess.run([
                            "sudo", "ovs-vsctl", "set", "interface", port,
                            f"external_ids:iface-id=ls-transit-nat-gateway"
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
        """Set up OVN networking for all test containers"""
        logger.info("Setting up container networking via OVN...")

        # Setup NAT Gateway first
        self.setup_nat_gateway_networking()

        # Container to OVN switch mapping
        container_config = [
            # VPC-A containers
            {"name": "vpc-a-web", "switch": "ls-vpc-a-web", "ip": "10.0.1.10"},
            {"name": "vpc-a-app", "switch": "ls-vpc-a-app", "ip": "10.0.2.10"},
            {"name": "vpc-a-db", "switch": "ls-vpc-a-db", "ip": "10.0.3.10"},
            {"name": "traffic-gen-a", "switch": "ls-vpc-a-test", "ip": "10.0.4.10"},
            # VPC-B containers
            {"name": "vpc-b-web", "switch": "ls-vpc-b-web", "ip": "10.1.1.10"},
            {"name": "vpc-b-app", "switch": "ls-vpc-b-app", "ip": "10.1.2.10"},
            {"name": "vpc-b-db", "switch": "ls-vpc-b-db", "ip": "10.1.3.10"},
            {"name": "traffic-gen-b", "switch": "ls-vpc-b-test", "ip": "10.1.4.10"},
        ]

        successful = 0
        failed = 0
        for config in container_config:
            # Check if container exists
            result = subprocess.run(["docker", "ps", "-q", "-f", f"name={config['name']}"], capture_output=True, text=True)
            if result.stdout.strip():
                # Generate a MAC address for the container
                mac_address = self.generate_mac_address()
                success = self.bind_container_to_ovn(config["name"], config["switch"], config["ip"], mac_address)
                if success:
                    successful += 1
                else:
                    failed += 1
                    logger.error(f"FAILED to bind container {config['name']} to OVN")
            else:
                logger.warning(f"Container {config['name']} not found")
                failed += 1

        if failed > 0:
            logger.error(f"Container networking setup FAILED: {successful} successful, {failed} failed")
        else:
            logger.info(f"Container networking setup complete: {successful} containers bound successfully")


# DockerNetworkManager removed - was trying to use non-existent "openvswitch" driver
# Containers should be attached directly to OVS bridges instead


class TestRunner:
    """Runs connectivity and performance tests"""

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

        # Define container IPs (as assigned by connect-vpc-containers.sh)
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

        self.exporter_url = f"https://github.com/Liquescent-Development/ovs_exporter/releases/download/v2.2.0/ovs-exporter-2.2.0.linux-{self.arch}.tar.gz"
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
                "wget", "-q", "-O", f"/tmp/ovs-exporter-2.2.0.linux-{self.arch}.tar.gz",
                self.exporter_url
            ], check=True)

            # Extract the package
            logger.info("Extracting OVS exporter package...")
            subprocess.run([
                "tar", "xzf", f"/tmp/ovs-exporter-2.2.0.linux-{self.arch}.tar.gz", "-C", "/tmp"
            ], check=True)

            # Copy the binary to /usr/local/bin
            logger.info("Installing OVS exporter binary...")
            subprocess.run([
                "cp", f"/tmp/ovs-exporter-2.2.0.linux-{self.arch}/ovs-exporter",
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
            subprocess.run(["bash", "-c", f"rm -rf /tmp/ovs-exporter-2.2.0.linux-{self.arch}*"], check=False)

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
    """Implements chaos testing scenarios"""

    def __init__(self):
        self.scenarios = {
            "packet-loss": self._packet_loss,
            "latency": self._add_latency,
            "bandwidth": self._limit_bandwidth,
            "partition": self._network_partition,
        }

    def run_scenario(self, scenario: str, duration: int = 60, target: str = "ovs-vpc-a"):
        """Run a chaos scenario"""
        if scenario not in self.scenarios:
            logger.error(f"Unknown scenario: {scenario}")
            return False

        logger.info(f"Running chaos scenario: {scenario} for {duration}s on {target}")
        self.scenarios[scenario](target, duration)
        return True

    def _packet_loss(self, target: str, duration: int):
        """Introduce packet loss"""
        logger.info(f"Introducing 30% packet loss on {target}")
        cmd = [
            "docker", "exec", target,
            "tc", "qdisc", "add", "dev", "eth0", "root", "netem", "loss", "30%"
        ]
        subprocess.run(cmd, check=True)

        time.sleep(duration)

        # Remove packet loss
        cmd[5] = "del"
        subprocess.run(cmd[2:6] + cmd[7:8], check=True)
        logger.info("Packet loss removed")

    def _add_latency(self, target: str, duration: int):
        """Add network latency"""
        logger.info(f"Adding 100ms latency on {target}")
        cmd = [
            "docker", "exec", target,
            "tc", "qdisc", "add", "dev", "eth0", "root", "netem", "delay", "100ms"
        ]
        subprocess.run(cmd, check=True)

        time.sleep(duration)

        # Remove latency
        cmd[5] = "del"
        subprocess.run(cmd[2:6] + cmd[7:8], check=True)
        logger.info("Latency removed")

    def _limit_bandwidth(self, target: str, duration: int):
        """Limit network bandwidth"""
        logger.info(f"Limiting bandwidth to 1mbit on {target}")
        # Implementation would use tc tbf qdisc
        pass

    def _network_partition(self, target: str, duration: int):
        """Create network partition"""
        logger.info(f"Creating network partition on {target}")
        # Implementation would use iptables rules
        pass


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="OVS Container Lab Orchestrator")

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Setup OVN topology")

    # Setup-chassis command
    chassis_parser = subparsers.add_parser("setup-chassis", help="Configure OVS as OVN chassis")

    # Bind-containers command
    bind_parser = subparsers.add_parser("bind-containers", help="Bind containers to OVN")

    # Setup-monitoring command
    monitoring_parser = subparsers.add_parser("setup-monitoring", help="Setup monitoring exporters on host")

    # Test command
    test_parser = subparsers.add_parser("test", help="Run connectivity tests")

    # Test-driver command
    test_driver_parser = subparsers.add_parser("test-driver", help="Test Docker network driver")

    # Chaos command
    chaos_parser = subparsers.add_parser("chaos", help="Run chaos scenarios")
    chaos_parser.add_argument("scenario", choices=["packet-loss", "latency", "bandwidth", "partition"])
    chaos_parser.add_argument("--duration", type=int, default=60, help="Duration in seconds")
    chaos_parser.add_argument("--target", default="ovs-vpc-a", help="Target container")

    # Traffic-test command
    traffic_test_parser = subparsers.add_parser("traffic-test", help="Test traffic generation prerequisites")

    # Show command
    show_parser = subparsers.add_parser("show", help="Show OVN topology")

    # Network command
    net_parser = subparsers.add_parser("network", help="Manage Docker networks")
    net_subparsers = net_parser.add_subparsers(dest="action")

    create_parser = net_subparsers.add_parser("create", help="Create network")
    create_parser.add_argument("name", help="Network name")
    create_parser.add_argument("--subnet", required=True, help="Subnet CIDR")
    create_parser.add_argument("--gateway", required=True, help="Gateway IP")
    create_parser.add_argument("--vpc", help="VPC label")

    delete_parser = net_subparsers.add_parser("delete", help="Delete network")
    delete_parser.add_argument("name", help="Network name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    # Execute commands
    if args.command == "setup":
        ovn = OVNManager()
        ovn.setup_topology()

    elif args.command == "setup-chassis":
        ovn = OVNManager()
        success = ovn.setup_ovs_chassis()
        return 0 if success else 1

    elif args.command == "bind-containers":
        ovn = OVNManager()
        ovn.setup_container_networking()

    elif args.command == "setup-monitoring":
        monitor = MonitoringManager()
        success = monitor.setup_ovs_exporter() and monitor.setup_node_exporter()
        return 0 if success else 1

    elif args.command == "test":
        tester = TestRunner()
        success = tester.test_connectivity()
        return 0 if success else 1

    elif args.command == "test-driver":
        # DockerNetworkManager was removed - not using Docker network driver anymore
        logger.error("Docker network driver test not available - using OVN directly")
        return 1

    elif args.command == "chaos":
        chaos = ChaosEngineer()
        chaos.run_scenario(args.scenario, args.duration, args.target)

    elif args.command == "traffic-test":
        tester = TestRunner()
        success = tester.test_traffic_prerequisites()
        return 0 if success else 1

    elif args.command == "show":
        ovn = OVNManager()
        ovn.show_topology()

    elif args.command == "network":
        net_mgr = DockerNetworkManager()
        if args.action == "create":
            net_mgr.create_network(args.name, args.subnet, args.gateway, args.vpc)
        elif args.action == "delete":
            net_mgr.delete_network(args.name)

    return 0


if __name__ == "__main__":
    sys.exit(main())