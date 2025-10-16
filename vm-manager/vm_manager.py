#!/usr/bin/env python3
"""
VM Manager for OVS Container Lab
Manages libvirt VMs connected to OVS/OVN networking
"""

import os
import sys
import json
import yaml
import time
import subprocess
import uuid
import logging
import tempfile
from pathlib import Path
from typing import Dict, List, Optional

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class VMManager:
    """Manages KVM/QEMU VMs in the OVS Container Lab environment"""

    def __init__(self):
        self.base_path = Path(__file__).parent
        self.image_path = self.base_path / "images"
        self.cloud_init_path = self.base_path / "cloud-init"

        # VM configurations - put VMs on existing container subnets
        # VMs use static IPs on the same subnet as containers
        self.vms = {
            'vpc-a-vm': {
                'vpc': 'a',
                'ip': '10.0.1.20',  # Static IP on web subnet
                'gateway': '10.0.1.1',
                'netmask': '255.255.255.0',
                'vlan': 101,  # Same VLAN as vpc-a-web containers
                'mac': self._generate_mac(),
                'memory': 512,  # MB
                'cpus': 1,
                'disk_size': '5G',  # Increased to accommodate cloud image
                'ovn_switch': 'ls-vpc-a-web',  # Share switch with web containers
                'ovn_router': 'lr-vpc-a'
            },
            'vpc-b-vm': {
                'vpc': 'b',
                'ip': '10.1.1.20',  # Static IP on web subnet
                'gateway': '10.1.1.1',
                'netmask': '255.255.255.0',
                'vlan': 201,  # Same VLAN as vpc-b-web containers
                'mac': self._generate_mac(),
                'memory': 512,  # MB
                'cpus': 1,
                'disk_size': '5G',  # Increased to accommodate cloud image
                'ovn_switch': 'ls-vpc-b-web',  # Share switch with web containers
                'ovn_router': 'lr-vpc-b'
            }
        }

    def _generate_mac(self) -> str:
        """Generate a random MAC address"""
        mac_parts = [0x52, 0x54, 0x00]  # KVM OUI prefix
        mac_parts.extend([os.urandom(1)[0] for _ in range(3)])
        return ':'.join(f'{b:02x}' for b in mac_parts)

    def configure_tap_for_ovn(self, vm_name: str) -> bool:
        """Configure TAP interface with OVN binding information"""
        logger.info(f"Configuring TAP interface for OVN binding for {vm_name}...")

        try:
            # Get the TAP interface name from virsh
            result = self._run_command(['sudo', 'virsh', 'dumpxml', vm_name], check=False)
            if not result or result.returncode != 0:
                logger.error(f"Could not get XML for {vm_name}")
                return False

            # Look for tap or vnet interface
            import re
            matches = re.findall(r"target dev='(tap[^']+)'", result.stdout)
            if not matches:
                matches = re.findall(r"target dev='(vnet[^']+)'", result.stdout)

            if not matches:
                logger.error(f"Could not find TAP interface for {vm_name}")
                return False

            tap_interface = matches[0]
            logger.info(f"Found TAP interface: {tap_interface}")

            # Set the external_ids:iface-id to match the OVN logical port
            # This is CRITICAL for OVN to bind the port
            lsp_name = f"lsp-{vm_name}"

            logger.info(f"Setting OVN binding: {tap_interface} -> {lsp_name}")
            self._run_command([
                'sudo', 'ovs-vsctl', 'set', 'Interface', tap_interface,
                f'external_ids:iface-id={lsp_name}'
            ])

            # Also set the MAC address in external_ids (optional but helpful)
            if vm_name in self.vms:
                mac = self.vms[vm_name]['mac']
                self._run_command([
                    'sudo', 'ovs-vsctl', 'set', 'Interface', tap_interface,
                    f'external_ids:attached-mac={mac}'
                ], check=False)

            # Verify the setting
            verify = self._run_command([
                'sudo', 'ovs-vsctl', 'get', 'Interface', tap_interface,
                'external_ids:iface-id'
            ], check=False)

            if verify and lsp_name in verify.stdout:
                logger.info(f"✅ OVN binding configured: {tap_interface} bound to {lsp_name}")
                return True
            else:
                logger.error(f"Failed to verify OVN binding for {tap_interface}")
                return False

        except Exception as e:
            logger.error(f"Failed to configure OVN binding for {vm_name}: {e}")
            return False

    def fix_tap_offloading(self, vm_name: str) -> bool:
        """Fix TAP interface offloading settings for a VM to enable TCP traffic"""
        logger.info(f"Fixing TAP interface offloading for {vm_name}...")

        # Get the TAP interface name from virsh
        try:
            result = self._run_command(['sudo', 'virsh', 'dumpxml', vm_name], check=False)
            if not result or result.returncode != 0:
                logger.warning(f"Could not get XML for {vm_name}")
                return False

            # Look for tap or vnet interface
            import re
            matches = re.findall(r"target dev='(tap[^']+)'", result.stdout)
            if not matches:
                matches = re.findall(r"target dev='(vnet[^']+)'", result.stdout)

            if not matches:
                logger.warning(f"Could not find TAP interface for {vm_name}")
                return False

            tap_interface = matches[0]
            logger.info(f"Found TAP interface: {tap_interface}")

            # Disable offloading features that break TCP with OVS
            offload_features = ['rx', 'tx', 'sg', 'tso', 'gso', 'gro', 'rxvlan', 'txvlan']

            for feature in offload_features:
                cmd = ['sudo', 'ethtool', '-K', tap_interface, feature, 'off']
                self._run_command(cmd, check=False)

            # Also use simplified command for common features
            self._run_command(['sudo', 'ethtool', '--offload', tap_interface, 'rx', 'off', 'tx', 'off'], check=False)

            logger.info(f"Offloading disabled for {tap_interface} - TCP traffic should now work")
            return True

        except Exception as e:
            logger.error(f"Failed to fix offloading for {vm_name}: {e}")
            return False

    def _run_command(self, cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
        """Run a shell command and return the result"""
        logger.debug(f"Running command: {' '.join(cmd)}")
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)

        if check and result.returncode != 0:
            logger.error(f"Command failed: {result.stderr}")
            raise RuntimeError(f"Command failed: {' '.join(cmd)}")

        return result

    def check_dependencies(self) -> bool:
        """Check if all required dependencies are installed"""
        logger.info("Checking dependencies...")

        required_commands = ['virsh', 'virt-install', 'qemu-img', 'ovs-vsctl', 'ovn-nbctl']
        missing = []

        for cmd in required_commands:
            result = self._run_command(['which', cmd], check=False)
            if result.returncode != 0:
                missing.append(cmd)

        if missing:
            logger.error(f"Missing dependencies: {', '.join(missing)}")
            logger.info("Install with: sudo apt-get install -y qemu-kvm libvirt-daemon-system libvirt-clients virtinst")
            return False

        # Check if libvirtd is running
        result = self._run_command(['sudo', 'systemctl', 'is-active', 'libvirtd'], check=False)
        if result.returncode != 0:
            logger.error("libvirtd is not running")
            logger.info("Start with: sudo systemctl start libvirtd")
            return False

        # Check KVM support
        if not os.path.exists('/dev/kvm'):
            logger.warning("KVM device not found. VMs will run without acceleration.")
            logger.info("Note: Nested virtualization may need to be enabled in Lima VM")

        return True

    def download_base_image(self, force: bool = False) -> bool:
        """Download Ubuntu cloud image for VMs"""
        self.image_path.mkdir(parents=True, exist_ok=True)

        # Detect architecture and use appropriate image
        import platform
        arch = platform.machine()
        if arch == 'aarch64':
            # ARM64 image - Ubuntu 24.04 LTS
            cache_name = "ubuntu-24.04-server-cloudimg-arm64.img"
            image_url = "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-arm64.img"
        else:
            # x86_64 image - Ubuntu 24.04 LTS
            cache_name = "ubuntu-24.04-server-cloudimg-amd64.img"
            image_url = "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img"

        image_file = self.image_path / "ubuntu-base.qcow2"

        # Check for cached image first
        cache_path = Path("/home/lima/code/ovs-container-lab/.downloads/vm-images") / cache_name

        if image_file.exists() and not force:
            logger.info(f"Base image already exists: {image_file}")
            return True

        if cache_path.exists():
            logger.info(f"Using cached Ubuntu image from {cache_path}")
            result = self._run_command(['cp', str(cache_path), str(image_file)], check=False)
            if result.returncode == 0:
                logger.info("Cached image copied successfully")
                return True
            else:
                logger.warning("Failed to copy cached image, downloading fresh...")

        logger.info(f"Downloading Ubuntu cloud image...")
        result = self._run_command(['wget', '-O', str(image_file), image_url], check=False)

        if result.returncode != 0:
            logger.error("Failed to download base image")
            return False

        logger.info("Base image downloaded successfully")
        return True

    def create_cloud_init(self, vm_name: str) -> str:
        """Create cloud-init ISO for VM configuration"""
        vm_config = self.vms[vm_name]

        # Create temporary directory for cloud-init files
        with tempfile.TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create meta-data
            metadata = {
                'instance-id': f'{vm_name}-{uuid.uuid4()}',
                'local-hostname': vm_name
            }

            with open(tmppath / 'meta-data', 'w') as f:
                json.dump(metadata, f)

            # Create network-config using netplan v2 format
            # Use static IP configuration
            # Match interface by MAC address, don't force interface name
            network_config = {
                'network': {
                    'version': 2,
                    'ethernets': {
                        'default': {  # Match by MAC, use whatever interface name
                            'match': {
                                'macaddress': vm_config['mac']
                            },
                            'addresses': [f"{vm_config['ip']}/24"],
                            'routes': [
                                {'to': 'default', 'via': vm_config['gateway']}
                            ],
                            'nameservers': {
                                'addresses': ['8.8.8.8', '8.8.4.4']
                            },
                            'dhcp4': False,
                            'dhcp6': False
                        }
                    }
                }
            }

            with open(tmppath / 'network-config', 'w') as f:
                yaml.dump(network_config, f)

            # Create user-data (cloud-config)
            userdata = f"""#cloud-config
hostname: {vm_name}
manage_etc_hosts: true

# Set password for the default ubuntu user
chpasswd:
  users:
    - name: ubuntu
      password: ubuntu
      type: text
  expire: false

# Configure SSH
ssh_pwauth: true

packages:
  - openssh-server
  - python3
  - curl
  - wget
  - tcpdump
  - iperf3
  - nmap
  - net-tools
  - iputils-ping
  - traceroute
  - nano
  - vim

runcmd:
  - echo "VM {vm_name} is ready" > /etc/motd
  - systemctl enable ssh
  - systemctl restart ssh
  - usermod -aG sudo ubuntu
"""

            with open(tmppath / 'user-data', 'w') as f:
                f.write(userdata)

            # Create ISO
            iso_path = self.image_path / f"{vm_name}-cloud-init.iso"
            logger.info(f"Creating cloud-init ISO at: {iso_path}")
            result = self._run_command([
                'genisoimage', '-output', str(iso_path),
                '-volid', 'cidata', '-joliet', '-rock',
                str(tmppath / 'user-data'),
                str(tmppath / 'meta-data'),
                str(tmppath / 'network-config')
            ], check=False)
            if result.returncode != 0:
                logger.error(f"Failed to create cloud-init ISO: {result.stderr}")
                raise RuntimeError(f"Failed to create cloud-init ISO for {vm_name}")
            if not iso_path.exists():
                logger.error(f"Cloud-init ISO was not created at {iso_path}")
                raise RuntimeError(f"Cloud-init ISO not found at {iso_path}")
            logger.info(f"Cloud-init ISO created successfully: {iso_path}")

            return str(iso_path)

    def create_vm_disk(self, vm_name: str) -> str:
        """Create a disk image for the VM"""
        vm_config = self.vms[vm_name]
        base_image = self.image_path / "ubuntu-base.qcow2"
        vm_disk = self.image_path / f"{vm_name}.qcow2"

        # Instead of using backing file, create a full copy and resize it
        # This ensures the VM has a complete, independent disk
        logger.info(f"Creating disk for {vm_name} from base image...")

        # Copy the base image to create an independent disk
        self._run_command([
            'cp', str(base_image), str(vm_disk)
        ])

        # Resize the disk to the requested size
        logger.info(f"Resizing disk to {vm_config['disk_size']}...")
        self._run_command([
            'qemu-img', 'resize', str(vm_disk), vm_config['disk_size']
        ])

        return str(vm_disk)

    def configure_ovs_port(self, vm_name: str) -> bool:
        """Configure the TAP interface (already created by virt-install) in OVS"""
        vm_config = self.vms[vm_name]
        tap_name = f"tap-{vm_name}"

        logger.info(f"Configuring OVS port for {vm_name}")

        # The TAP interface was created by virt-install, just configure it in OVS
        # Add to OVS bridge with VLAN tag
        self._run_command([
            'sudo', 'ovs-vsctl', '--may-exist', 'add-port',
            'br-int', tap_name, '--', 'set', 'port', tap_name,
            f'tag={vm_config["vlan"]}'
        ])

        # Set interface options for OVN
        self._run_command([
            'sudo', 'ovs-vsctl', 'set', 'interface', tap_name,
            'external-ids:iface-id=' + f'{vm_name}-port'
        ])

        logger.info(f"TAP interface {tap_name} added to br-int with VLAN {vm_config['vlan']}")
        return True

    def setup_ovs_port(self, vm_name: str) -> bool:
        """Create TAP interface and add to OVS bridge"""
        vm_config = self.vms[vm_name]
        tap_name = f"tap-{vm_name}"

        logger.info(f"Setting up OVS port for {vm_name}")

        # Create TAP interface
        self._run_command(['sudo', 'ip', 'tuntap', 'add', tap_name, 'mode', 'tap'], check=False)
        self._run_command(['sudo', 'ip', 'link', 'set', tap_name, 'up'])

        # Add to OVS bridge with VLAN tag
        self._run_command([
            'sudo', 'ovs-vsctl', '--may-exist', 'add-port',
            'br-int', tap_name, '--', 'set', 'port', tap_name,
            f'tag={vm_config["vlan"]}'
        ])

        # Set interface options for OVN
        self._run_command([
            'sudo', 'ovs-vsctl', 'set', 'interface', tap_name,
            f'external_ids:iface-id={vm_name}',
            f'external_ids:vm-id={vm_name}',
            f'external_ids:iface-status=active'
        ])

        logger.info(f"TAP interface {tap_name} added to br-int with VLAN {vm_config['vlan']}")
        return True

    def setup_ovn_networking(self, vm_name: str) -> bool:
        """Configure OVN logical networking for VM"""
        vm_config = self.vms[vm_name]

        logger.info(f"Setting up OVN networking for {vm_name}")

        # Create logical switch if it doesn't exist
        result = self._run_command([
            'sudo', 'docker', 'exec', 'ovn-central',
            'ovn-nbctl', '--may-exist', 'ls-add', vm_config['ovn_switch']
        ], check=False)

        if result.returncode != 0:
            logger.warning("Could not create OVN switch (may already exist)")

        # Add logical switch port
        self._run_command([
            'sudo', 'docker', 'exec', 'ovn-central',
            'ovn-nbctl', '--may-exist', 'lsp-add',
            vm_config['ovn_switch'], f'lsp-{vm_name}'
        ])

        # Set port addresses
        self._run_command([
            'sudo', 'docker', 'exec', 'ovn-central',
            'ovn-nbctl', 'lsp-set-addresses',
            f'lsp-{vm_name}', f"{vm_config['mac']} {vm_config['ip']}"
        ])

        # Enable port security
        self._run_command([
            'sudo', 'docker', 'exec', 'ovn-central',
            'ovn-nbctl', 'lsp-set-port-security',
            f'lsp-{vm_name}', f"{vm_config['mac']} {vm_config['ip']}"
        ])

        # Connect logical switch to router
        # Check if router port already exists
        result = self._run_command([
            'sudo', 'docker', 'exec', 'ovn-central',
            'ovn-nbctl', 'lrp-list', vm_config['ovn_router']
        ], check=False)

        router_port = f"rp-{vm_config['ovn_switch']}"
        if router_port not in result.stdout:
            # Add router port
            self._run_command([
                'sudo', 'docker', 'exec', 'ovn-central',
                'ovn-nbctl', 'lrp-add', vm_config['ovn_router'],
                router_port, self._generate_mac(),
                f"{vm_config['gateway']}/24"
            ])

            # Add switch port to connect to router
            self._run_command([
                'sudo', 'docker', 'exec', 'ovn-central',
                'ovn-nbctl', 'lsp-add', vm_config['ovn_switch'],
                f"sp-{vm_config['ovn_router']}-{vm_config['ovn_switch']}"
            ])

            # Set switch port type to router
            self._run_command([
                'sudo', 'docker', 'exec', 'ovn-central',
                'ovn-nbctl', 'lsp-set-type',
                f"sp-{vm_config['ovn_router']}-{vm_config['ovn_switch']}",
                'router'
            ])

            # Set switch port options
            self._run_command([
                'sudo', 'docker', 'exec', 'ovn-central',
                'ovn-nbctl', 'lsp-set-options',
                f"sp-{vm_config['ovn_router']}-{vm_config['ovn_switch']}",
                f'router-port={router_port}'
            ])

        logger.info(f"OVN networking configured for {vm_name}")
        return True

    def create_vm(self, vm_name: str) -> bool:
        """Create and start a VM"""
        if vm_name not in self.vms:
            logger.error(f"Unknown VM: {vm_name}")
            return False

        vm_config = self.vms[vm_name]

        logger.info(f"Creating VM {vm_name}...")

        # Check if VM already exists
        result = self._run_command(['sudo', 'virsh', 'list', '--all'], check=False)
        if vm_name in result.stdout:
            logger.warning(f"VM {vm_name} already exists")
            return False

        # Create VM disk
        vm_disk = self.create_vm_disk(vm_name)

        # Create cloud-init ISO
        cloud_init_iso = self.create_cloud_init(vm_name)

        # Create VM with virt-install using OVS bridge
        # libvirt will create the TAP interface and integrate it with OVS
        import platform
        arch = platform.machine()

        # Use appropriate CPU model based on architecture
        if os.path.exists('/dev/kvm'):
            cpu_model = 'host-passthrough'
        elif arch == 'aarch64':
            cpu_model = 'cortex-a57'  # Generic ARM64 CPU
        else:
            cpu_model = 'qemu64'  # x86_64

        cmd = [
            'sudo', 'virt-install',
            '--name', vm_name,
            '--memory', str(vm_config['memory']),
            '--vcpus', str(vm_config['cpus']),
            '--disk', f'path={vm_disk},format=qcow2',
            '--cdrom', cloud_init_iso,
            '--os-variant', 'ubuntu24.04',  # Use Ubuntu 24.04 to match our image
            '--network', f'bridge=br-int,virtualport_type=openvswitch,model=virtio,mac={vm_config["mac"]}',
            '--graphics', 'none',
            '--console', 'pty,target_type=serial',
            '--noautoconsole',
            '--boot', 'hd,cdrom',
            '--cpu', cpu_model
        ]

        result = self._run_command(cmd, check=False)

        if result.returncode != 0:
            logger.error(f"Failed to create VM {vm_name}")
            if result.stderr:
                logger.error(f"Error: {result.stderr}")
            # Clean up the TAP interface if VM creation failed
            self._run_command(['sudo', 'ovs-vsctl', '--if-exists', 'del-port', 'br-int', tap_name], check=False)
            self._run_command(['sudo', 'ip', 'link', 'del', tap_name], check=False)
            return False

        logger.info(f"VM {vm_name} created successfully")

        # CRITICAL: Configure the TAP interface for OVN binding
        self.configure_tap_for_ovn(vm_name)

        # Fix offloading settings for the VM's TAP interface
        self.fix_tap_offloading(vm_name)

        # IMPORTANT: Ensure the cloud-init ISO is permanently attached
        # virt-install with --cdrom creates the device but may not insert media
        logger.info(f"Ensuring cloud-init ISO is permanently attached to {vm_name}...")

        # Use --config to make the change persistent and --live for running VMs
        attach_cmd = [
            'sudo', 'virsh', 'change-media', vm_name, 'sda',
            cloud_init_iso, '--insert', '--config'
        ]
        attach_result = self._run_command(attach_cmd, check=False)

        if attach_result.returncode != 0:
            # If sda doesn't exist or fails, try attaching as a new disk
            logger.warning(f"change-media failed: {attach_result.stderr}")
            logger.info("Trying to attach as new CDROM device...")
            attach_disk_cmd = [
                'sudo', 'virsh', 'attach-disk', vm_name,
                cloud_init_iso, 'sdb',
                '--type', 'cdrom',
                '--mode', 'readonly',
                '--persistent'
            ]
            disk_result = self._run_command(attach_disk_cmd, check=False)
            if disk_result.returncode != 0:
                logger.error(f"Failed to attach cloud-init ISO: {disk_result.stderr}")
                logger.error("VM may not boot properly without cloud-init!")
            else:
                logger.info(f"Cloud-init ISO attached as sdb to {vm_name}")
        else:
            logger.info(f"Cloud-init ISO permanently attached to {vm_name}")

        # Get the actual interface name created by libvirt
        vm_config = self.vms[vm_name]

        # Find the interface name that libvirt created
        result = self._run_command(['sudo', 'virsh', 'domiflist', vm_name], check=False)
        tap_name = None
        for line in result.stdout.splitlines():
            if 'br-int' in line:
                # Extract the interface name (usually vnetX)
                parts = line.split()
                if len(parts) >= 1:
                    tap_name = parts[0]
                    break

        if tap_name:
            logger.info(f"Found VM interface {tap_name} on br-int")

            # Set VLAN tag and OVN external IDs on the interface
            # Note: We must override libvirt's auto-generated UUID with our OVN port name
            lsp_name = f"lsp-{vm_name}"
            self._run_command([
                'sudo', 'ovs-vsctl',
                '--', 'set', 'port', tap_name, f'tag={vm_config["vlan"]}',
                '--', 'set', 'interface', tap_name, f'external-ids:iface-id={lsp_name}',
                '--', 'set', 'interface', tap_name, 'external-ids:iface-status=active'
            ])
            logger.info(f"Configured {tap_name} with VLAN {vm_config['vlan']} and OVN binding to {lsp_name}")
        else:
            logger.warning(f"Could not find interface for {vm_name} on br-int")

        # Setup OVN networking
        self.setup_ovn_networking(vm_name)

        # Start the VM (virt-install creates but doesn't start by default)
        logger.info(f"Starting VM {vm_name}...")
        result = self._run_command(['sudo', 'virsh', 'start', vm_name], check=False)
        if result.returncode != 0:
            logger.warning(f"Could not start VM {vm_name}: {result.stderr}")
        else:
            logger.info(f"VM {vm_name} started successfully")

        # Set VM to autostart when host boots
        logger.info(f"Setting VM {vm_name} to autostart...")
        result = self._run_command(['sudo', 'virsh', 'autostart', vm_name], check=False)
        if result.returncode != 0:
            logger.warning(f"Could not set autostart for VM {vm_name}: {result.stderr}")
        else:
            logger.info(f"VM {vm_name} set to autostart")

        return True

    def destroy_vm(self, vm_name: str) -> bool:
        """Stop and remove a VM"""
        logger.info(f"Destroying VM {vm_name}...")

        # Stop VM if running
        self._run_command(['sudo', 'virsh', 'destroy', vm_name], check=False)

        # Undefine VM (with --nvram in case UEFI is used)
        self._run_command(['sudo', 'virsh', 'undefine', vm_name, '--nvram'], check=False)

        # Remove TAP interface from OVS
        tap_name = f"tap-{vm_name}"
        self._run_command(['sudo', 'ovs-vsctl', 'del-port', 'br-int', tap_name], check=False)

        # Remove TAP interface
        self._run_command(['sudo', 'ip', 'link', 'delete', tap_name], check=False)

        # Remove OVN logical port
        vm_config = self.vms.get(vm_name, {})
        if 'ovn_switch' in vm_config:
            self._run_command([
                'sudo', 'docker', 'exec', 'ovn-central',
                'ovn-nbctl', 'lsp-del', f'lsp-{vm_name}'
            ], check=False)

        # Remove disk and cloud-init ISO
        disk_path = self.image_path / f"{vm_name}.qcow2"
        cloud_init_path = self.image_path / f"{vm_name}-cloud-init.iso"

        if disk_path.exists():
            disk_path.unlink()
        if cloud_init_path.exists():
            cloud_init_path.unlink()

        logger.info(f"VM {vm_name} destroyed")
        return True

    def get_vm_status(self, vm_name: str = None) -> Dict:
        """Get status of VM(s)"""
        if vm_name:
            vms_to_check = [vm_name] if vm_name in self.vms else []
        else:
            vms_to_check = list(self.vms.keys())

        status = {}

        # Get virsh list
        result = self._run_command(['sudo', 'virsh', 'list', '--all'], check=False)
        virsh_output = result.stdout

        for vm in vms_to_check:
            vm_status = {
                'exists': vm in virsh_output,
                'running': False,
                'ip': self.vms[vm]['ip'],
                'vpc': self.vms[vm]['vpc']
            }

            if vm_status['exists']:
                # Check if running
                result = self._run_command(['sudo', 'virsh', 'domstate', vm], check=False)
                vm_status['running'] = 'running' in result.stdout.lower()

            status[vm] = vm_status

        return status

    def create_all_vms(self) -> bool:
        """Create all configured VMs"""
        logger.info("Creating all VMs...")

        # Download base image first
        if not self.download_base_image():
            return False

        success = True
        for vm_name in self.vms:
            if not self.create_vm(vm_name):
                success = False
                logger.error(f"Failed to create VM {vm_name}")

        return success

    def destroy_all_vms(self) -> bool:
        """Destroy all configured VMs"""
        logger.info("Destroying all VMs...")

        success = True
        for vm_name in self.vms:
            if not self.destroy_vm(vm_name):
                success = False
                logger.error(f"Failed to destroy VM {vm_name}")

        return success


def main():
    """CLI interface for VM manager"""
    import argparse

    parser = argparse.ArgumentParser(description='OVS Container Lab VM Manager')
    parser.add_argument('action', choices=['create', 'destroy', 'status', 'create-all', 'destroy-all'],
                       help='Action to perform')
    parser.add_argument('--vm', help='VM name (for create/destroy/status)')

    args = parser.parse_args()

    manager = VMManager()

    # Check dependencies first
    if not manager.check_dependencies():
        sys.exit(1)

    if args.action == 'create':
        if not args.vm:
            print("Error: --vm required for create action")
            sys.exit(1)
        success = manager.create_vm(args.vm)
    elif args.action == 'destroy':
        if not args.vm:
            print("Error: --vm required for destroy action")
            sys.exit(1)
        success = manager.destroy_vm(args.vm)
    elif args.action == 'status':
        status = manager.get_vm_status(args.vm)
        print(json.dumps(status, indent=2))
        success = True
    elif args.action == 'create-all':
        success = manager.create_all_vms()
    elif args.action == 'destroy-all':
        success = manager.destroy_all_vms()
    else:
        success = False

    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()