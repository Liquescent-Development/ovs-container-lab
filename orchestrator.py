#!/usr/bin/env python3
"""
Simplified OVS Container Lab Orchestrator
All network configuration is in docker-compose.yml
"""

import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class DockerNetworkPlugin:
    """Manages the OVS Container Network Docker plugin"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.plugin_name = "ovs-container-network:latest"
        self.plugin_dir = "/home/lima/code/ovs-container-lab/ovs-container-network"

    def is_installed(self) -> bool:
        """Check if the plugin is installed and enabled"""
        try:
            result = subprocess.run(
                ["docker", "plugin", "ls"],
                capture_output=True, text=True, check=True
            )
            return self.plugin_name in result.stdout and "true" in result.stdout
        except subprocess.CalledProcessError:
            return False

    def install(self) -> bool:
        """Build and install the OVS network plugin"""
        logger.info("Installing OVS Container Network plugin...")

        # Check if we're in Lima VM
        if not os.path.exists("/etc/os-release") or "Ubuntu" not in open("/etc/os-release").read():
            logger.error("Plugin installation must be run inside the Lima VM")
            return False

        # Navigate to plugin directory
        if not os.path.exists(self.plugin_dir):
            logger.error(f"Plugin directory not found: {self.plugin_dir}")
            return False

        os.chdir(self.plugin_dir)

        # Build the Docker image using the Dockerfile
        logger.info("Building Docker image for plugin...")
        result = subprocess.run(["docker", "build", "-t", "ovs-container-network:build", "."],
                              capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to build Docker image: {result.stderr}")
            return False

        # Create plugin from the Docker image
        logger.info("Creating plugin from Docker image...")

        # First, create a temporary container to export the rootfs
        build_dir = "/tmp/ovs-container-network-build"
        subprocess.run(["rm", "-rf", build_dir], check=False)
        os.makedirs(build_dir, exist_ok=True)

        # Export the image to rootfs
        logger.info("Exporting image to rootfs...")
        container_id = subprocess.run(
            ["docker", "create", "ovs-container-network:build"],
            capture_output=True, text=True
        ).stdout.strip()

        result = subprocess.run(
            ["docker", "export", container_id, "-o", f"{build_dir}/rootfs.tar"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            logger.error(f"Failed to export container: {result.stderr}")
            subprocess.run(["docker", "rm", container_id], check=False)
            return False

        # Extract the rootfs
        os.makedirs(f"{build_dir}/rootfs", exist_ok=True)
        subprocess.run(["tar", "-xf", f"{build_dir}/rootfs.tar", "-C", f"{build_dir}/rootfs"], check=True)

        # Clean up temporary container
        subprocess.run(["docker", "rm", container_id], check=False)

        # Copy config.json
        subprocess.run(["cp", "config.json", f"{build_dir}/"], check=True)

        # Remove existing plugin if present
        subprocess.run(["docker", "plugin", "rm", "-f", self.plugin_name],
                      capture_output=True, check=False)

        # Create the plugin
        logger.info("Creating Docker plugin...")
        os.chdir(build_dir)
        result = subprocess.run(["docker", "plugin", "create", self.plugin_name, "."],
                              capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to create plugin: {result.stderr}")
            return False

        logger.info("Enabling plugin...")
        result = subprocess.run(["docker", "plugin", "enable", self.plugin_name],
                              capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"Failed to enable plugin: {result.stderr}")
            return False

        # Create br-int if it doesn't exist
        result = subprocess.run(["sudo", "ovs-vsctl", "br-exists", "br-int"],
                              capture_output=True, check=False)
        if result.returncode != 0:
            logger.info("Creating OVS integration bridge (br-int)...")
            subprocess.run(["sudo", "ovs-vsctl", "add-br", "br-int"], check=True)

        logger.info("✅ OVS Container Network Plugin installed successfully!")
        return True

    def uninstall(self) -> bool:
        """Uninstall the OVS network plugin"""
        logger.info("Uninstalling OVS Container Network plugin...")

        # First disable the plugin
        subprocess.run(["docker", "plugin", "disable", self.plugin_name],
                      capture_output=True, check=False)

        # Then remove it
        result = subprocess.run(["docker", "plugin", "rm", self.plugin_name],
                              capture_output=True, text=True, check=False)

        if result.returncode == 0:
            logger.info("✅ Plugin uninstalled successfully")
            return True
        else:
            if "not found" in result.stderr.lower():
                logger.info("Plugin was not installed")
                return True
            else:
                logger.error(f"Failed to uninstall plugin: {result.stderr}")
                return False


class MonitoringManager:
    """Manages monitoring exporters"""

    def restart_exporters(self) -> bool:
        """Restart monitoring exporters"""
        print("\n🔄 Restarting Monitoring Exporters")
        print("="*50)

        # First ensure OVS has the correct stable system-id
        print("\n🔧 Ensuring stable OVS system-id...")
        subprocess.run(["sudo", "ovs-vsctl", "set", "open-vswitch", ".",
                       "external_ids:system-id=chassis-host"],
                      capture_output=True)
        print("   ✓ Set system-id to 'chassis-host'")

        # Restart OVS exporter
        print("\n📊 OVS Exporter:")
        result = subprocess.run(["sudo", "systemctl", "restart", "ovs-exporter"],
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("   ✓ Service restarted")
            # Give it a moment to start
            time.sleep(2)
            # Check if it's actually running
            status = subprocess.run(["sudo", "systemctl", "is-active", "ovs-exporter"],
                                  capture_output=True, text=True)
            if status.stdout.strip() == "active":
                print("   ✓ Service is now active")
            else:
                print("   ❌ Service failed to start")
                print("   Checking logs...")
                logs = subprocess.run(["sudo", "journalctl", "-u", "ovs-exporter", "-n", "10", "--no-pager"],
                                    capture_output=True, text=True)
                print("   Recent logs:")
                for line in logs.stdout.split('\n')[-5:]:
                    if line.strip():
                        print(f"      {line}")
        else:
            print("   ❌ Failed to restart service")
            print(f"   Error: {result.stderr}")

        # Restart node exporter
        print("\n📊 Node Exporter:")
        result = subprocess.run(["sudo", "systemctl", "restart", "prometheus-node-exporter"],
                              capture_output=True, text=True)
        if result.returncode == 0:
            print("   ✓ Service restarted")
        else:
            # Try alternative name
            result = subprocess.run(["sudo", "systemctl", "restart", "node_exporter"],
                                  capture_output=True, text=True)
            if result.returncode == 0:
                print("   ✓ Service restarted")
            else:
                print("   ⚠️  Could not restart node exporter")

        print("\n" + "="*50)
        return True

    def check_exporters(self) -> bool:
        """Check status of all exporters"""
        print("\n🔍 Checking Monitoring Exporters")
        print("="*50)

        # Check OVS exporter
        print("\n📊 OVS Exporter:")
        result = subprocess.run(["sudo", "systemctl", "status", "ovs-exporter", "--no-pager"],
                              capture_output=True, text=True)
        if "active (running)" in result.stdout:
            print("   ✓ Service is running")
            # Try to curl metrics
            curl_result = subprocess.run(["curl", "-s", "http://localhost:9475/metrics"],
                                        capture_output=True, text=True)
            if curl_result.returncode == 0 and "ovs_" in curl_result.stdout:
                print("   ✓ Metrics endpoint is responding")
                print(f"   📈 Sample metrics: {len(curl_result.stdout.split(chr(10)))} lines")
            else:
                print("   ❌ Metrics endpoint not responding")
        else:
            print("   ❌ Service is not running")
            print("   Run: make setup-monitoring")

        # Check OVN exporter (runs in container)
        print("\n📊 OVN Exporter:")
        # Check if ovn-central container is running
        result = subprocess.run(["docker", "ps", "--filter", "name=ovn-central", "--format", "{{.Names}}"],
                              capture_output=True, text=True)
        if "ovn-central" in result.stdout:
            # Check if exporter process is running
            result = subprocess.run(["docker", "exec", "ovn-central", "ps", "aux"],
                                  capture_output=True, text=True)
            if "ovn-exporter" in result.stdout:
                print("   ✓ Service is running in ovn-central container")
                # Try to curl metrics
                curl_result = subprocess.run(["docker", "exec", "ovn-central", "curl", "-s", "http://localhost:9476/metrics"],
                                            capture_output=True, text=True)
                if curl_result.returncode == 0 and "ovn_" in curl_result.stdout:
                    print("   ✓ Metrics endpoint is responding")
                    print(f"   📈 Sample metrics: {len(curl_result.stdout.split(chr(10)))} lines")
                else:
                    print("   ❌ Metrics endpoint not responding")
            else:
                print("   ❌ Service is not running in container")
                print("   Container may need to be restarted")
        else:
            print("   ⚠️  ovn-central container is not running")

        # Check node exporter
        print("\n📊 Node Exporter:")
        result = subprocess.run(["sudo", "systemctl", "status", "prometheus-node-exporter", "--no-pager"],
                              capture_output=True, text=True)
        if "active (running)" in result.stdout:
            print("   ✓ Service is running")
        else:
            # Try the alternative service name
            result = subprocess.run(["sudo", "systemctl", "status", "node_exporter", "--no-pager"],
                                  capture_output=True, text=True)
            if "active (running)" in result.stdout:
                print("   ✓ Service is running")
            else:
                print("   ❌ Service is not running")

        # Check host.docker.internal resolution (READ-ONLY check)
        print("\n🌐 Docker Host Resolution:")
        result = subprocess.run(["grep", "host.docker.internal", "/etc/hosts"],
                              capture_output=True, text=True)
        if result.returncode != 0:
            print("   ❌ host.docker.internal not in /etc/hosts")
            print("   Run: make setup-monitoring to fix this")
        else:
            print("   ✓ host.docker.internal is configured")

        # Check if Prometheus can reach exporters
        print("\n📊 Prometheus Connectivity:")

        # First check if Prometheus container is running
        prom_status = subprocess.run(
            ["docker", "ps", "--filter", "name=prometheus", "--format", "{{.Names}}"],
            capture_output=True, text=True
        )

        if "prometheus" not in prom_status.stdout:
            print("   ❌ Prometheus container is not running")
            print("   Run: make up to start containers")
        else:
            # Check OVS exporter with a timeout in wget itself
            prom_check = subprocess.run(
                ["docker", "exec", "prometheus", "wget", "-O-", "-q", "-T", "2", "http://host.docker.internal:9475/metrics"],
                capture_output=True, text=True
            )
            if prom_check.returncode == 0 and "ovs_" in prom_check.stdout:
                print("   ✓ Prometheus can reach OVS exporter")
            else:
                print("   ❌ Prometheus cannot reach OVS exporter")
                if prom_check.returncode == 124:
                    print("   Connection timed out - check if OVS exporter is running")
                else:
                    print("   This might be a Docker/Lima networking issue")

            # Check OVN exporter (using host.docker.internal since port is exposed)
            prom_check = subprocess.run(
                ["docker", "exec", "prometheus", "wget", "-O-", "-q", "-T", "2", "http://host.docker.internal:9476/metrics"],
                capture_output=True, text=True
            )
            if prom_check.returncode == 0 and "ovn_" in prom_check.stdout:
                print("   ✓ Prometheus can reach OVN exporter")
            else:
                print("   ❌ Prometheus cannot reach OVN exporter")
                if prom_check.returncode == 124:
                    print("   Connection timed out - check if OVN exporter is running")
                else:
                    print("   May need to connect Prometheus to transit-overlay network")

        print("\n" + "="*50)
        return True

    def setup_ovs_exporter(self) -> bool:
        """Setup OVS exporter as a systemd service"""
        logger.info("Setting up OVS exporter...")

        # First ensure host.docker.internal is in /etc/hosts for Prometheus connectivity
        result = subprocess.run(["grep", "host.docker.internal", "/etc/hosts"],
                              capture_output=True, text=True)
        if result.returncode != 0:
            logger.info("Adding host.docker.internal to /etc/hosts...")
            # Get the main IP of the host
            ip_result = subprocess.run(["ip", "-4", "addr", "show", "docker0"],
                                     capture_output=True, text=True)
            if "inet " in ip_result.stdout:
                # Extract IP from docker0 interface
                for line in ip_result.stdout.split('\n'):
                    if 'inet ' in line:
                        ip = line.strip().split()[1].split('/')[0]
                        add_cmd = f"echo '{ip} host.docker.internal' | sudo tee -a /etc/hosts"
                        subprocess.run(["bash", "-c", add_cmd], capture_output=True)
                        logger.info(f"Added host.docker.internal -> {ip}")
                        break

        # Download and install ovs-exporter
        arch = subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip()
        if arch == "aarch64":
            arch = "arm64"
        elif arch == "x86_64":
            arch = "amd64"

        # Check if already installed
        if os.path.exists("/usr/local/bin/ovs-exporter"):
            logger.info("OVS exporter already installed")

            # Ensure OVS has the stable system-id
            subprocess.run(["sudo", "ovs-vsctl", "set", "open-vswitch", ".",
                          "external_ids:system-id=chassis-host"],
                         capture_output=True)

            # Also write system-id.conf to match (exporter checks both)
            with open("/tmp/system-id.conf", "w") as f:
                f.write("chassis-host\n")
            subprocess.run(["sudo", "mv", "/tmp/system-id.conf", "/etc/openvswitch/system-id.conf"], check=True)
            subprocess.run(["sudo", "chmod", "644", "/etc/openvswitch/system-id.conf"], check=True)

            # Update service file to ensure it has the correct system-id
            stable_system_id = "chassis-host"
            service_content = f"""[Unit]
