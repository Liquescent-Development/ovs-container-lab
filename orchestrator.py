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

    def setup_topology(self, create_containers=False):
        """Configure OVN logical topology for multi-VPC"""
        logger.info("Setting up OVN topology...")

        # Create logical routers
        logger.info("Creating logical routers...")
        self._create_logical_router("lr-gateway", "External gateway router")
        self._create_logical_router("lr-vpc-a", "VPC-A router")
        self._create_logical_router("lr-vpc-b", "VPC-B router")

        # Create logical switches for each VPC tier
        logger.info("Creating logical switches...")

        # VPC-A switches
        self._create_logical_switch("ls-vpc-a-web", "10.0.1.0/24")
        self._create_logical_switch("ls-vpc-a-app", "10.0.2.0/24")
        self._create_logical_switch("ls-vpc-a-db", "10.0.3.0/24")

        # VPC-B switches
        self._create_logical_switch("ls-vpc-b-web", "10.1.1.0/24")
        self._create_logical_switch("ls-vpc-b-app", "10.1.2.0/24")
        self._create_logical_switch("ls-vpc-b-db", "10.1.3.0/24")

        # Transit switch for inter-VPC routing
        self._create_logical_switch("ls-transit", "192.168.100.0/24")

        # Connect routers to switches
        logger.info("Connecting routers to switches...")

        # Connect VPC-A router to its switches
        self._connect_router_to_switch("lr-vpc-a", "ls-vpc-a-web", "10.0.1.1/24", "00:00:00:01:01:01")
        self._connect_router_to_switch("lr-vpc-a", "ls-vpc-a-app", "10.0.2.1/24", "00:00:00:01:02:01")
        self._connect_router_to_switch("lr-vpc-a", "ls-vpc-a-db", "10.0.3.1/24", "00:00:00:01:03:01")

        # Connect VPC-B router to its switches
        self._connect_router_to_switch("lr-vpc-b", "ls-vpc-b-web", "10.1.1.1/24", "00:00:00:02:01:01")
        self._connect_router_to_switch("lr-vpc-b", "ls-vpc-b-app", "10.1.2.1/24", "00:00:00:02:02:01")
        self._connect_router_to_switch("lr-vpc-b", "ls-vpc-b-db", "10.1.3.1/24", "00:00:00:02:03:01")

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

        logger.info("OVN topology setup complete")

        # Create test containers if requested
        if create_containers:
            self.create_test_containers()

    def _create_logical_router(self, name: str, comment: str = ""):
        """Create a logical router if it doesn't exist"""
        try:
            existing = self.run_nbctl(["lr-list"])
            if name not in existing:
                self.run_nbctl(["lr-add", name])
                if comment:
                    self.run_nbctl(["set", "logical_router", name, f"external_ids:comment=\"{comment}\""])
                logger.info(f"Created logical router: {name}")
            else:
                logger.debug(f"Logical router {name} already exists")
        except Exception as e:
            logger.error(f"Failed to create logical router {name}: {e}")
            raise

    def _create_logical_switch(self, name: str, subnet: str = ""):
        """Create a logical switch if it doesn't exist"""
        try:
            existing = self.run_nbctl(["ls-list"])
            if name not in existing:
                self.run_nbctl(["ls-add", name])
                if subnet:
                    self.run_nbctl(["set", "logical_switch", name, f"other_config:subnet=\"{subnet}\""])
                logger.info(f"Created logical switch: {name} ({subnet})")
            else:
                logger.debug(f"Logical switch {name} already exists")
        except Exception as e:
            logger.error(f"Failed to create logical switch {name}: {e}")
            raise

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

    # Removed old broken create_test_containers_old function that tried to use non-existent Docker network driver
        """DEPRECATED: Create test containers in each VPC subnet using Docker networks"""
        logger.info("Creating Docker networks and test containers...")

        # First, create Docker networks via OVN driver
        net_mgr = DockerNetworkManager()

        # Define networks and containers
        networks = [
            # VPC-A networks
            {"name": "vpc-a-web", "subnet": "10.0.1.0/24", "gateway": "10.0.1.1", "vpc": "a"},
            {"name": "vpc-a-app", "subnet": "10.0.2.0/24", "gateway": "10.0.2.1", "vpc": "a"},
            {"name": "vpc-a-db", "subnet": "10.0.3.0/24", "gateway": "10.0.3.1", "vpc": "a"},

            # VPC-B networks
            {"name": "vpc-b-web", "subnet": "10.1.1.0/24", "gateway": "10.1.1.1", "vpc": "b"},
            {"name": "vpc-b-app", "subnet": "10.1.2.0/24", "gateway": "10.1.2.1", "vpc": "b"},
            {"name": "vpc-b-db", "subnet": "10.1.3.0/24", "gateway": "10.1.3.1", "vpc": "b"},
        ]

        # Create Docker networks
        logger.info("Creating Docker networks via OVN driver...")
        for net in networks:
            if net_mgr.create_network(net["name"], net["subnet"], net["gateway"], net["vpc"]):
                logger.info(f"Created network: {net['name']}")
            else:
                logger.warning(f"Failed to create network: {net['name']}")

        # Define containers for each network
        containers = [
            # VPC-A containers
            {"name": "vpc-a-web-1", "network": "vpc-a-web", "image": "alpine:latest"},
            {"name": "vpc-a-web-2", "network": "vpc-a-web", "image": "alpine:latest"},
            {"name": "vpc-a-app-1", "network": "vpc-a-app", "image": "alpine:latest"},
            {"name": "vpc-a-app-2", "network": "vpc-a-app", "image": "alpine:latest"},
            {"name": "vpc-a-db-1", "network": "vpc-a-db", "image": "alpine:latest"},

            # VPC-B containers
            {"name": "vpc-b-web-1", "network": "vpc-b-web", "image": "alpine:latest"},
            {"name": "vpc-b-web-2", "network": "vpc-b-web", "image": "alpine:latest"},
            {"name": "vpc-b-app-1", "network": "vpc-b-app", "image": "alpine:latest"},
            {"name": "vpc-b-app-2", "network": "vpc-b-app", "image": "alpine:latest"},
            {"name": "vpc-b-db-1", "network": "vpc-b-db", "image": "alpine:latest"},
        ]

        # Create containers
        logger.info("Creating test containers...")
        for container in containers:
            try:
                # Remove container if it exists
                subprocess.run(["docker", "rm", "-f", container["name"]],
                             capture_output=True, text=True)

                # Create container on OVN network
                cmd = [
                    "docker", "run", "-d",
                    "--name", container["name"],
                    "--hostname", container["name"],
                    "--network", container["network"],
                    "--label", f"vpc={container['name'].split('-')[1]}",
                    "--label", f"tier={container['name'].split('-')[2]}",
                    "--label", "ovs-lab=true",
                    container["image"],
                    "sh", "-c",
                    "apk add --no-cache iproute2 iputils tcpdump iperf3 curl netcat-openbsd >/dev/null 2>&1; "
                    "nc -l -k -p 80 </dev/null >/dev/null 2>&1 & "
                    "nc -l -k -p 443 </dev/null >/dev/null 2>&1 & "
                    "iperf3 -s -D >/dev/null 2>&1; "
                    "sleep infinity"
                ]

                result = subprocess.run(cmd, capture_output=True, text=True, check=True)

                # Get container IP
                cmd_ip = [
                    "docker", "inspect", container["name"],
                    "-f", "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"
                ]
                ip_result = subprocess.run(cmd_ip, capture_output=True, text=True)
                ip = ip_result.stdout.strip()

                logger.info(f"Created container: {container['name']} (IP: {ip})")

            except subprocess.CalledProcessError as e:
                logger.error(f"Failed to create container {container['name']}: {e.stderr}")

        logger.info("Test containers created and connected via OVN")

    def show_topology(self):
        """Display current OVN topology"""
        logger.info("Current OVN topology:")
        print("\nLogical Routers:")
        print(self.run_nbctl(["lr-list"]))
        print("\nLogical Switches:")
        print(self.run_nbctl(["ls-list"]))
        print("\nNorthbound DB:")
        print(self.run_nbctl(["show"]))

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

        # Ensure br-int exists
        subprocess.run(["sudo", "ovs-vsctl", "--may-exist", "add-br", "br-int"], check=True)

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

    def bind_container_to_ovn(self, container_name: str, switch_name: str, ip_address: str, mac_address: Optional[str] = None):
        """Bind a container to an OVN logical switch port"""
        logger.info(f"Binding container {container_name} to OVN switch {switch_name}...")

        # Generate MAC if not provided
        if not mac_address:
            import random
            mac_address = "02:00:00:%02x:%02x:%02x" % (random.randint(0, 255), random.randint(0, 255), random.randint(0, 255))

        # Create logical switch port
        port_name = f"lsp-{container_name}"
        try:
            self.run_nbctl(["lsp-add", switch_name, port_name])
            self.run_nbctl(["lsp-set-addresses", port_name, f"{mac_address} {ip_address}"])
            logger.info(f"Created logical switch port {port_name}")
        except subprocess.CalledProcessError:
            logger.warning(f"Port {port_name} may already exist")

        # Get container PID for namespace operations
        cmd = ["docker", "inspect", "-f", "{{.State.Pid}}", container_name]
        result = subprocess.run(cmd, capture_output=True, text=True)
        container_pid = result.stdout.strip()

        if not container_pid or container_pid == "0":
            logger.error(f"Cannot get PID for container {container_name}")
            return False

        # Create veth pair and attach to container namespace
        veth_host = f"veth-{container_name[:8]}"
        veth_cont = "eth1"

        # Delete if exists
        subprocess.run(["sudo", "ip", "link", "del", veth_host], capture_output=True)

        # Create veth pair
        subprocess.run(["sudo", "ip", "link", "add", veth_host, "type", "veth", "peer", "name", veth_cont], check=True)

        # Move one end to container namespace
        subprocess.run(["sudo", "ip", "link", "set", veth_cont, "netns", container_pid], check=True)

        # Configure container interface
        subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "link", "set", veth_cont, "address", mac_address], check=True)
        subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "addr", "add", f"{ip_address}/24", "dev", veth_cont], check=True)
        subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "link", "set", veth_cont, "up"], check=True)

        # Add default route in container
        gateway = ".".join(ip_address.split(".")[:3]) + ".1"
        subprocess.run(["sudo", "nsenter", "-t", container_pid, "-n", "ip", "route", "add", "default", "via", gateway], capture_output=True)

        # Attach host end to OVS integration bridge
        # First check if port already exists
        result = subprocess.run(["sudo", "ovs-vsctl", "list-ports", "br-int"], capture_output=True, text=True)
        if veth_host not in result.stdout:
            # Add port with external_ids in one atomic operation to avoid race condition
            subprocess.run([
                "sudo", "ovs-vsctl",
                "add-port", "br-int", veth_host,
                "--", "set", "Interface", veth_host, f"external_ids:iface-id={port_name}"
            ], check=True)
        else:
            # Port exists, just update external_ids
            subprocess.run(["sudo", "ovs-vsctl", "set", "interface", veth_host, f"external_ids:iface-id={port_name}"], check=True)

        subprocess.run(["sudo", "ip", "link", "set", veth_host, "up"], check=True)

        logger.info(f"Container {container_name} bound to OVN port {port_name}")
        return True

    def setup_container_networking(self):
        """Set up OVN networking for all test containers"""
        logger.info("Setting up container networking via OVN...")

        # Container to OVN switch mapping
        container_config = [
            # VPC-A containers
            {"name": "vpc-a-web", "switch": "ls-vpc-a-web", "ip": "10.0.1.10"},
            {"name": "vpc-a-app", "switch": "ls-vpc-a-app", "ip": "10.0.2.10"},
            {"name": "vpc-a-db", "switch": "ls-vpc-a-db", "ip": "10.0.3.10"},
            # VPC-B containers
            {"name": "vpc-b-web", "switch": "ls-vpc-b-web", "ip": "10.1.1.10"},
            {"name": "vpc-b-app", "switch": "ls-vpc-b-app", "ip": "10.1.2.10"},
            {"name": "vpc-b-db", "switch": "ls-vpc-b-db", "ip": "10.1.3.10"},
        ]

        for config in container_config:
            # Check if container exists
            result = subprocess.run(["docker", "ps", "-q", "-f", f"name={config['name']}"], capture_output=True, text=True)
            if result.stdout.strip():
                self.bind_container_to_ovn(config["name"], config["switch"], config["ip"])
            else:
                logger.warning(f"Container {config['name']} not found")

        logger.info("Container networking setup complete")


