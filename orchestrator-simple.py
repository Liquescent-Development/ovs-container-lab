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

    def setup_ovs_exporter(self) -> bool:
        """Setup OVS exporter as a systemd service"""
        logger.info("Setting up OVS exporter...")

        # Download and install ovs-exporter
        arch = subprocess.run(["uname", "-m"], capture_output=True, text=True).stdout.strip()
        if arch == "aarch64":
            arch = "arm64"
        elif arch == "x86_64":
            arch = "amd64"

        # Check if already installed
        if os.path.exists("/usr/local/bin/ovs-exporter"):
            logger.info("OVS exporter already installed")
            return True

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

        # Create systemd service
        service_content = """[Unit]
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

    chassis_parser = subparsers.add_parser("setup-chassis", help="Setup OVS chassis connection to OVN")
    chassis_parser.add_argument("--ovn-ip", default="172.30.0.5",
                               help="OVN central IP address (default: 172.30.0.5)")
    chassis_parser.add_argument("--encap-ip", default="172.30.0.1",
                               help="Local IP for tunnel encapsulation (default: 172.30.0.1)")

    # Test commands
    subparsers.add_parser("test-unit", help="Run unit tests for the plugin")
    subparsers.add_parser("test-integration", help="Run integration tests for the plugin")
    subparsers.add_parser("test-all", help="Run all tests (unit and integration)")

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

    return 0


if __name__ == "__main__":
    sys.exit(main())