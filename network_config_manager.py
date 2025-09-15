#!/usr/bin/env python3
"""
Network Configuration Manager for OVS Container Lab
Handles parsing, validation, and management of network configurations
"""

import yaml
import json
import os
import logging
import ipaddress
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class HostConfig:
    """Configuration for a single host"""
    name: str
    chassis_name: str
    management_ip: str
    tunnel_ip: str
    location: str
    zone: str
    type: str
    roles: List[str]


@dataclass
class ContainerConfig:
    """Configuration for a container/VM"""
    name: str
    host: str
    vpc: str
    switch: str
    ip: str
    mac: str
    tier: str
    type: Optional[str] = None
    scheduling: Optional[Dict] = None


@dataclass
class OVNClusterConfig:
    """OVN cluster configuration"""
    nb_nodes: List[Dict]
    sb_nodes: List[Dict]
    nb_connection: str
    sb_connection: str
    nb_port: int = 6641
    sb_port: int = 6642
    nb_raft_port: int = 6643
    sb_raft_port: int = 6644


@dataclass
class VPCConfig:
    """VPC configuration"""
    name: str
    tenant: str
    cidr: str
    router: Dict
    switches: List[Dict]
    spanning_hosts: Any  # Can be list or 'all'


class NetworkConfigManager:
    """Manages network configuration for the OVS container lab"""

    def __init__(self, config_path: str = "network-config.yaml"):
        self.config_path = Path(config_path)
        self.config = {}
        self.hosts = {}
        self.containers = {}
        self.vpcs = {}
        self.ovn_cluster = None
        self._state_file = Path(".network-state.json")  # Runtime state

    def load_config(self) -> bool:
        """Load configuration from YAML file"""
        try:
            if not self.config_path.exists():
                logger.error(f"Config file not found: {self.config_path}")
                return False

            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f)

            self._parse_config()
            logger.info(f"Loaded config with {len(self.hosts)} hosts, {len(self.containers)} containers")
            return True

        except Exception as e:
            logger.error(f"Failed to load config: {e}")
            return False

    def _parse_config(self):
        """Parse configuration into structured objects"""
        # Parse hosts
        for host_name, host_data in self.config.get('hosts', {}).items():
            self.hosts[host_name] = HostConfig(
                name=host_name,
                chassis_name=host_data['chassis_name'],
                management_ip=host_data['management_ip'],
                tunnel_ip=host_data['tunnel_ip'],
                location=host_data['location'],
                zone=host_data['zone'],
                type=host_data['type'],
                roles=host_data.get('roles', [])
            )

        # Parse OVN cluster
        if 'ovn_cluster' in self.config:
            cluster = self.config['ovn_cluster']
            self.ovn_cluster = OVNClusterConfig(
                nb_nodes=cluster['northbound']['nodes'],
                sb_nodes=cluster['southbound']['nodes'],
                nb_connection=cluster['nb_connection'],
                sb_connection=cluster['sb_connection'],
                nb_port=cluster['northbound'].get('port', 6641),
                sb_port=cluster['southbound'].get('port', 6642),
                nb_raft_port=cluster['northbound'].get('raft_port', 6643),
                sb_raft_port=cluster['southbound'].get('raft_port', 6644)
            )

        # Parse VPCs
        for vpc_name, vpc_data in self.config.get('vpcs', {}).items():
            self.vpcs[vpc_name] = VPCConfig(
                name=vpc_name,
                tenant=vpc_data['tenant'],
                cidr=vpc_data['cidr'],
                router=vpc_data['router'],
                switches=vpc_data['switches'],
                spanning_hosts=vpc_data.get('spanning_hosts', [])
            )

        # Parse containers
        for container_name, container_data in self.config.get('containers', {}).items():
            self.containers[container_name] = ContainerConfig(
                name=container_name,
                host=container_data['host'],
                vpc=container_data['vpc'],
                switch=container_data['switch'],
                ip=container_data['ip'],
                mac=container_data['mac'],
                tier=container_data.get('tier', 'default'),
                type=container_data.get('type'),
                scheduling=container_data.get('scheduling')
            )

    def get_current_host(self) -> Optional[str]:
        """Determine which host we're currently running on"""
        # Try to detect from hostname, IP, or environment variable
        import socket
        hostname = socket.gethostname()

        # Check environment variable first
        if 'OVN_HOST' in os.environ:
            return os.environ['OVN_HOST']

        # Try to match by hostname
        for host_name, host in self.hosts.items():
            if host_name in hostname or hostname in host_name:
                return host_name

        # Try to match by IP
        try:
            local_ips = socket.gethostbyname_ex(hostname)[2]
            for host_name, host in self.hosts.items():
                if host.management_ip in local_ips or host.tunnel_ip in local_ips:
                    return host_name
        except:
            pass

        # Default to first host or environment setting
        if self.hosts:
            return list(self.hosts.keys())[0]

        return None

    def get_containers_for_host(self, host: str) -> List[ContainerConfig]:
        """Get all containers that should run on a specific host"""
        return [c for c in self.containers.values() if c.host == host]

    def get_container_config(self, container_name: str) -> Optional[ContainerConfig]:
        """Get configuration for a specific container"""
        return self.containers.get(container_name)

    def get_vpc_config(self, vpc_name: str) -> Optional[VPCConfig]:
        """Get configuration for a specific VPC"""
        return self.vpcs.get(vpc_name)

    def is_ovn_central_host(self, host: str) -> bool:
        """Check if a host should run OVN central components"""
        host_config = self.hosts.get(host)
        return host_config and 'ovn-central' in host_config.roles

    def get_ovn_cluster_nodes(self) -> Dict[str, List[str]]:
        """Get OVN cluster node addresses"""
        if not self.ovn_cluster:
            return {'northbound': [], 'southbound': []}

        nb_nodes = [f"{node['address']}:{self.ovn_cluster.nb_port}"
                    for node in self.ovn_cluster.nb_nodes]
        sb_nodes = [f"{node['address']}:{self.ovn_cluster.sb_port}"
                    for node in self.ovn_cluster.sb_nodes]

        return {
            'northbound': nb_nodes,
            'southbound': sb_nodes
        }

    def save_runtime_state(self, state: Dict):
        """Save runtime state (e.g., actual MAC addresses assigned)"""
        try:
            with open(self._state_file, 'w') as f:
                json.dump(state, f, indent=2)
            logger.info(f"Saved runtime state to {self._state_file}")
        except Exception as e:
            logger.error(f"Failed to save runtime state: {e}")

    def load_runtime_state(self) -> Dict:
        """Load runtime state"""
        if not self._state_file.exists():
            return {}

        try:
            with open(self._state_file, 'r') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Failed to load runtime state: {e}")
            return {}

    def update_container_mac(self, container_name: str, mac: str):
        """Update container MAC in runtime state"""
        state = self.load_runtime_state()
        if 'container_macs' not in state:
            state['container_macs'] = {}
        state['container_macs'][container_name] = mac
        self.save_runtime_state(state)

    def get_container_mac(self, container_name: str) -> Optional[str]:
        """Get container MAC from config or runtime state"""
        # First check config
        container = self.containers.get(container_name)
        if container and container.mac:
            return container.mac

        # Then check runtime state
        state = self.load_runtime_state()
        return state.get('container_macs', {}).get(container_name)

    def validate_config(self) -> List[str]:
        """Validate the configuration and return list of errors"""
        errors = []

        # Check for duplicate IPs
        ips_seen = {}
        for container in self.containers.values():
            if container.ip in ips_seen:
                errors.append(f"Duplicate IP {container.ip}: {container.name} and {ips_seen[container.ip]}")
            ips_seen[container.ip] = container.name

        # Check for duplicate MACs
        macs_seen = {}
        for container in self.containers.values():
            if container.mac in macs_seen:
                errors.append(f"Duplicate MAC {container.mac}: {container.name} and {macs_seen[container.mac]}")
            macs_seen[container.mac] = container.name

        # Check host references
        for container in self.containers.values():
            if container.host not in self.hosts:
                errors.append(f"Container {container.name} references unknown host {container.host}")

        # Check VPC references
        for container in self.containers.values():
            if container.vpc not in self.vpcs and container.vpc != 'transit':
                errors.append(f"Container {container.name} references unknown VPC {container.vpc}")

        # Check CIDR overlaps
        cidrs = []
        for vpc in self.vpcs.values():
            try:
                vpc_net = ipaddress.ip_network(vpc.cidr)
                for other_net, other_vpc in cidrs:
                    if vpc_net.overlaps(other_net):
                        errors.append(f"CIDR overlap: {vpc.name} ({vpc.cidr}) and {other_vpc}")
                cidrs.append((vpc_net, vpc.name))
            except ValueError as e:
                errors.append(f"Invalid CIDR for {vpc.name}: {vpc.cidr}")

        return errors

    def generate_ansible_inventory(self) -> Dict:
        """Generate Ansible inventory from config"""
        inventory = {
            'all': {
                'children': {
                    'ovn_central': {'hosts': {}},
                    'ovn_controllers': {'hosts': {}},
                    'gateway_nodes': {'hosts': {}}
                }
            }
        }

        for host_name, host in self.hosts.items():
            host_vars = {
                'ansible_host': host.management_ip,
                'tunnel_ip': host.tunnel_ip,
                'chassis_name': host.chassis_name
            }

            if 'ovn-central' in host.roles:
                inventory['all']['children']['ovn_central']['hosts'][host_name] = host_vars

            if 'ovn-controller' in host.roles:
                inventory['all']['children']['ovn_controllers']['hosts'][host_name] = host_vars

            if 'gateway' in host.roles:
                inventory['all']['children']['gateway_nodes']['hosts'][host_name] = host_vars

        return inventory