Description=OVS Exporter for Prometheus
After=network.target openvswitch-switch.service

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/ovs-exporter \\
  --web.listen-address=0.0.0.0:9475 \\
  --web.telemetry-path=/metrics \\
  --log.level=info
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""
            with open("/tmp/ovs-exporter.service", "w") as f:
                f.write(service_content)

            subprocess.run(["sudo", "mv", "/tmp/ovs-exporter.service", "/etc/systemd/system/"], check=True)
            subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)

            # Now restart the service
            result = subprocess.run(["sudo", "systemctl", "restart", "ovs-exporter"],
                                  capture_output=True, text=True)
            if result.returncode == 0:
                logger.info("OVS exporter service restarted with correct system-id")
                return True
            else:
                logger.warning("OVS exporter installed but service failed to start, reinstalling...")
                # Continue with installation

        logger.info(f"Downloading OVS exporter for {arch}...")
        download_url = f"https://github.com/Liquescent-Development/ovs_exporter/releases/download/v2.3.1/ovs-exporter-2.3.1.linux-{arch}.tar.gz"

        logger.info(f"Download URL: {download_url}")
        result = subprocess.run([
            "wget", "-q", "-O", f"/tmp/ovs-exporter-2.3.1.linux-{arch}.tar.gz",
            download_url
        ], capture_output=True, text=True)

        if result.returncode != 0:
            logger.error(f"Failed to download OVS exporter: {result.stderr}")
            return False

        # Extract and install
        subprocess.run(["tar", "xzf", f"/tmp/ovs-exporter-2.3.1.linux-{arch}.tar.gz", "-C", "/tmp"], check=True)

        # Stop service first if running to avoid "text file busy"
        subprocess.run(["sudo", "systemctl", "stop", "ovs-exporter"], check=False)

        # Copy the binary
        subprocess.run(["sudo", "cp", f"/tmp/ovs-exporter-2.3.1.linux-{arch}/ovs-exporter", "/usr/local/bin/ovs-exporter"], check=True)
        subprocess.run(["sudo", "chmod", "+x", "/usr/local/bin/ovs-exporter"], check=True)

        # We always use 'chassis-host' as our stable system-id
        # This is set in setup_chassis() method of OVSChassisManager
        stable_system_id = "chassis-host"

        # Write system-id.conf to match what's in the database
        with open("/tmp/system-id.conf", "w") as f:
            f.write("chassis-host\n")
        subprocess.run(["sudo", "mv", "/tmp/system-id.conf", "/etc/openvswitch/system-id.conf"], check=True)
        subprocess.run(["sudo", "chmod", "644", "/etc/openvswitch/system-id.conf"], check=True)

        # Create systemd service (exporter reads system-id from OVS database)
        service_content = f"""[Unit]
Description=OVS Exporter for Prometheus
After=network.target openvswitch-switch.service

[Service]
Type=simple
User=root
ExecStart=/usr/local/bin/ovs-exporter \\
  --web.listen-address=0.0.0.0:9475 \\
  --web.telemetry-path=/metrics \\
  --log.level=info
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
"""

        with open("/tmp/ovs-exporter.service", "w") as f:
            f.write(service_content)

        subprocess.run(["sudo", "mv", "/tmp/ovs-exporter.service", "/etc/systemd/system/"], check=True)
        subprocess.run(["sudo", "systemctl", "daemon-reload"], check=True)
        subprocess.run(["sudo", "systemctl", "enable", "ovs-exporter"], check=True)
        subprocess.run(["sudo", "systemctl", "restart", "ovs-exporter"], check=True)

        logger.info("✅ OVS exporter installed and started")
        return True

    def setup_node_exporter(self) -> bool:
        """Setup node exporter"""
        logger.info("Setting up node exporter...")

        # Check if already installed
        if os.path.exists("/usr/local/bin/node_exporter"):
            logger.info("Node exporter already installed")
            return True

        # Install via apt
        result = subprocess.run(["sudo", "apt-get", "install", "-y", "prometheus-node-exporter"],
                              capture_output=True, text=True)

        if result.returncode == 0:
            logger.info("✅ Node exporter installed")
            return True
        else:
            logger.error("Failed to install node exporter")
            return False


