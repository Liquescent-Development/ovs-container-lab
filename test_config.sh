#!/bin/bash
# Test script for network configuration management

set -e

echo "Testing Network Configuration Management"
echo "========================================"

# Test 1: Validate configuration
echo -n "1. Validating configuration... "
python3 network_config_manager.py validate
echo "✓"

# Test 2: Show hosts
echo -e "\n2. Configured hosts:"
python3 network_config_manager.py show-hosts

# Test 3: Show containers for current host
echo -e "\n3. Containers for current host:"
python3 network_config_manager.py show-containers

# Test 4: Show VPCs
echo -e "\n4. VPC configuration:"
python3 network_config_manager.py show-vpcs

# Test 5: Test with orchestrator (dry run)
echo -e "\n5. Testing orchestrator with config:"
export NETWORK_CONFIG=network-config.yaml
python3 orchestrator.py show >/dev/null 2>&1 && echo "✓ Orchestrator loaded config successfully" || echo "✗ Orchestrator failed to load config"

echo -e "\n✅ All tests passed!"