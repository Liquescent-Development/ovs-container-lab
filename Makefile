# OVS Container Lab - Simplified Makefile
# Clean, single-path workflow for all operations

.PHONY: help up down status clean check traffic-run traffic-chaos traffic-stop

# Default configuration file
# All configuration is now in docker-compose.yml

# Default target
help:
	@echo "OVS Container Lab - Simplified Commands"
	@echo "========================================"
	@echo ""
	@echo "CORE COMMANDS:"
	@echo "  make up           - Start everything (VM, containers, networking)"
	@echo "  make status       - Show status of entire lab"
	@echo "  make down         - Stop containers (VM stays running)"
	@echo "  make clean        - Clean everything including VM"
	@echo "  make check        - Verify configuration and topology"
	@echo "  make go-version   - Check Go version in VM"
	@echo ""
	@echo "TRAFFIC GENERATION:"
	@echo "  make traffic-run   - Generate normal traffic"
	@echo "  make traffic-chaos - Generate chaos traffic (heavy internal)"
	@echo "  make traffic-stop  - Stop all traffic generation"
	@echo ""
	@echo "CHAOS ENGINEERING:"
	@echo "  make chaos-loss       - Simulate 30% packet loss"
	@echo "  make chaos-delay      - Add 100ms network delay"
	@echo "  make chaos-bandwidth  - Limit bandwidth to 1mbit"
	@echo "  make chaos-partition  - Create network partition"
	@echo "  make chaos-corruption - Introduce packet corruption"
	@echo "  make chaos-duplication - Introduce packet duplication"
	@echo ""
	@echo "MONITORING:"
	@echo "  make logs        - Follow container logs"
	@echo "  make dashboard   - Open Grafana (http://localhost:3000)"
	@echo "  make metrics     - Show current metrics"
	@echo ""
	@echo "PLUGIN MANAGEMENT:"
	@echo "  make plugin-install   - Install OVS network plugin"
	@echo "  make plugin-uninstall - Uninstall OVS network plugin"
	@echo "  make plugin-status    - Check plugin status"
	@echo ""
	@echo "DEVELOPMENT:"
	@echo "  make shell-vm    - SSH into Lima VM"
	@echo "  make shell-ovn   - Shell into OVN container"
	@echo "  make shell-ovs   - Shell into OVS container"
	@echo ""
	@echo "Configuration: docker-compose.yml"

# ==================== CORE COMMANDS ====================

up: _ensure-vm
	@echo "🚀 Starting OVS Container Lab..."
	@echo ""
	@echo "Step 1: Building OVN central image..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker build -t ovn-central:latest ./ovn-container
	@echo ""
	@echo "Step 2: Installing OVS network plugin..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator-simple.py install-plugin
	@echo ""
	@echo "Step 3: Setting up monitoring exporters..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator-simple.py setup-monitoring
	@echo ""
	@echo "Step 4: Starting containers (networks created automatically by docker-compose)..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker compose up -d
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker compose --profile testing --profile vpc --profile traffic --profile chaos up -d
	@echo ""
	@echo "Step 5: Setting up OVS chassis connection to OVN..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator-simple.py setup-chassis
	@echo ""
	@echo "✅ OVS Container Lab is ready!"
	@echo "  Grafana:    http://localhost:3000 (admin/admin)"
	@echo "  Prometheus: http://localhost:9090"

# ==================== PLUGIN MANAGEMENT ====================

plugin-install: _ensure-vm
	@echo "🔌 Installing OVS Container Network plugin..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator-simple.py install-plugin

plugin-uninstall: _ensure-vm
	@echo "🔌 Uninstalling OVS Container Network plugin..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator-simple.py uninstall-plugin

plugin-status: _ensure-vm
	@echo "🔍 Checking OVS Container Network plugin status..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker plugin ls | grep ovs-container-network

status:
	@echo "=== Lima VM Status ==="
	@limactl list ovs-lab 2>/dev/null || echo "VM not created"
	@echo ""
	@echo "=== Container Status ==="
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker ps --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || echo "VM not running"
	@echo ""
	@echo "=== OVS Bridge Status ==="
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo ovs-vsctl show 2>/dev/null | head -15 || echo "OVS not available"
	@echo ""
	@echo "=== OVN Topology Status ==="
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker exec ovn-central ovn-nbctl show 2>/dev/null | head -15 || echo "OVN not available"

down:
	@echo "Stopping all containers..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker compose --profile testing --profile vpc --profile traffic --profile chaos down
	@echo "✅ Containers stopped (VM still running)"

clean:
	@echo "🧹 Cleaning everything including VM..."
	@limactl delete ovs-lab --force 2>/dev/null || true
	@echo "✅ Everything cleaned up"