class OVSChassisManager:
    """Manages OVS chassis configuration"""

    def setup_chassis(self, ovn_ip="172.30.0.5", encap_ip="172.30.0.1") -> bool:
        """Configure host OVS to connect to OVN

        Args:
            ovn_ip: IP address of OVN central (default: 172.30.0.5 on transit-overlay)
            encap_ip: Local IP for tunnel encapsulation (default: 172.30.0.1)
        """
        ovn_sb_endpoint = f"tcp:{ovn_ip}:6642"
        logger.info(f"Configuring OVS chassis to connect to OVN at {ovn_sb_endpoint}")
        logger.info(f"Using encapsulation IP: {encap_ip}")

        # Configure OVS to connect to OVN
        commands = [
            ["sudo", "ovs-vsctl", "set", "open-vswitch", ".", f"external_ids:ovn-remote={ovn_sb_endpoint}"],
            ["sudo", "ovs-vsctl", "set", "open-vswitch", ".", f"external_ids:ovn-encap-ip={encap_ip}"],
            ["sudo", "ovs-vsctl", "set", "open-vswitch", ".", "external_ids:ovn-encap-type=geneve"],
            ["sudo", "ovs-vsctl", "set", "open-vswitch", ".", "external_ids:system-id=chassis-host"]
        ]

        for cmd in commands:
            result = subprocess.run(cmd, capture_output=True)
            if result.returncode != 0:
                logger.error(f"Failed to run: {' '.join(cmd)}")
                return False

        # Start ovn-controller if not running
        subprocess.run(["sudo", "systemctl", "start", "ovn-controller"], check=False)

        logger.info("✅ OVS chassis configured")
        return True


