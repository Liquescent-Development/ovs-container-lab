# OVS Container Network Plugin Testing Guide

## Overview

This document describes the comprehensive testing framework for the OVS Container Network Plugin. The test suite leverages our Lima VM environment to provide full integration testing with real OVS/OVN infrastructure.

## Test Architecture

```
┌──────────────────────────────────────────────┐
│                Host Machine                    │
├────────────────────────────────────────────────┤
│                                                │
│    ┌────────────────────────────────────┐     │
│    │         Lima VM (ovs-lab)          │     │
│    │                                    │     │
│    │  ┌──────────────────────────────┐ │     │
│    │  │  OVS Container Network       │ │     │
│    │  │       Plugin                 │ │     │
│    │  └──────────────────────────────┘ │     │
│    │           ▲         ▲             │     │
│    │           │         │             │     │
│    │      Unit Tests  Integration      │     │
│    │                   Tests           │     │
│    └────────────────────────────────────┘     │
│                                                │
└────────────────────────────────────────────────┘
```

## Test Categories

### 1. Unit Tests
- **Location**: `ovs-container-network/pkg/*/..._test.go`
- **Coverage**: Individual package functionality
- **Execution**: Fast, no external dependencies

### 2. Integration Tests
- **Location**: `tests/integration/`
- **Coverage**: End-to-end plugin functionality
- **Execution**: Requires full Lima VM environment

### 3. Smoke Tests
- **Purpose**: Quick validation of basic functionality
- **Execution**: < 30 seconds

## Running Tests

### Prerequisites
```bash
# Ensure Lima VM is running
make up

# Verify plugin is installed
make plugin-status
```

### Quick Start
```bash
# Run all tests
make test-all

# Run specific test suites
make test-unit          # Unit tests only
make test-integration   # Integration tests only
make test-quick        # Quick smoke test
make test-persistence  # Test state persistence
make test-ovn-auto    # Test OVN auto-creation
```

### Clean Up
```bash
# Remove all test artifacts
make test-clean

# Full environment reset
make clean && make up
```

## Test Suite Details

### Unit Tests

#### Store Package Tests
```go
// Tests persistent storage functionality
TestNewStore           // Store creation
TestNetworkPersistence // Network save/load
TestEndpointPersistence // Endpoint save/load
TestStoreRecovery      // Recovery from disk
TestCorruptedStateHandling // Graceful corruption handling
TestConcurrentAccess   // Thread safety
TestIPAMDataPersistence // IPAM state preservation
```

### Integration Tests

#### Shell-Based Tests (`test_plugin.sh`)
1. **Plugin Installation** - Verifies plugin is properly installed and enabled
2. **Basic Network Creation** - Tests network lifecycle operations
3. **Container Connectivity** - Validates container-to-container communication
4. **VLAN Isolation** - Ensures VLAN separation works correctly
5. **Persistent State** - Validates state recovery after plugin restart
6. **OVN Auto-Create** - Tests automatic OVN central creation
7. **Transit Network** - Validates inter-VPC routing setup
8. **Network Deletion** - Ensures proper cleanup
9. **Concurrent Operations** - Tests parallel network creation
10. **State File Integrity** - Verifies persistence files

#### Go-Based Tests (`plugin_test.go`)
```go
TestPluginEnabled       // Plugin availability check
TestBasicNetworkLifecycle // Create/inspect/delete network
TestContainerConnectivity // Container communication
TestVLANIsolation      // VLAN separation
TestPersistentState    // State preservation across restarts
TestOVNIntegration     // OVN functionality
```

## Test Scenarios

### Scenario 1: Basic Functionality
```bash
# Create network
docker network create --driver ovs-container-network:latest \
  --subnet 10.100.0.0/24 test-basic

# Launch containers
docker run -d --name c1 --network test-basic alpine sleep 3600
docker run -d --name c2 --network test-basic alpine sleep 3600

# Test connectivity
docker exec c1 ping -c 2 c2

# Cleanup
docker rm -f c1 c2
docker network rm test-basic
```

### Scenario 2: Plugin Restart with State Recovery
```bash
# Setup
docker network create --driver ovs-container-network:latest \
  --subnet 10.101.0.0/24 persistent-net
docker run -d --name persistent-cont \
  --network persistent-net alpine sleep 3600

# Record state
IP_BEFORE=$(docker inspect persistent-cont \
  --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')

# Restart plugin
docker plugin disable ovs-container-network:latest
docker plugin enable ovs-container-network:latest

# Verify state preserved
docker restart persistent-cont
IP_AFTER=$(docker inspect persistent-cont \
  --format '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}')

[ "$IP_BEFORE" = "$IP_AFTER" ] && echo "✅ State preserved"
```