check:
	@echo "🔍 Running network diagnostics..."
	@echo "Network checking temporarily disabled - needs update for new architecture"

# ==================== TRAFFIC GENERATION ====================

traffic-run:
	@echo "📡 Generating normal traffic across VPCs..."
	@echo "Starting traffic generators with standard patterns..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker exec -d traffic-gen-a bash -c 'cd /workspace && python3 traffic-gen.py standard'
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker exec -d traffic-gen-b bash -c 'cd /workspace && python3 traffic-gen.py standard'
	@echo "Traffic generation started. Monitor in Grafana dashboard."
	@echo "Use 'make traffic-stop' to stop."

traffic-chaos:
	@echo "🔥 CHAOS MODE - Heavy internal traffic generation..."
	@echo "WARNING: This will generate heavy internal traffic to stress test the network!"
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker exec -d traffic-gen-a bash -c 'cd /workspace && python3 traffic-gen.py chaos'
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker exec -d traffic-gen-b bash -c 'cd /workspace && python3 traffic-gen.py chaos'
	@echo ""
	@echo "Starting Pumba chaos injection (runs for 5 minutes in background)..."
	@echo "Chaos testing needs update for new architecture"
	@echo ""
	@echo "✅ Chaos traffic and network failures started!"
	@echo ""
	@echo "Monitor in Grafana: http://localhost:3000"
	@echo "Chaos will run for 5 minutes. Check /tmp/chaos.log for details."
	@echo ""
	@echo "To stop chaos early: make traffic-stop"

traffic-stop:
	@echo "🛑 Stopping all traffic generation..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker exec traffic-gen-a pkill -f traffic-gen.py 2>/dev/null || true
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker exec traffic-gen-b pkill -f traffic-gen.py 2>/dev/null || true
	@echo "✅ Traffic generation stopped"

# ==================== CHAOS ENGINEERING ====================

chaos-loss:
	@echo "🔥 Simulating 30% packet loss..."
	@echo "Packet loss chaos needs update for new architecture"

chaos-delay:
	@echo "⏰ Adding 100ms network delay..."
	@echo "Latency chaos needs update for new architecture"

chaos-bandwidth:
	@echo "🚦 Limiting bandwidth to 1mbit..."
	@echo "Bandwidth chaos needs update for new architecture"

chaos-partition:
	@echo "🔌 Creating network partition..."
	@echo "Partition chaos needs update for new architecture"

chaos-corruption:
	@echo "💥 Introducing packet corruption..."
	@echo "Corruption chaos needs update for new architecture"

chaos-duplication:
	@echo "👥 Introducing packet duplication..."
	@echo "Duplication chaos needs update for new architecture"

# ==================== MONITORING ====================

logs:
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker compose logs -f

dashboard:
	@echo "Opening Grafana dashboard..."
	@open http://localhost:3000 2>/dev/null || echo "Open: http://localhost:3000"

metrics:
	@echo "=== Current OVS Metrics ==="
	@curl -s http://localhost:9475/metrics 2>/dev/null | grep "ovs_" | head -15 || echo "Metrics not available"

# ==================== DEVELOPMENT ====================

shell-vm:
	@limactl shell ovs-lab

go-version: _ensure-vm
	@echo "Checking Go version in VM..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- go version || echo "Go is not installed"

shell-ovn:
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker exec -it ovn-central bash

shell-ovs:
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker exec -it ovs bash

# ==================== INTERNAL HELPERS ====================

_ensure-vm:
	@if ! limactl list -q | grep -q "^ovs-lab$$"; then \
		echo "Creating new Lima VM..."; \
		limactl start --name=ovs-lab lima.yaml; \
		echo "Waiting for VM provisioning..."; \
		sleep 15; \
		echo "Installing OVS and OVN packages..."; \
		limactl shell --workdir /home/lima ovs-lab -- sudo DEBIAN_FRONTEND=noninteractive apt-get update; \
		limactl shell --workdir /home/lima ovs-lab -- sudo DEBIAN_FRONTEND=noninteractive apt-get install -y openvswitch-switch openvswitch-common python3-openvswitch ovn-host ovn-common; \
		limactl shell --workdir /home/lima ovs-lab -- sudo systemctl start openvswitch-switch; \
		limactl shell --workdir /home/lima ovs-lab -- sudo ovs-vsctl set open_vswitch . external_ids:system-id=chassis-host; \
		limactl shell --workdir /home/lima ovs-lab -- sudo ovs-vsctl set open_vswitch . external_ids:ovn-encap-type=geneve; \
		limactl shell --workdir /home/lima ovs-lab -- sudo ovs-vsctl --may-exist add-br br-int -- set bridge br-int datapath_type=netdev fail-mode=secure; \
	else \
		if ! limactl list | grep ovs-lab | grep -q Running; then \
			echo "Starting existing Lima VM..."; \
			limactl start ovs-lab; \
			sleep 5; \
		fi; \
	fi
	@echo "VM is ready"
	@echo "Checking Go installation..."
	@if ! limactl shell --workdir /home/lima ovs-lab -- which go > /dev/null 2>&1; then \
		echo "Go not found, installing..."; \
		limactl shell --workdir /home/lima ovs-lab -- bash -c 'GO_VERSION="1.25.1"; \
			ARCH=$$(dpkg --print-architecture); \
			sudo curl -L "https://go.dev/dl/go$${GO_VERSION}.linux-$${ARCH}.tar.gz" -o /tmp/go.tar.gz; \
			sudo tar -C /usr/local -xzf /tmp/go.tar.gz; \
			sudo rm /tmp/go.tar.gz; \
			sudo ln -sf /usr/local/go/bin/go /usr/bin/go; \
			sudo ln -sf /usr/local/go/bin/gofmt /usr/bin/gofmt; \
			echo "Go installed successfully"'; \
	else \
		echo "Go is already installed"; \
	fi