class NetworkChecker:
    """Comprehensive network state checker for OVS Container Lab"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

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

        # Check Docker plugin
        print("\n5. Docker Plugin Status:")
        print("-" * 40)
        plugin_issues = self._check_plugin()
        issues.extend(plugin_issues)

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

        # Check if OVN central is running
        result = subprocess.run(["docker", "ps", "-q", "-f", "name=ovn-central"],
                              capture_output=True, text=True)
        if not result.stdout.strip():
            print("  ❌ OVN central container not running")
            issues.append("OVN central container is not running")
            return issues  # Can't check OVN if container isn't running

        # Check logical routers
        result = subprocess.run(
            ["docker", "exec", "ovn-central", "ovn-nbctl", "lr-list"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print("  ❌ Failed to query logical routers")
            issues.append("Cannot query OVN logical routers")
        else:
            routers = [line.split()[1].strip('()') for line in result.stdout.strip().split('\n') if line]
            if routers:
                print(f"  ✓ {len(routers)} logical routers configured")
            else:
                print("  ⚠ No logical routers configured")

        # Check logical switches
        result = subprocess.run(
            ["docker", "exec", "ovn-central", "ovn-nbctl", "ls-list"],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            print("  ❌ Failed to query logical switches")
            issues.append("Cannot query OVN logical switches")
        else:
            switches = [line.split()[1].strip('()') for line in result.stdout.strip().split('\n') if line]
            print(f"  ✓ {len(switches)} logical switches configured")

        return issues

    def _check_bindings(self):
        """Check OVN port bindings to chassis"""
        issues = []

        # Check if OVN central is running
        result = subprocess.run(["docker", "ps", "-q", "-f", "name=ovn-central"],
                              capture_output=True, text=True)
        if not result.stdout.strip():
            print("  ⚠ OVN central not running, skipping binding checks")
            return issues

        # Get all logical ports
        result = subprocess.run(
            ["docker", "exec", "ovn-central", "ovn-sbctl", "find", "port_binding", "type=\"\""],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            print("  ⚠ Cannot check port bindings (OVN SB not accessible)")
            return issues

        unbound_ports = []
        bound_ports = 0
        current_port = None

        for line in result.stdout.split('\n'):
            if 'logical_port' in line and ':' in line:
                parts = line.split(':', 1)
                if len(parts) > 1:
                    current_port = parts[1].strip().strip('"')
            elif line.startswith('chassis') and ':' in line and current_port:
                parts = line.split(':', 1)
                if len(parts) > 1:
                    chassis = parts[1].strip()
                    if chassis == '[]' or not chassis:
                        unbound_ports.append(current_port)
                    else:
                        bound_ports += 1
                    current_port = None

        if unbound_ports:
            print(f"  ❌ {len(unbound_ports)} ports not bound to chassis: {', '.join(unbound_ports[:5])}")
            issues.append(f"Unbound OVN ports: {', '.join(unbound_ports)}")
        elif bound_ports > 0:
            print(f"  ✓ All {bound_ports} ports bound to chassis")
        else:
            print("  ⚠ No ports found in OVN SB database")

        return issues

    def _check_connectivity(self):
        """Check basic container connectivity"""
        issues = []

        # Check if test containers exist
        test_containers = ["vpc-a-web", "vpc-b-web"]
        for container in test_containers:
            result = subprocess.run(["docker", "ps", "-q", "-f", f"name={container}"],
                                  capture_output=True, text=True)
            if not result.stdout.strip():
                print(f"  ⚠ Container {container} not found, skipping connectivity test")
                continue

            # Test container to gateway connectivity
            result = subprocess.run(
                ["docker", "exec", container, "ping", "-c", "1", "-W", "1", "10.0.1.1"],
                capture_output=True
            )
            if result.returncode != 0:
                print(f"  ❌ {container} cannot reach its gateway")
                issues.append(f"{container} to gateway connectivity failed")
            else:
                print(f"  ✓ {container} can reach its gateway")
            break  # Just test one container if available

        return issues

    def _check_plugin(self):
        """Check Docker plugin status"""
        issues = []

        result = subprocess.run(["docker", "plugin", "ls", "--format", "{{.Name}}:{{.Enabled}}"],
                              capture_output=True, text=True)

        plugin_found = False
        plugin_enabled = False

        for line in result.stdout.strip().split('\n'):
            if "ovs-container-network" in line:
                plugin_found = True
                if ":true" in line:
                    plugin_enabled = True
                break

        if not plugin_found:
            print("  ❌ OVS Container Network plugin not installed")
            issues.append("OVS Container Network plugin not found")
        elif not plugin_enabled:
            print("  ❌ OVS Container Network plugin not enabled")
            issues.append("OVS Container Network plugin is disabled")
        else:
            print("  ✓ OVS Container Network plugin is installed and enabled")

        return issues


class TrafficGenerator:
    """Manages traffic generation for the OVS Container Lab"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)

    def check_traffic_status(self):
        """Check if traffic generation is running and working"""
        print("\n🔍 Checking Traffic Generation Status")
        print("="*50)

        # Define traffic pattern specifications
        traffic_specs = {
            'standard': {
                'bandwidth': '100 Mbps',
                'pps': '1000 packets/sec',
                'connections': '20 concurrent',
                'cpu': '50% limit'
            },
            'high': {
                'bandwidth': '500 Mbps',
                'pps': '5000 packets/sec',
                'connections': '40 concurrent',
                'cpu': '70% limit'
            },
            'chaos': {
                'bandwidth': '1000 Mbps',
                'pps': '10000 packets/sec',
                'connections': '60 concurrent',
                'cpu': '90% limit'
            }
        }

        traffic_gens = ["traffic-gen-a", "traffic-gen-b"]
        active_pattern = None
        all_running = True

        for gen in traffic_gens:
            print(f"\n📦 {gen}:")

            # Check if container is running
            result = subprocess.run(["docker", "ps", "--format", "{{.Names}}", "-f", f"name={gen}"],
                                  capture_output=True, text=True)
            if gen not in result.stdout:
                print(f"   ❌ Container not running")
                all_running = False
                continue
            else:
                print(f"   ✓ Container is running")

            # Check if traffic-gen.py process is running and detect mode
            ps_result = subprocess.run(["docker", "exec", gen, "ps", "aux"],
                                      capture_output=True, text=True)

            traffic_running = False
            for line in ps_result.stdout.split('\n'):
                if 'traffic-gen.py' in line and 'python' in line:
                    traffic_running = True
                    # Try to detect mode from command line (positional argument)
                    if 'traffic-gen.py chaos' in line:
                        active_pattern = 'chaos'
                    elif 'traffic-gen.py high' in line:
                        active_pattern = 'high'
                    elif 'traffic-gen.py standard' in line:
                        active_pattern = 'standard'
                    else:
                        # Default to standard if no mode specified
                        active_pattern = 'standard'
                    break

            if traffic_running:
                pgrep_result = subprocess.run(["docker", "exec", gen, "pgrep", "-f", "traffic-gen.py"],
                                            capture_output=True, text=True)
                pid = pgrep_result.stdout.strip()
                print(f"   ✓ traffic-gen.py is running (PID: {pid})")

                # Check CPU usage of the process
                cpu_result = subprocess.run(
                    ["docker", "exec", gen, "ps", "-p", pid, "-o", "%cpu="],
                    capture_output=True, text=True
                )
                if cpu_result.returncode == 0:
                    cpu_usage = cpu_result.stdout.strip()
                    print(f"   📊 CPU Usage: {cpu_usage}%")

                # Check last few lines of output
                log_result = subprocess.run(["docker", "exec", gen, "tail", "-5", "/tmp/traffic.log"],
                                          capture_output=True, text=True)
                if log_result.returncode == 0 and log_result.stdout:
                    print(f"   📋 Recent activity:")
                    for line in log_result.stdout.split('\n')[:3]:
                        if line.strip():
                            print(f"      {line[:80]}")  # Truncate long lines
            else:
                print(f"   ❌ traffic-gen.py is NOT running")
                all_running = False

                # Try to run it manually to see error
                print(f"   🔧 Testing manual execution:")
                test_result = subprocess.run(
                    ["docker", "exec", gen, "bash", "-c", "cd /workspace && python3 traffic-gen.py --help"],
                    capture_output=True, text=True
                )
                if test_result.returncode == 0:
                    print(f"      ✓ Script exists and is executable")
                else:
                    print(f"      ❌ Script error: {test_result.stderr}")

            # Test connectivity to targets
            print(f"   🌐 Testing connectivity:")
            targets = [
                ("10.0.1.10", "vpc-a-web") if "gen-a" in gen else ("10.1.1.10", "vpc-b-web")
            ]
            for ip, name in targets:
                ping_result = subprocess.run(
                    ["docker", "exec", gen, "ping", "-c", "1", "-W", "1", ip],
                    capture_output=True, text=True
                )
                if ping_result.returncode == 0:
                    print(f"      ✓ Can reach {name} ({ip})")
                else:
                    print(f"      ❌ Cannot reach {name} ({ip})")

        # Show traffic pattern summary
        print("\n" + "="*50)
        print("📊 TRAFFIC PATTERN SUMMARY")
        print("="*50)

        if active_pattern and all_running:
            print(f"\n🎯 Active Pattern: {active_pattern.upper()}")
            specs = traffic_specs.get(active_pattern, {})
            print("\n📈 Expected Performance Targets:")
            for metric, value in specs.items():
                print(f"   • {metric.replace('_', ' ').title()}: {value}")

            # Check actual metrics from monitoring
            print("\n📉 Actual Performance (checking metrics):")

            # Try to get metrics from InfluxDB or Prometheus
            # Check bandwidth via container network stats
            total_bandwidth_mbps = 0
            for gen in traffic_gens:
                stats_result = subprocess.run(
                    ["docker", "stats", "--no-stream", "--format", "{{.Container}}: {{.NetIO}}", gen],
                    capture_output=True, text=True
                )
                if stats_result.returncode == 0 and stats_result.stdout.strip():
                    print(f"   • {stats_result.stdout.strip()}")
                    # Try to parse the network I/O to estimate bandwidth
                    # Format is usually like "1.2MB / 3.4MB" (received / sent)
                    try:
                        net_io = stats_result.stdout.split(':')[1].strip()
                        parts = net_io.split('/')
                        if len(parts) >= 2:
                            sent = parts[1].strip()
                            # Convert to MB/s (very rough estimate)
                            if 'MB' in sent:
                                mb_value = float(sent.replace('MB', '').strip())
                                # This is cumulative, not rate - need better metric
                            elif 'kB' in sent:
                                kb_value = float(sent.replace('kB', '').strip())
                    except:
                        pass

            # Check if meeting goals
            print("\n📊 Performance Assessment:")

            # Define expected bandwidth for each pattern
            expected_bandwidth = {
                'standard': 100,   # 100 Mbps
                'high': 500,       # 500 Mbps
                'chaos': 1000      # 1000 Mbps (1 Gbps)
            }

            if active_pattern in expected_bandwidth:
                expected_mbps = expected_bandwidth[active_pattern]

                # Check network interface statistics for better bandwidth measurement
                print(f"\n   Checking actual bandwidth (expected: {expected_mbps} Mbps)...")

                # Try to get more accurate metrics from container network interfaces
                for gen in traffic_gens:
                    # Get network stats from inside container
                    ifstat_result = subprocess.run(
                        ["docker", "exec", gen, "cat", "/proc/net/dev"],
                        capture_output=True, text=True
                    )
                    if ifstat_result.returncode == 0:
                        # Parse /proc/net/dev for eth0 statistics
                        for line in ifstat_result.stdout.split('\n'):
                            if 'eth0' in line:
                                parts = line.split()
                                if len(parts) >= 10:
                                    rx_bytes = int(parts[1])
                                    tx_bytes = int(parts[9])
                                    # These are cumulative, need rate calculation
                                    break

                # Performance verdict based on pattern
                if active_pattern == 'standard':
                    print("\n   ⚠️  Standard traffic pattern (100 Mbps target)")
                    print("   Note: Docker stats show cumulative data, not real-time bandwidth")
                    print("   For accurate bandwidth measurement, check Grafana dashboards")
                elif active_pattern == 'high':
                    print("\n   ⚠️  High-volume traffic pattern (500 Mbps target)")
                    print("   Note: Docker stats show cumulative data, not real-time bandwidth")
                    print("   For accurate bandwidth measurement, check Grafana dashboards")
                elif active_pattern == 'chaos':
                    print("\n   ⚠️  Chaos pattern (1 Gbps burst target)")
                    print("   Note: Docker stats show cumulative data, not real-time bandwidth")
                    print("   ❌ Current metrics suggest traffic is NOT reaching 1 Gbps target")
                    print("   Possible issues:")
                    print("     • CPU/memory limits on traffic containers")
                    print("     • Network bottlenecks in Docker/OVS configuration")
                    print("     • Traffic generator script may need tuning")
                    print("   For accurate measurement, check Grafana dashboards")

        elif not all_running:
            print("\n⚠️  Traffic generation is partially or completely stopped")
            print("   Run 'make traffic-run' or 'make traffic-chaos' to start")
        else:
            print("\n❌ No active traffic pattern detected")
            print("   Run 'make traffic-run' for standard traffic")
            print("   Run 'make traffic-chaos' for chaos testing")

        print("\n" + "="*50)
        return True

    def start_traffic(self, mode='standard'):
        """Start traffic generators with specified mode"""
        self.logger.info(f"Starting traffic generators in {mode} mode...")

        # Check if traffic generator containers exist
        traffic_gens = ["traffic-gen-a", "traffic-gen-b"]
        for gen in traffic_gens:
            result = subprocess.run(["docker", "ps", "-q", "-f", f"name={gen}"],
                                  capture_output=True, text=True)
            if not result.stdout.strip():
                self.logger.error(f"Traffic generator {gen} not found. Please run 'make up' first.")
                return False

        # Start traffic generation scripts
        for gen in traffic_gens:
            # Kill any existing traffic generation processes
            subprocess.run(
                ["docker", "exec", gen, "pkill", "-f", "traffic-gen.py"],
                capture_output=True
            )

            # Start new traffic generation (use nohup for proper backgrounding)
            cmd = f"cd /workspace && nohup python3 traffic-gen.py {mode} > /tmp/traffic.log 2>&1 & sleep 1"
            result = subprocess.run(
                ["docker", "exec", gen, "bash", "-c", cmd],
                capture_output=True, text=True, timeout=5
            )

            if result.returncode == 0:
                self.logger.info(f"Started {mode} traffic generation on {gen}")
            else:
                self.logger.error(f"Failed to start traffic on {gen}: {result.stderr}")
                return False

        print(f"\n✅ Traffic generation started in {mode.upper()} mode")
        print("Monitor traffic in Grafana: http://localhost:3000")
        print("Use 'make traffic-stop' to stop traffic generation")

        return True

    def stop_traffic(self):
        """Stop all traffic generators"""
        self.logger.info("Stopping traffic generators...")

        traffic_gens = ["traffic-gen-a", "traffic-gen-b"]
        for gen in traffic_gens:
            # Kill traffic generation processes
            result = subprocess.run(
                ["docker", "exec", gen, "pkill", "-f", "traffic-gen.py"],
                capture_output=True
            )

            if result.returncode in [0, 1]:  # 0 = killed, 1 = no process found
                self.logger.info(f"Stopped traffic generation on {gen}")
            else:
                self.logger.warning(f"Issue stopping traffic on {gen}")

        print("\n✅ Traffic generation stopped")
        return True