### Scenario 3: OVN with Auto-Create
```bash
# Create OVN-backed network with auto-create
docker network create --driver ovs-container-network:latest \
  --subnet 10.102.0.0/24 \
  --opt ovn.switch=ls-test \
  --opt ovn.auto_create=true \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  ovn-test

# Verify OVN central running
docker ps | grep ovn-central

# Check logical switch
docker exec ovn-central ovn-nbctl ls-list | grep ls-test
```

## Debugging Test Failures

### Check Plugin Logs
```bash
# View recent plugin logs
docker plugin logs ovs-container-network:latest --tail 50

# Follow logs during test
docker plugin logs -f ovs-container-network:latest
```

### Inspect State Files
```bash
# Find plugin data directory
PLUGIN_ID=$(docker plugin ls --format "{{.ID}}" \
  --filter "name=ovs-container-network:latest")

# Check state files
sudo ls -la /var/lib/docker/plugins/${PLUGIN_ID}/propagated-mount/data/
sudo cat /var/lib/docker/plugins/${PLUGIN_ID}/propagated-mount/data/networks.json
```

### OVS Debugging
```bash
# Check OVS configuration
sudo ovs-vsctl show

# View flow rules
sudo ovs-ofctl dump-flows br-int

# Check port details
sudo ovs-vsctl list interface
```

### OVN Debugging
```bash
# Logical topology
docker exec ovn-central ovn-nbctl show

# Physical bindings
docker exec ovn-central ovn-sbctl show

# List logical switches
docker exec ovn-central ovn-nbctl ls-list

# List logical ports
docker exec ovn-central ovn-nbctl lsp-list <switch-name>
```

## Continuous Integration

### GitHub Actions Workflow (Future)
```yaml
name: Plugin Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v2
      - name: Setup Lima
        run: |
          brew install lima
          limactl start --name=ovs-lab lima.yaml
      - name: Run Tests
        run: make test-all
      - name: Upload Coverage
        uses: codecov/codecov-action@v2
```

## Test Coverage Goals

- **Unit Tests**: > 80% coverage
- **Integration Tests**: All critical paths
- **Performance Tests**: < 100ms network creation
- **Stress Tests**: 100+ concurrent networks

## Adding New Tests

### Unit Test Template
```go
func TestNewFeature(t *testing.T) {
    // Setup
    store, cleanup := setupTestStore(t)
    defer cleanup()

    // Test
    result, err := store.NewFeature()

    // Assert
    assert.NoError(t, err)
    assert.NotNil(t, result)
}
```

### Integration Test Template
```bash
test_new_feature() {
    log_test "Testing new feature"

    # Setup
    local network_name="${TEST_NETWORK_PREFIX}-new"

    # Execute
    if sudo docker network create --driver "${PLUGIN_NAME}" \
        "${network_name}" > /dev/null 2>&1; then
        pass_test "New feature works"
    else
        fail_test "New feature failed"
    fi

    # Cleanup
    sudo docker network rm "${network_name}" 2>/dev/null || true
}
```

## Best Practices

1. **Always clean up** - Use defer/trap to ensure cleanup
2. **Use unique names** - Prefix test resources with test identifiers
3. **Check prerequisites** - Verify environment before running tests
4. **Log failures** - Capture detailed error information
5. **Test isolation** - Tests should not depend on each other
6. **Idempotency** - Tests should be runnable multiple times

## Troubleshooting

### Common Issues

#### Plugin Not Found
```bash
# Reinstall plugin
make plugin-install
```

#### State Corruption
```bash
# Reset plugin state
docker plugin disable ovs-container-network:latest
sudo rm -rf /var/lib/docker/plugins/*/propagated-mount/data/*
docker plugin enable ovs-container-network:latest
```

#### OVN Connection Issues
```bash
# Check OVN central
docker ps | grep ovn-central
docker logs ovn-central

# Restart OVN
docker restart ovn-central
```

## Performance Testing

### Network Creation Benchmark
```bash
time for i in {1..10}; do
  docker network create --driver ovs-container-network:latest \
    --subnet "10.${i}.0.0/24" "perf-test-${i}"
done
```

### Concurrent Container Launch
```bash
for i in {1..20}; do
  docker run -d --name "perf-${i}" \
    --network perf-test-1 alpine sleep 3600 &
done
wait
```

## Summary

The comprehensive test suite ensures:
- ✅ Core functionality works correctly
- ✅ State persistence is reliable
- ✅ OVN integration functions properly
- ✅ VLAN isolation is enforced
- ✅ Concurrent operations are thread-safe
- ✅ Plugin survives restarts and upgrades

Regular test execution (`make test-all`) should be run before any significant changes or releases.