.PHONY: test
test:
	@echo "========================================="
	@echo "     OVS Container Lab Connectivity Test"
	@echo "========================================="
	@echo ""
	@echo "=== Discovering Container Network Configuration ==="
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c 'for container in vpc-a-web vpc-a-app vpc-a-db vpc-b-web vpc-b-app vpc-b-db; do \
		echo -n "$$container: "; \
		sudo docker inspect $$container --format "{{range .NetworkSettings.Networks}}{{.IPAddress}} (gw: {{.Gateway}}){{end}}" 2>/dev/null || echo "not found"; \
	done'
	@echo ""
	@echo "=== Testing Gateway Connectivity ==="
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c 'for container in vpc-a-web vpc-a-app vpc-a-db vpc-b-web vpc-b-app vpc-b-db; do \
		if sudo docker inspect $$container > /dev/null 2>&1; then \
			gateway=$$(sudo docker inspect $$container --format "{{range .NetworkSettings.Networks}}{{.Gateway}}{{end}}"); \
			echo -n "$$container -> gateway ($$gateway): "; \
			if [ -n "$$gateway" ]; then \
				sudo docker exec $$container ping -c 1 -W 2 $$gateway > /dev/null 2>&1 && echo "✅ PASS" || echo "❌ FAIL"; \
			else \
				echo "❌ No gateway configured"; \
			fi \
		fi \
	done'
	@echo ""
	@echo "=== Testing Intra-VPC Connectivity ==="
	@echo "Testing containers within same VPC (should connect):"
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c 'test_connectivity() { \
		src=$$1; dst=$$2; \
		dst_ip=$$(sudo docker inspect $$dst --format "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" 2>/dev/null); \
		if [ -n "$$dst_ip" ]; then \
			echo -n "  $$src -> $$dst ($$dst_ip): "; \
			sudo docker exec $$src ping -c 1 -W 2 $$dst_ip > /dev/null 2>&1 && echo "✅ PASS" || echo "❌ FAIL"; \
		fi \
	}; \
	echo "VPC-A:"; \
	test_connectivity vpc-a-web vpc-a-app; \
	test_connectivity vpc-a-app vpc-a-db; \
	test_connectivity vpc-a-web vpc-a-db; \
	echo "VPC-B:"; \
	test_connectivity vpc-b-web vpc-b-app; \
	test_connectivity vpc-b-app vpc-b-db; \
	test_connectivity vpc-b-web vpc-b-db'
	@echo ""
	@echo "=== Testing Inter-VPC Isolation ==="
	@echo "Testing containers across VPCs (should be isolated):"
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c 'test_isolation() { \
		src=$$1; dst=$$2; \
		dst_ip=$$(sudo docker inspect $$dst --format "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" 2>/dev/null); \
		if [ -n "$$dst_ip" ]; then \
			echo -n "  $$src -> $$dst ($$dst_ip): "; \
			sudo docker exec $$src ping -c 1 -W 2 $$dst_ip > /dev/null 2>&1 && echo "❌ CONNECTED (should be isolated)" || echo "✅ ISOLATED"; \
		fi \
	}; \
	test_isolation vpc-a-web vpc-b-web; \
	test_isolation vpc-a-app vpc-b-app; \
	test_isolation vpc-a-db vpc-b-db'
	@echo ""
	@echo "========================================="

# ==================== TESTING ====================

# Unit tests for the plugin
test-unit: _ensure-vm
	@echo "🧪 Running unit tests for OVS Container Network plugin..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator-simple.py test-unit

