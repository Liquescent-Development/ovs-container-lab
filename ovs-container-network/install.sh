#!/bin/bash

set -e

PLUGIN_NAME="ovs-container-network"
PLUGIN_TAG="${PLUGIN_TAG:-latest}"
PLUGIN_IMAGE="${PLUGIN_NAME}:${PLUGIN_TAG}"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

echo_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

echo_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check prerequisites
check_prerequisites() {
    echo_info "Checking prerequisites..."

    # Check if running as root
    if [[ $EUID -ne 0 ]]; then
        echo_error "This script must be run as root"
        exit 1
    fi

    # Check if Docker is installed
    if ! command -v docker &> /dev/null; then
        echo_error "Docker is not installed"
        exit 1
    fi

    # Check if OVS is installed
    if ! command -v ovs-vsctl &> /dev/null; then
        echo_error "Open vSwitch is not installed"
        echo "Please install it with:"
        echo "  Ubuntu/Debian: apt-get install openvswitch-switch"
        echo "  RHEL/CentOS: yum install openvswitch"
        exit 1
    fi

    # Check if OVS is running
    if ! ovs-vsctl show &> /dev/null; then
        echo_error "Open vSwitch is not running"
        echo "Please start it with: systemctl start openvswitch-switch"
        exit 1
    fi

    # Check if Go is installed (for building from source)
    if ! command -v go &> /dev/null; then
        echo_warn "Go is not installed - will use pre-built binary if available"
    else
        echo_info "Go version: $(go version)"
    fi

    echo_info "All prerequisites met"
}

# Create default OVS bridge
setup_ovs_bridge() {
    local bridge="${1:-br-int}"

    echo_info "Setting up OVS bridge: $bridge"

    if ovs-vsctl br-exists "$bridge" 2>/dev/null; then
        echo_info "Bridge $bridge already exists"
    else
        echo_info "Creating bridge $bridge"
        ovs-vsctl add-br "$bridge"
        ovs-vsctl set bridge "$bridge" fail-mode=secure
    fi
}

# Build the plugin
build_plugin() {
    echo_info "Building Docker plugin..."

    # Clean any previous builds
    echo_info "Cleaning previous builds..."
    make clean 2>/dev/null || true
    docker plugin rm -f "${PLUGIN_IMAGE}" 2>/dev/null || true

    # Build the Docker image
    echo_info "Building Docker image..."
    make docker-build

    # Create the plugin
    echo_info "Creating Docker plugin..."
    make plugin-create

    echo_info "Plugin built successfully"
}

# Install the plugin
install_plugin() {
    echo_info "Installing plugin ${PLUGIN_IMAGE}..."

    # Enable the plugin
    docker plugin enable "${PLUGIN_IMAGE}"

    echo_info "Plugin installed and enabled"
}

# Verify installation
verify_installation() {
    echo_info "Verifying installation..."

    # Check if plugin is installed
    if docker plugin ls | grep -q "${PLUGIN_NAME}"; then
        echo_info "Plugin is installed"
    else
        echo_error "Plugin installation failed"
        exit 1
    fi

    # Check if plugin is enabled
    if docker plugin ls | grep "${PLUGIN_NAME}" | grep -q "true"; then
        echo_info "Plugin is enabled"
    else
        echo_error "Plugin is not enabled"
        exit 1
    fi

    # Test network creation
    echo_info "Testing network creation..."
    TEST_NET="ovs-test-$$"

    if docker network create --driver "${PLUGIN_IMAGE}" \
        --subnet 172.30.0.0/24 \
        --opt bridge=br-int \
        "${TEST_NET}" 2>/dev/null; then
        echo_info "Test network created successfully"
        docker network rm "${TEST_NET}" 2>/dev/null
    else
        echo_warn "Test network creation failed - plugin may need configuration"
    fi

    echo_info "Installation verified"
}

# Print usage information
print_usage() {
    echo "OVS Container Network Plugin Installation"
    echo
    echo "This plugin provides native Docker integration with Open vSwitch (OVS)"
    echo
    echo "Usage examples:"
    echo
    echo "1. Create a basic network:"
    echo "   docker network create --driver ${PLUGIN_IMAGE} \\"
    echo "     --subnet 10.0.0.0/24 \\"
    echo "     my-ovs-network"
    echo
    echo "2. Create a VLAN network:"
    echo "   docker network create --driver ${PLUGIN_IMAGE} \\"
    echo "     --subnet 10.0.0.0/24 \\"
    echo "     --opt vlan=100 \\"
    echo "     vlan-network"
    echo
    echo "3. Create a multi-tenant network:"
    echo "   docker network create --driver ${PLUGIN_IMAGE} \\"
    echo "     --subnet 10.0.0.0/24 \\"
    echo "     --opt tenant_id=tenant-a \\"
    echo "     --opt vlan=100 \\"
    echo "     tenant-network"
    echo
    echo "4. Run a container:"
    echo "   docker run --rm -it --network my-ovs-network alpine sh"
    echo
    echo "For more information, see README.md"
}

# Main installation flow
main() {
    echo "========================================="
    echo " OVS Container Network Plugin Installer"
    echo "========================================="
    echo

    # Check prerequisites
    check_prerequisites

    # Setup OVS bridge
    setup_ovs_bridge "br-int"

    # Build the plugin
    build_plugin

    # Install the plugin
    install_plugin

    # Verify installation
    verify_installation

    echo
    echo "========================================="
    echo_info "Installation completed successfully!"
    echo "========================================="
    echo

    # Print usage information
    print_usage
}

# Run main function
main "$@"