# CLI interface for testing
if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)

    if len(sys.argv) < 2:
        print("Usage: python network_config_manager.py <command> [args]")
        print("Commands: validate, show-hosts, show-containers, show-vpcs, ansible-inventory")
        sys.exit(1)

    manager = NetworkConfigManager()
    if not manager.load_config():
        sys.exit(1)

    command = sys.argv[1]

    if command == "validate":
        errors = manager.validate_config()
        if errors:
            print("Configuration errors found:")
            for error in errors:
                print(f"  - {error}")
            sys.exit(1)
        else:
            print("Configuration is valid")

    elif command == "show-hosts":
        for host_name, host in manager.hosts.items():
            print(f"{host_name}:")
            print(f"  Chassis: {host.chassis_name}")
            print(f"  Management IP: {host.management_ip}")
            print(f"  Roles: {', '.join(host.roles)}")
            containers = manager.get_containers_for_host(host_name)
            if containers:
                print(f"  Containers: {', '.join([c.name for c in containers])}")

    elif command == "show-containers":
        current_host = manager.get_current_host()
        print(f"Current host: {current_host}")
        for container in manager.get_containers_for_host(current_host):
            print(f"{container.name}:")
            print(f"  Host: {container.host}")
            print(f"  VPC: {container.vpc}")
            print(f"  IP: {container.ip}")
            print(f"  MAC: {container.mac}")

    elif command == "show-vpcs":
        for vpc_name, vpc in manager.vpcs.items():
            print(f"{vpc_name}:")
            print(f"  Tenant: {vpc.tenant}")
            print(f"  CIDR: {vpc.cidr}")
            print(f"  Switches: {len(vpc.switches)}")

    elif command == "ansible-inventory":
        inventory = manager.generate_ansible_inventory()
        print(yaml.dump(inventory, default_flow_style=False))

    else:
        print(f"Unknown command: {command}")
        sys.exit(1)