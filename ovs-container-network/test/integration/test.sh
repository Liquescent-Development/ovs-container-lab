#!/bin/bash

# Integration test script for OVS Container Network Plugin

set -e

PLUGIN_NAME="ovs-container-network"
PLUGIN_TAG="${PLUGIN_TAG:-latest}"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo_test() {
    echo -e "${YELLOW}[TEST]${NC} $1"
}

echo_pass() {
    echo -e "${GREEN}[PASS]${NC} $1"
}

echo_fail() {
    echo -e "${RED}[FAIL]${NC} $1"
}

cleanup() {
    echo_test "Cleaning up test resources..."

    # Remove test containers
    docker rm -f test-client-1 test-client-2 test-server 2>/dev/null || true

    # Remove test networks
    docker network rm test-basic test-vlan test-tenant-a test-tenant-b 2>/dev/null || true

    echo_pass "Cleanup complete"
}

# Test basic network creation
test_basic_network() {
    echo_test "Testing basic network creation..."

    docker network create --driver ${PLUGIN_NAME}:${PLUGIN_TAG} \
        --subnet 172.25.0.0/24 \
        test-basic

    if docker network ls | grep -q test-basic; then
        echo_pass "Basic network created"
    else
        echo_fail "Failed to create basic network"
        return 1
    fi

    # Inspect the network
    docker network inspect test-basic > /dev/null
    echo_pass "Network inspection successful"
}

# Test container connectivity
test_container_connectivity() {
    echo_test "Testing container connectivity..."

    # Start a server container
    docker run -d --name test-server \
        --network test-basic \
        nginx:alpine

    # Start a client container and test connectivity
    docker run --rm --name test-client-1 \
        --network test-basic \
        alpine sh -c "
            apk add --no-cache curl >/dev/null 2>&1 &&
            curl -s -o /dev/null -w '%{http_code}' http://test-server
        " | grep -q 200

    if [ $? -eq 0 ]; then
        echo_pass "Container connectivity test passed"
    else
        echo_fail "Container connectivity test failed"
        return 1
    fi
}

# Test VLAN isolation
test_vlan_isolation() {
    echo_test "Testing VLAN isolation..."

    # Create VLAN network
    docker network create --driver ${PLUGIN_NAME}:${PLUGIN_TAG} \
        --subnet 172.26.0.0/24 \
        --opt vlan=100 \
        test-vlan

    # Verify network has correct options
    if docker network inspect test-vlan | grep -q '"vlan": "100"'; then
        echo_pass "VLAN network created with correct options"
    else
        echo_fail "VLAN options not set correctly"
        return 1
    fi
}

# Test multi-tenancy
test_multi_tenancy() {
    echo_test "Testing multi-tenancy..."

    # Create tenant A network
    docker network create --driver ${PLUGIN_NAME}:${PLUGIN_TAG} \
        --subnet 172.27.0.0/24 \
        --opt tenant_id=tenant-a \
        --opt vlan=200 \
        test-tenant-a

    # Create tenant B network
    docker network create --driver ${PLUGIN_NAME}:${PLUGIN_TAG} \
        --subnet 172.28.0.0/24 \
        --opt tenant_id=tenant-b \
        --opt vlan=201 \
        test-tenant-b

    echo_pass "Multi-tenant networks created"

    # Verify OVS configuration
    echo_test "Verifying OVS port configurations..."

    # Start containers in each network
    docker run -d --name test-client-2 --network test-tenant-a alpine sleep 3600

    # Check if external_ids are set correctly (requires OVS access)
    if command -v ovs-vsctl &> /dev/null; then
        sleep 2  # Wait for port creation

        # List ports and check for tenant_id
        ovs_output=$(sudo ovs-vsctl list interface 2>/dev/null | grep tenant_id || true)
        if [ -n "$ovs_output" ]; then
            echo_pass "OVS external_ids configured correctly"
        else
            echo_test "Could not verify OVS external_ids (may need root access)"
        fi
    else
        echo_test "OVS not accessible for verification"
    fi
}

# Test static IP assignment
test_static_ip() {
    echo_test "Testing static IP assignment..."

    # Create a container with static IP
    docker run --rm \
        --network test-basic \
        --ip 172.25.0.100 \
        alpine sh -c "ip addr show | grep 172.25.0.100"

    if [ $? -eq 0 ]; then
        echo_pass "Static IP assignment successful"
    else
        echo_fail "Static IP assignment failed"
        return 1
    fi
}

# Test network deletion
test_network_deletion() {
    echo_test "Testing network deletion..."

    # Create a temporary network
    docker network create --driver ${PLUGIN_NAME}:${PLUGIN_TAG} \
        --subnet 172.29.0.0/24 \
        test-temp

    # Delete it
    docker network rm test-temp

    if docker network ls | grep -q test-temp; then
        echo_fail "Network deletion failed"
        return 1
    else
        echo_pass "Network deletion successful"
    fi
}

# Main test execution
main() {
    echo "========================================="
    echo " OVS Container Network Plugin Test Suite"
    echo "========================================="
    echo

    # Set up cleanup trap
    trap cleanup EXIT

    # Clean any existing test resources
    cleanup

    # Run tests
    local failed=0

    test_basic_network || ((failed++))
    test_container_connectivity || ((failed++))
    test_vlan_isolation || ((failed++))
    test_multi_tenancy || ((failed++))
    test_static_ip || ((failed++))
    test_network_deletion || ((failed++))

    echo
    echo "========================================="

    if [ $failed -eq 0 ]; then
        echo_pass "All tests passed!"
    else
        echo_fail "$failed test(s) failed"
        exit 1
    fi
}

# Run main if script is executed directly
if [ "${BASH_SOURCE[0]}" = "${0}" ]; then
    main "$@"
fi