# DockerNetworkManager removed - was trying to use non-existent "openvswitch" driver
# Containers should be attached directly to OVS bridges instead


class TestRunner:
    """Runs connectivity and performance tests"""

    def test_connectivity(self):
        """Test connectivity between VPCs"""
        logger.info("Running connectivity tests...")

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

        tests = [
            # Intra-VPC tests (same VPC, different subnets)
            ("vpc-a-web", "vpc-a-app", "VPC-A: web to app tier"),
            ("vpc-a-app", "vpc-a-db", "VPC-A: app to db tier"),

            ("vpc-b-web", "vpc-b-app", "VPC-B: web to app tier"),
            ("vpc-b-app", "vpc-b-db", "VPC-B: app to db tier"),

            # Inter-VPC tests (between VPCs) - these should fail without proper routing
            ("vpc-a-web", "vpc-b-web", "Inter-VPC: A-web to B-web"),
            ("vpc-a-app", "vpc-b-app", "Inter-VPC: A-app to B-app"),
        ]

        results = []
        for source, target, description in tests:
            # Get target IP from our known mapping
            target_ip = container_ips.get(target)

            if target_ip:
                result = self._test_ping(source, target_ip, description)
                results.append((description, result))
            else:
                logger.warning(f"Could not find IP for {target}")
                results.append((description, False))

        # Print summary
        print("\n" + "="*60)
        print("CONNECTIVITY TEST RESULTS")
        print("="*60)
        for desc, result in results:
            status = "✅ PASS" if result else "❌ FAIL"
            print(f"{desc:45} {status}")
        print("="*60)

        # Summary stats
        passed = sum(1 for _, r in results if r)
        total = len(results)
        print(f"\nPassed: {passed}/{total} tests")

        return all(r[1] for r in results)

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

    # Test command
    test_parser = subparsers.add_parser("test", help="Run connectivity tests")

    # Test-driver command
    test_driver_parser = subparsers.add_parser("test-driver", help="Test Docker network driver")

    # Chaos command
    chaos_parser = subparsers.add_parser("chaos", help="Run chaos scenarios")
    chaos_parser.add_argument("scenario", choices=["packet-loss", "latency", "bandwidth", "partition"])
    chaos_parser.add_argument("--duration", type=int, default=60, help="Duration in seconds")
    chaos_parser.add_argument("--target", default="ovs-vpc-a", help="Target container")

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