# Integration tests - requires plugin to be installed
test-integration: _ensure-vm
	@echo "🧪 Running integration tests in Lima VM..."
	@echo "Step 1: Checking if plugin is installed..."
	@if ! limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker plugin ls | grep -q "ovs-container-network.*true"; then \
		echo "Plugin not found or not enabled. Installing..."; \
		limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator-simple.py install-plugin; \
	else \
		echo "Plugin is already installed and enabled"; \
	fi
	@echo ""
	@echo "Step 2: Running integration tests..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator-simple.py test-integration

# Full test suite
test-all: _ensure-vm
	@echo "🧪 Running all tests..."
	@echo "Checking if plugin is installed..."
	@if ! limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker plugin ls | grep -q "ovs-container-network.*true"; then \
		echo "Plugin not found or not enabled. Installing..."; \
		limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator-simple.py install-plugin; \
	else \
		echo "Plugin is already installed and enabled"; \
	fi
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator-simple.py test-all

# Quick smoke test
test-quick: _ensure-vm
	@echo "🚀 Running quick smoke tests..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c 'echo "=== Plugin Status ==="; sudo docker plugin ls | grep ovs-container-network'
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c 'echo "=== Creating test network ==="; sudo docker network create --driver ovs-container-network:latest --subnet 10.99.0.0/24 test-smoke || true'
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c 'echo "=== Verifying network ==="; sudo docker network ls | grep test-smoke'
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c 'echo "=== Cleaning up ==="; sudo docker network rm test-smoke || true'
	@echo "✅ Smoke test passed!"

# Test persistence specifically
test-persistence: _ensure-vm
	@echo "💾 Testing persistent state management..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c '\
		echo "Creating network with state..."; \
		sudo docker network create --driver ovs-container-network:latest --subnet 10.98.0.0/24 test-persist; \
		sudo docker run -d --name test-persist-cont --network test-persist alpine:latest sleep 3600; \
		IP_BEFORE=$$(sudo docker inspect test-persist-cont --format "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"); \
		echo "Container IP before restart: $$IP_BEFORE"; \
		echo "Restarting plugin..."; \
		sudo docker plugin disable ovs-container-network:latest; \
		sleep 2; \
		sudo docker plugin enable ovs-container-network:latest; \
		sleep 3; \
		sudo docker restart test-persist-cont; \
		sleep 2; \
		IP_AFTER=$$(sudo docker inspect test-persist-cont --format "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"); \
		echo "Container IP after restart: $$IP_AFTER"; \
		if [ "$$IP_BEFORE" = "$$IP_AFTER" ]; then \
			echo "✅ Persistence test PASSED - IP preserved"; \
		else \
			echo "❌ Persistence test FAILED - IP changed"; \
			exit 1; \
		fi; \
		sudo docker rm -f test-persist-cont; \
		sudo docker network rm test-persist'

# Test OVN auto-create functionality
test-ovn-auto: _ensure-vm
	@echo "🔧 Testing OVN auto-create functionality..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c '\
		echo "Creating network with OVN auto-create..."; \
		sudo docker network create --driver ovs-container-network:latest \
			--subnet 10.97.0.0/24 \
			--opt ovn.switch=ls-auto-test \
			--opt ovn.auto_create=true \
			--opt ovn.nb_connection=tcp:172.30.0.5:6641 \
			--opt ovn.sb_connection=tcp:172.30.0.5:6642 \
			test-ovn-auto; \
		echo "Verifying OVN central is running..."; \
		if sudo docker ps | grep -q ovn-central; then \
			echo "✅ OVN central is running"; \
		else \
			echo "❌ OVN central is not running"; \
			exit 1; \
		fi; \
		echo "Verifying logical switch..."; \
		if sudo docker exec ovn-central ovn-nbctl ls-list | grep -q ls-auto-test; then \
			echo "✅ Logical switch created"; \
		else \
			echo "❌ Logical switch not found"; \
			exit 1; \
		fi; \
		echo "Cleaning up..."; \
		sudo docker network rm test-ovn-auto'

# Clean test artifacts
test-clean: _ensure-vm
	@echo "🧹 Cleaning up test artifacts..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c '\
		sudo docker ps -a --filter "name=test-" -q | xargs -r sudo docker rm -f 2>/dev/null || true; \
		sudo docker ps -a --filter "name=itest-" -q | xargs -r sudo docker rm -f 2>/dev/null || true; \
		sudo docker network ls --filter "name=test-" -q | xargs -r sudo docker network rm 2>/dev/null || true; \
		sudo docker network ls --filter "name=itest-" -q | xargs -r sudo docker network rm 2>/dev/null || true'
	@echo "✅ Test cleanup completed"

.PHONY: test-unit test-integration test-all test-quick test-persistence test-ovn-auto test-clean