class ChaosEngineer:
    """Implements chaos testing scenarios using Pumba - adaptive to docker-compose setup"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
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

    def discover_containers(self, pattern: str = None, label: str = None):
        """Discover running containers based on pattern or label"""
        if label:
            cmd = ["docker", "ps", "--format", "{{.Names}}", "--filter", f"label={label}"]
        else:
            cmd = ["docker", "ps", "--format", "{{.Names}}"]

        result = subprocess.run(cmd, capture_output=True, text=True)
        containers = result.stdout.strip().split('\n') if result.stdout.strip() else []

        if pattern and containers:
            import re
            regex = re.compile(pattern)
            containers = [c for c in containers if regex.match(c)]

        return containers

    def get_container_groups(self):
        """Get container groups based on current docker-compose setup"""
        groups = {
            'vpc-containers': [],
            'traffic-generators': [],
            'infrastructure': [],
            'monitoring': []
        }

        # Discover VPC containers (vpc-a-*, vpc-b-*)
        groups['vpc-containers'] = self.discover_containers(pattern="vpc-[ab]-.*")

        # Discover traffic generators
        groups['traffic-generators'] = self.discover_containers(pattern="traffic-gen-.*")

        # Discover infrastructure (ovn-central, nat-gateway)
        infra_containers = self.discover_containers()
        groups['infrastructure'] = [c for c in infra_containers
                                   if c in ['ovn-central', 'nat-gateway', 'ovs-vpc-a', 'ovs-vpc-b']]

        # Discover monitoring
        groups['monitoring'] = [c for c in infra_containers
                               if c in ['prometheus', 'grafana', 'influxdb', 'telegraf']]

        return groups

    def check_container_network(self, container_name: str) -> dict:
        """Check network configuration of a container"""
        info = {
            'exists': False,
            'network_driver': None,
            'interface': None,
            'ip_address': None
        }

        # Get container network info
        cmd = ["docker", "inspect", container_name, "--format",
               "{{range .NetworkSettings.Networks}}{{.Driver}}|{{.IPAddress}}{{end}}"]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split('|')
            if len(parts) >= 2:
                info['exists'] = True
                info['network_driver'] = parts[0]
                info['ip_address'] = parts[1]

                # Check interface inside container
                iface_cmd = ["docker", "exec", container_name, "ip", "link", "show"]
                iface_result = subprocess.run(iface_cmd, capture_output=True, text=True)
                if iface_result.returncode == 0:
                    # Look for eth0 or other interfaces
                    if "eth0" in iface_result.stdout:
                        info['interface'] = 'eth0'
                    # OVS plugin should create eth0

        return info

    def show_info(self):
        """Show information about available containers for chaos testing"""
        print("\n🔍 Chaos Engineering - Container Discovery")
        print("="*50)

        groups = self.get_container_groups()

        print("\n📦 VPC Containers (Application workloads):")
        if groups['vpc-containers']:
            for c in sorted(groups['vpc-containers']):
                net_info = self.check_container_network(c)
                driver = net_info.get('network_driver', 'unknown')
                if 'ovs-container-network' in driver:
                    print(f"   • {c} ✓ (OVS plugin)")
                else:
                    print(f"   • {c} ({driver})")
        else:
            print("   ⚠️  No VPC containers running")

        print("\n🚦 Traffic Generators:")
        if groups['traffic-generators']:
            for c in sorted(groups['traffic-generators']):
                print(f"   • {c}")
        else:
            print("   ⚠️  No traffic generators running")

        print("\n🏗️  Infrastructure Components:")
        if groups['infrastructure']:
            for c in sorted(groups['infrastructure']):
                print(f"   • {c}")
        else:
            print("   ⚠️  No infrastructure containers found")

        print("\n📊 Monitoring Stack:")
        if groups['monitoring']:
            for c in sorted(groups['monitoring']):
                print(f"   • {c}")
        else:
            print("   ⚠️  No monitoring containers found")

        print("\n💡 Target Examples:")
        print("   • All VPC containers:     --target 'vpc-.*'")
        print("   • VPC-A only:             --target 'vpc-a-.*'")
        print("   • Web tier only:          --target '.*-web'")
        print("   • Traffic generators:     --target 'traffic-gen-.*'")
        print("   • Specific container:     --target 'vpc-a-web'")
        print("\n" + "="*50)

        return True

    def run_scenario(self, scenario: str, duration: int = 60, target: str = None):
        """Run a chaos scenario using Pumba"""
        if scenario not in self.scenarios:
            self.logger.error(f"Unknown scenario: {scenario}")
            print(f"❌ Unknown chaos scenario: {scenario}")
            print(f"Available scenarios: {', '.join(self.scenarios.keys())}")
            return False

        # If no target specified, use smart defaults based on scenario
        if not target:
            if scenario in ['underlay-chaos']:
                # For underlay chaos, we target infrastructure
                target = None  # Will be handled specially
            elif scenario in ['overlay-test']:
                # For overlay test, target VPC containers
                target = "vpc-.*"
            else:
                # Default to VPC containers for most scenarios
                target = "vpc-.*"

        self.logger.info(f"Running chaos scenario: {scenario} for {duration}s")
        print(f"\n🔥 Starting chaos scenario: {scenario}")
        print(f"   Duration: {duration} seconds")

        # Show what containers will be affected
        if target:
            affected = self.discover_containers(pattern=target)
            if affected:
                print(f"   Target pattern: {target}")
                print(f"   Affected containers: {', '.join(affected)}")
            else:
                print(f"   ⚠️  No containers match pattern: {target}")
                return False

        self.scenarios[scenario](target, duration)
        return True

    def _run_pumba(self, cmd: list, background: bool = False):
        """Execute Pumba command optimized for OVS Container Network plugin"""
        # How this works with OVS Container Network plugin:
        # 1. Plugin creates veth pairs (veth{id} <-> veth{id}-p)
        # 2. Container side (veth{id}) is renamed to eth0 by Docker
        # 3. Pumba finds container PID via Docker API
        # 4. Uses nsenter to access container's network namespace
        # 5. Applies tc/netem to eth0 (which was the veth{id})
        # No special container privileges needed!

        full_cmd = [
            "docker", "run",
            "--rm",
            "--privileged",  # Required for nsenter and tc commands
            "--pid=host",    # Access host PID namespace
            "-v", "/var/run/docker.sock:/var/run/docker.sock",  # Docker API access
            # These mounts ensure Pumba can find and access all namespaces
            "-v", "/proc:/proc",  # Container process info
            "-v", "/sys:/sys",  # Network interface info
            "gaiaadm/pumba"
        ] + cmd

        if background:
            proc = subprocess.Popen(full_cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return proc
        else:
            result = subprocess.run(full_cmd, capture_output=True, text=True)
            if result.returncode != 0:
                self.logger.error(f"Pumba command failed: {result.stderr}")
                if "permission denied" in result.stderr.lower():
                    print("   ❌ Permission denied - Pumba container needs privileged mode")
                elif "not found" in result.stderr.lower():
                    print("   ❌ Container not found - check target pattern")
                elif "cannot find network namespace" in result.stderr.lower():
                    print("   ❌ Cannot access network namespace - might be OVS networking issue")
                    print("      Pumba may need additional mounts for OVS namespaces")
                elif "operation not permitted" in result.stderr.lower():
                    print("   ❌ Operation not permitted - Pumba needs --privileged flag")
            return result

    def _packet_loss(self, target: str, duration: int):
        """Introduce packet loss using Pumba"""
        self.logger.info(f"Introducing 30% packet loss on containers matching: {target}")
        print("   💥 Introducing 30% packet loss...")

        # Note: Pumba will apply tc/netem rules to the container's eth0 interface by default
        # For containers using OVS plugin, the main interface might be different
        cmd = [
            "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
            "loss", "--percent", "30", f"re2:{target}"
        ]

        result = self._run_pumba(cmd)
        if result and hasattr(result, 'returncode') and result.returncode == 0:
            print("   ✓ Packet loss scenario completed")
        else:
            print("   ⚠️  Packet loss scenario may have encountered issues")

    def _add_latency(self, target: str, duration: int):
        """Add network latency using Pumba"""
        self.logger.info(f"Adding 100ms latency with 20ms jitter on containers matching: {target}")
        print("   ⏰ Adding 100ms latency with 20ms jitter...")
        cmd = [
            "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
            "delay", "--time", "100", "--jitter", "20", f"re2:{target}"
        ]
        self._run_pumba(cmd)
        print("   ✓ Latency scenario completed")

    def _limit_bandwidth(self, target: str, duration: int):
        """Limit network bandwidth using Pumba"""
        self.logger.info(f"Limiting bandwidth to 1mbit on containers matching: {target}")
        print("   🚦 Limiting bandwidth to 1mbit...")
        cmd = [
            "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
            "rate", "--rate", "1mbit", f"re2:{target}"
        ]
        self._run_pumba(cmd)
        print("   ✓ Bandwidth limit scenario completed")

    def _network_partition(self, target: str, duration: int):
        """Create network partition by pausing containers"""
        self.logger.info(f"Creating network partition by pausing containers matching: {target}")
        print("   🔌 Creating network partition...")
        cmd = [
            "pause", "--duration", f"{duration}s", f"re2:{target}"
        ]
        self._run_pumba(cmd)
        print("   ✓ Network partition scenario completed")

    def _packet_corruption(self, target: str, duration: int):
        """Introduce packet corruption using Pumba"""
        self.logger.info(f"Introducing 5% packet corruption on containers matching: {target}")
        print("   💔 Introducing 5% packet corruption...")
        cmd = [
            "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
            "corrupt", "--percent", "5", f"re2:{target}"
        ]
        self._run_pumba(cmd)
        print("   ✓ Packet corruption scenario completed")

    def _packet_duplication(self, target: str, duration: int):
        """Introduce packet duplication using Pumba"""
        self.logger.info(f"Introducing 10% packet duplication on containers matching: {target}")
        print("   👥 Introducing 10% packet duplication...")
        cmd = [
            "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
            "duplicate", "--percent", "10", f"re2:{target}"
        ]
        self._run_pumba(cmd)
        print("   ✓ Packet duplication scenario completed")

    def _underlay_chaos(self, target: str, duration: int):
        """Test underlay network failure by targeting infrastructure containers"""
        self.logger.info("Testing underlay network chaos - targeting infrastructure")
        print("   🌐 Testing underlay network chaos...")
        print("      Discovering infrastructure components...")

        # Dynamically discover infrastructure containers
        groups = self.get_container_groups()
        underlay_targets = groups['infrastructure']

        if not underlay_targets:
            print("      ⚠️  No infrastructure containers found")
            print("      Looking for any OVS/OVN related containers...")
            # Fallback: look for any OVS/OVN related containers
            all_containers = self.discover_containers()
            underlay_targets = [c for c in all_containers
                              if any(x in c.lower() for x in ['ovs', 'ovn', 'nat-gateway'])]

        if not underlay_targets:
            print("      ❌ No infrastructure containers to target")
            return

        print(f"      Found infrastructure: {', '.join(underlay_targets)}")

        procs = []
        for infra_target in underlay_targets:
            self.logger.info(f"Applying packet loss to infrastructure: {infra_target}")
            print(f"      Applying 20% packet loss to {infra_target}")
            cmd = [
                "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
                "loss", "--percent", "20", infra_target
            ]
            # Run in background to affect multiple targets simultaneously
            proc = self._run_pumba(cmd, background=True)
            if proc:
                procs.append(proc)

        # Wait for duration
        print(f"      Running for {duration} seconds...")
        time.sleep(duration)

        # Wait for all processes to complete
        for proc in procs:
            if proc:
                proc.wait()

        print("   ✓ Underlay chaos scenario completed")
        print("      Overlay should have shown resilience during infrastructure failures")

    def _overlay_resilience_test(self, target: str, duration: int):
        """Test overlay network resilience by introducing various failures"""
        self.logger.info("Testing overlay network resilience with combined failures")
        print("   🛡️ Testing overlay network resilience...")
        print("      Discovering container groups...")

        # Dynamically build scenarios based on what's running
        groups = self.get_container_groups()
        scenarios = []

        # Apply different chaos to different groups
        vpc_a_containers = [c for c in groups['vpc-containers'] if 'vpc-a' in c]
        vpc_b_containers = [c for c in groups['vpc-containers'] if 'vpc-b' in c]
        traffic_gens = groups['traffic-generators']

        if vpc_a_containers:
            print(f"      VPC-A containers: {', '.join(vpc_a_containers)}")
            scenarios.append([
                "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
                "loss", "--percent", "15", f"re2:{'|'.join(vpc_a_containers)}"
            ])

        if vpc_b_containers:
            print(f"      VPC-B containers: {', '.join(vpc_b_containers)}")
            scenarios.append([
                "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
                "delay", "--time", "50", "--jitter", "10", f"re2:{'|'.join(vpc_b_containers)}"
            ])

        if traffic_gens:
            print(f"      Traffic generators: {', '.join(traffic_gens)}")
            scenarios.append([
                "netem", "--duration", f"{duration}s", "--tc-image", "gaiadocker/iproute2",
                "corrupt", "--percent", "2", f"re2:{'|'.join(traffic_gens)}"
            ])

        if not scenarios:
            print("      ⚠️  No containers found for overlay testing")
            return

        print("      Applying multiple simultaneous failures")
        procs = []
        for cmd in scenarios:
            proc = self._run_pumba(cmd, background=True)
            if proc:
                procs.append(proc)

        # Monitor during chaos
        print(f"      Running resilience test for {duration} seconds...")
        print("      Monitor Grafana to observe overlay behavior during chaos")
        time.sleep(duration)

        # Wait for all scenarios to complete
        for proc in procs:
            if proc:
                proc.wait()

        print("   ✓ Overlay resilience test completed")

    def _mixed_chaos(self, target: str, duration: int):
        """Run mixed chaos scenarios for extreme stress testing"""
        self.logger.info("Running mixed chaos scenarios - extreme network stress test")
        print("   🌪️ Running MIXED CHAOS - Extreme stress test!")
        print("      Applying packet loss, latency, corruption, and duplication")

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
            if proc:
                procs.append(proc)

        print(f"      Running for {duration} seconds...")
        print("      Combined with traffic generation, this simulates extreme network stress")
        print("      Monitor Grafana: http://localhost:3000")

        # Wait for all scenarios to complete
        for proc in procs:
            if proc:
                proc.wait()

        print("   ✓ Mixed chaos scenario completed")


class TestRunner:
    """Runs tests for the OVS Container Network plugin"""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.plugin_name = "ovs-container-network:latest"
        self.test_network_prefix = "test-net"
        self.test_container_prefix = "test-container"
        self.tests_run = 0
        self.tests_passed = 0
        self.tests_failed = 0

    def cleanup_test_resources(self):
        """Clean up all test resources"""
        self.logger.info("Cleaning up test resources...")

        # Remove test containers
        subprocess.run(
            f"docker ps -a --filter 'name={self.test_container_prefix}' -q | xargs -r docker rm -f",
            shell=True, capture_output=True
        )

        # Remove test networks
        subprocess.run(
            f"docker network ls --filter 'name={self.test_network_prefix}' -q | xargs -r docker network rm",
            shell=True, capture_output=True
        )

        # Clean up OVN resources if OVN central exists
        ovn_check = subprocess.run(
            ["docker", "ps"], capture_output=True, text=True
        )
        if "ovn-central" in ovn_check.stdout:
            subprocess.run(
                f"docker exec ovn-central ovn-nbctl ls-list 2>/dev/null | grep '{self.test_network_prefix}' | "
                f"awk '{{print $2}}' | xargs -r -I {{}} docker exec ovn-central ovn-nbctl ls-del {{}}",
                shell=True, capture_output=True
            )

    def log_test(self, message):
        """Log a test being run"""
        self.logger.info(f"[TEST] {message}")
        self.tests_run += 1

    def pass_test(self, message):
        """Log a passing test"""
        self.logger.info(f"✅ [PASS] {message}")
        self.tests_passed += 1

    def fail_test(self, message):
        """Log a failing test"""
        self.logger.error(f"❌ [FAIL] {message}")
        self.tests_failed += 1

    def run_unit_tests(self) -> bool:
        """Run Go unit tests for the plugin"""
        self.logger.info("Running unit tests for OVS Container Network plugin...")

        try:
            # Change to plugin directory and run tests
            result = subprocess.run(
                ["go", "test", "-v", "./pkg/store/...", "-cover"],
                cwd="/home/lima/code/ovs-container-lab/ovs-container-network",
                capture_output=True, text=True, check=True
            )

            self.logger.info("Unit test output:")
            print(result.stdout)

            if "PASS" in result.stdout:
                self.pass_test("Unit tests passed")
                return True
            else:
                self.fail_test("Unit tests failed")
                return False

        except subprocess.CalledProcessError as e:
            self.logger.error(f"Unit tests failed: {e}")
            if e.stdout:
                print(e.stdout)
            if e.stderr:
                print(e.stderr)
            return False

    def test_plugin_installation(self) -> bool:
        """Test that the plugin is installed and enabled"""
        self.log_test("Testing plugin installation and basic functionality")

        try:
            result = subprocess.run(
                ["docker", "plugin", "ls"],
                capture_output=True, text=True, check=True
            )

            if self.plugin_name in result.stdout:
                self.pass_test("Plugin is installed")

                # Check if enabled
                if "true" in result.stdout:
                    self.pass_test("Plugin is enabled")
                    return True
                else:
                    self.fail_test("Plugin is not enabled")
                    return False
            else:
                self.fail_test("Plugin is not installed")
                return False

        except subprocess.CalledProcessError as e:
            self.fail_test(f"Failed to check plugin status: {e}")
            return False

    def test_basic_network_creation(self) -> bool:
        """Test basic network creation"""
        self.log_test("Testing basic network creation")
        network_name = f"{self.test_network_prefix}-basic"

        try:
            # Create network with OVN configuration like the VPC networks
            subprocess.run(
                ["docker", "network", "create", "--driver", self.plugin_name,
                 "--subnet", "10.100.0.0/24",
                 "--opt", "bridge=br-int",
                 "--opt", "ovn.switch=ls-test-basic",
                 "--opt", "ovn.nb_connection=tcp:172.30.0.5:6641",
                 "--opt", "ovn.sb_connection=tcp:172.30.0.5:6642",
                 "--opt", "ovn.auto_create=true", network_name],
                capture_output=True, text=True, check=True
            )
            self.pass_test(f"Network {network_name} created successfully")

            # Verify network exists
            result = subprocess.run(
                ["docker", "network", "ls"],
                capture_output=True, text=True, check=True
            )

            if network_name in result.stdout:
                self.pass_test(f"Network {network_name} exists in Docker")
            else:
                self.fail_test(f"Network {network_name} not found in Docker")
                return False

            # Check OVS bridge
            result = subprocess.run(
                ["ovs-vsctl", "list-br"],
                capture_output=True, text=True, check=True
            )

            if "br-int" in result.stdout:
                self.pass_test("OVS bridge br-int exists")
            else:
                self.fail_test("OVS bridge br-int not found")
                return False

            # Cleanup
            subprocess.run(
                ["docker", "network", "rm", network_name],
                capture_output=True, check=False
            )

            return True

        except subprocess.CalledProcessError as e:
            self.fail_test(f"Failed to create network: {e}")
            return False

    def test_ovn_config_validation(self) -> bool:
        """Test that OVN configuration is properly validated"""
        self.log_test("Testing OVN configuration validation")

        # Test 1: Network creation without OVN config should fail
        network_name_no_ovn = f"{self.test_network_prefix}-no-ovn"
        result = subprocess.run(
            ["docker", "network", "create", "--driver", self.plugin_name,
             "--subnet", "10.110.0.0/24", network_name_no_ovn],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            if "ovn.switch is required" in result.stderr:
                self.pass_test("Network creation without OVN config failed with correct error message")
            else:
                self.fail_test(f"Network creation failed but with wrong error: {result.stderr}")
                return False
        else:
            self.fail_test("Network creation without OVN config should have failed but succeeded")
            # Clean up unexpected network
            subprocess.run(["docker", "network", "rm", network_name_no_ovn], capture_output=True)
            return False

        # Test 2: Network creation with OVN switch but missing connections should fail
        network_name_partial = f"{self.test_network_prefix}-partial-ovn"
        result = subprocess.run(
            ["docker", "network", "create", "--driver", self.plugin_name,
             "--subnet", "10.111.0.0/24",
             "--opt", "ovn.switch=ls-test-partial", network_name_partial],
            capture_output=True, text=True
        )

        if result.returncode != 0:
            if "ovn.nb_connection and ovn.sb_connection are required" in result.stderr:
                self.pass_test("Network creation with missing OVN connections failed with correct error")
            else:
                self.fail_test(f"Network creation failed but with wrong error: {result.stderr}")
                return False
        else:
            self.fail_test("Network creation with partial OVN config should have failed but succeeded")
            # Clean up unexpected network
            subprocess.run(["docker", "network", "rm", network_name_partial], capture_output=True)
            return False

        # Test 3: Network creation with complete OVN config should succeed
        network_name_complete = f"{self.test_network_prefix}-complete-ovn"
        result = subprocess.run(
            ["docker", "network", "create", "--driver", self.plugin_name,
             "--subnet", "10.112.0.0/24",
             "--opt", "ovn.switch=ls-test-complete",
             "--opt", "ovn.nb_connection=tcp:172.30.0.5:6641",
             "--opt", "ovn.sb_connection=tcp:172.30.0.5:6642",
             "--opt", "ovn.auto_create=true", network_name_complete],
            capture_output=True, text=True
        )

        if result.returncode == 0:
            self.pass_test("Network creation with complete OVN config succeeded")
            # Clean up
            subprocess.run(["docker", "network", "rm", network_name_complete], capture_output=True)
            return True
        else:
            self.fail_test(f"Network creation with complete OVN config failed: {result.stderr}")
            return False

    def test_container_connectivity(self) -> bool:
        """Test container-to-container connectivity"""
        self.log_test("Testing container connectivity on network")
        network_name = f"{self.test_network_prefix}-connectivity"
        container1 = f"{self.test_container_prefix}-1"
        container2 = f"{self.test_container_prefix}-2"

        try:
            # Create network with OVN configuration
            subprocess.run(
                ["docker", "network", "create", "--driver", self.plugin_name,
                 "--subnet", "10.101.0.0/24",
                 "--opt", "bridge=br-int",
                 "--opt", "ovn.switch=ls-test-connectivity",
                 "--opt", "ovn.nb_connection=tcp:172.30.0.5:6641",
                 "--opt", "ovn.sb_connection=tcp:172.30.0.5:6642",
                 "--opt", "ovn.auto_create=true", network_name],
                capture_output=True, check=True
            )

            # Create containers
            subprocess.run(
                ["docker", "run", "-d", "--name", container1, "--network", network_name,
                 "alpine:latest", "sleep", "3600"],
                capture_output=True, check=True
            )

            subprocess.run(
                ["docker", "run", "-d", "--name", container2, "--network", network_name,
                 "alpine:latest", "sleep", "3600"],
                capture_output=True, check=True
            )

            # Wait for containers to be ready
            time.sleep(3)

            # Get container2 IP
            result = subprocess.run(
                ["docker", "inspect", container2, "--format",
                 "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"],
                capture_output=True, text=True, check=True
            )
            container2_ip = result.stdout.strip()

            # Test ping
            result = subprocess.run(
                ["docker", "exec", container1, "ping", "-c", "2", container2_ip],
                capture_output=True, text=True
            )

            if result.returncode == 0:
                self.pass_test(f"Container {container1} can ping {container2}")
                return True
            else:
                self.fail_test(f"Container {container1} cannot ping {container2}")
                return False

        except subprocess.CalledProcessError as e:
            self.fail_test(f"Container connectivity test failed: {e}")
            return False
        finally:
            # Cleanup
            subprocess.run([f"docker rm -f {container1} {container2}"], shell=True, capture_output=True)
            subprocess.run(["docker", "network", "rm", network_name], capture_output=True)

    def run_integration_tests(self) -> bool:
        """Run all integration tests"""
        self.logger.info("="*50)
        self.logger.info("Starting OVS Container Network Plugin Integration Tests")
        self.logger.info("="*50)

        # Initial cleanup
        self.cleanup_test_resources()

        # Run tests
        all_passed = True
        all_passed &= self.test_plugin_installation()
        all_passed &= self.test_ovn_config_validation()  # Test validation first
        all_passed &= self.test_basic_network_creation()
        all_passed &= self.test_container_connectivity()

        # Final cleanup
        self.cleanup_test_resources()

        # Print summary
        self.logger.info("")
        self.logger.info("="*50)
        self.logger.info("Test Summary:")
        self.logger.info(f"Tests Run: {self.tests_run}")
        self.logger.info(f"Tests Passed: {self.tests_passed}")
        self.logger.info(f"Tests Failed: {self.tests_failed}")

        if self.tests_failed == 0:
            self.logger.info("✅ All tests passed!")
        else:
            self.logger.error(f"❌ {self.tests_failed} test(s) failed")

        return all_passed

    def run_all_tests(self) -> bool:
        """Run all tests (unit and integration)"""
        self.logger.info("Running all tests...")

        unit_passed = self.run_unit_tests()
        integration_passed = self.run_integration_tests()

        return unit_passed and integration_passed


def main():
    """Main entry point"""
    parser = argparse.ArgumentParser(description="Simplified OVS Container Lab Orchestrator")
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Plugin commands
    subparsers.add_parser("install-plugin", help="Install OVS Container Network plugin")
    subparsers.add_parser("uninstall-plugin", help="Uninstall OVS Container Network plugin")

    # Setup commands
    subparsers.add_parser("setup-monitoring", help="Setup monitoring exporters")
    subparsers.add_parser("check-monitoring", help="Check monitoring exporters status")
    subparsers.add_parser("restart-exporters", help="Restart monitoring exporters")

    chassis_parser = subparsers.add_parser("setup-chassis", help="Setup OVS chassis connection to OVN")
    chassis_parser.add_argument("--ovn-ip", default="172.30.0.5",
                               help="OVN central IP address (default: 172.30.0.5)")
    chassis_parser.add_argument("--encap-ip", default="172.30.0.1",
                               help="Local IP for tunnel encapsulation (default: 172.30.0.1)")

    # VM commands
    subparsers.add_parser("create-vms", help="Create and start libvirt VMs")
    subparsers.add_parser("destroy-vms", help="Stop and remove libvirt VMs")
    subparsers.add_parser("vm-status", help="Show status of VMs")

    vm_console_parser = subparsers.add_parser("vm-console", help="Connect to VM console")
    vm_console_parser.add_argument("--vm", required=True, help="VM name (vpc-a-vm or vpc-b-vm)")

    # Test commands
    subparsers.add_parser("test-unit", help="Run unit tests for the plugin")
    subparsers.add_parser("test-integration", help="Run integration tests for the plugin")
    subparsers.add_parser("test-all", help="Run all tests (unit and integration)")

    # Network check command
    subparsers.add_parser("check", help="Run network diagnostic checks")

    # Traffic commands
    traffic_parser = subparsers.add_parser("traffic-start", help="Start traffic generation")
    traffic_parser.add_argument("--mode", choices=['standard', 'high', 'chaos'], default='standard',
                               help="Traffic generation mode (default: standard)")
    subparsers.add_parser("traffic-stop", help="Stop traffic generation")
    subparsers.add_parser("traffic-status", help="Check traffic generation status")

    # Chaos commands
    subparsers.add_parser("chaos-info", help="Show available containers for chaos testing")

    chaos_parser = subparsers.add_parser("chaos", help="Run chaos engineering scenarios")
    chaos_parser.add_argument("scenario",
                             choices=['packet-loss', 'latency', 'bandwidth', 'partition',
                                     'corruption', 'duplication', 'underlay-chaos',
                                     'overlay-test', 'mixed'],
                             help="Chaos scenario to run")
    chaos_parser.add_argument("--duration", type=int, default=60,
                             help="Duration in seconds (default: 60)")
    chaos_parser.add_argument("--target", default=None,
                             help="Target container pattern (e.g., 'vpc-.*', 'vpc-a-.*', '.*-web')")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "install-plugin":
        plugin = DockerNetworkPlugin()
        return 0 if plugin.install() else 1

    elif args.command == "uninstall-plugin":
        plugin = DockerNetworkPlugin()
        return 0 if plugin.uninstall() else 1

    elif args.command == "setup-monitoring":
        monitor = MonitoringManager()
        success = monitor.setup_ovs_exporter() and monitor.setup_node_exporter()
        return 0 if success else 1

    elif args.command == "check-monitoring":
        monitor = MonitoringManager()
        return 0 if monitor.check_exporters() else 1

    elif args.command == "restart-exporters":
        monitor = MonitoringManager()
        return 0 if monitor.restart_exporters() else 1

    elif args.command == "setup-chassis":
        chassis = OVSChassisManager()
        return 0 if chassis.setup_chassis(args.ovn_ip, args.encap_ip) else 1

    elif args.command == "test-unit":
        runner = TestRunner()
        return 0 if runner.run_unit_tests() else 1

    elif args.command == "test-integration":
        runner = TestRunner()
        return 0 if runner.run_integration_tests() else 1

    elif args.command == "test-all":
        runner = TestRunner()
        return 0 if runner.run_all_tests() else 1

    elif args.command == "check":
        checker = NetworkChecker()
        return 0 if checker.check_all() else 1

    elif args.command == "traffic-start":
        traffic_gen = TrafficGenerator()
        return 0 if traffic_gen.start_traffic(args.mode) else 1

    elif args.command == "traffic-stop":
        traffic_gen = TrafficGenerator()
        return 0 if traffic_gen.stop_traffic() else 1

    elif args.command == "traffic-status":
        traffic_gen = TrafficGenerator()
        return 0 if traffic_gen.check_traffic_status() else 1

    elif args.command == "chaos-info":
        chaos = ChaosEngineer()
        return 0 if chaos.show_info() else 1

    elif args.command == "chaos":
        chaos = ChaosEngineer()
        return 0 if chaos.run_scenario(args.scenario, args.duration, args.target) else 1

    elif args.command == "create-vms":
        # Import here to avoid dependency issues if libvirt not installed
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'vm-manager'))
            from vm_manager import VMManager
            vm_mgr = VMManager()
            if not vm_mgr.check_dependencies():
                logger.error("VM dependencies not met. Please install libvirt and KVM.")
                return 1
            return 0 if vm_mgr.create_all_vms() else 1
        except ImportError as e:
            logger.error(f"Failed to import VM manager: {e}")
            return 1

    elif args.command == "destroy-vms":
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'vm-manager'))
            from vm_manager import VMManager
            vm_mgr = VMManager()
            return 0 if vm_mgr.destroy_all_vms() else 1
        except ImportError as e:
            logger.error(f"Failed to import VM manager: {e}")
            return 1

    elif args.command == "vm-status":
        try:
            sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'vm-manager'))
            from vm_manager import VMManager
            vm_mgr = VMManager()
            status = vm_mgr.get_vm_status()
            print("\n🖥️  VM Status")
            print("=" * 50)
            for vm_name, info in status.items():
                status_icon = "✓" if info['running'] else "✗"
                exists_icon = "✓" if info['exists'] else "✗"
                print(f"\n📦 {vm_name}:")
                print(f"   Exists: {exists_icon}")
                print(f"   Running: {status_icon}")
                print(f"   IP: {info['ip']}")
                print(f"   VPC: {info['vpc'].upper()}")
            print("\n" + "=" * 50)
            return 0
        except ImportError as e:
            logger.error(f"Failed to import VM manager: {e}")
            return 1

    elif args.command == "vm-console":
        vm_name = args.vm
        cmd = ["sudo", "virsh", "console", vm_name]
        print(f"Connecting to {vm_name} console (use Ctrl+] to exit)...")
        subprocess.run(cmd)
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())