# OVS Container Lab - Simplified Makefile
# Clean, single-path workflow for all operations

.PHONY: help up down status clean check traffic-run traffic-chaos traffic-stop

# Default configuration file
NETWORK_CONFIG ?= network-config.yaml

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
	@echo "DEVELOPMENT:"
	@echo "  make shell-vm    - SSH into Lima VM"
	@echo "  make shell-ovn   - Shell into OVN container"
	@echo "  make shell-ovs   - Shell into OVS container"
	@echo ""
	@echo "Current config: $(NETWORK_CONFIG)"

# ==================== CORE COMMANDS ====================

up: _ensure-vm
	@echo "🚀 Starting OVS Container Lab..."
	@echo "Using configuration: $(NETWORK_CONFIG)"
	@echo ""
	@echo "Starting core services and containers..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo docker compose up -d prometheus grafana ovn-central"
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo docker compose --profile testing --profile vpc --profile traffic --profile chaos up -d"
	@echo ""
	@echo "Running orchestrated setup with proper ordering and verification..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo NETWORK_CONFIG=$(NETWORK_CONFIG) python3 orchestrator.py up"

status:
	@echo "=== Lima VM Status ==="
	@limactl list ovs-lab 2>/dev/null || echo "VM not created"
	@echo ""
	@echo "=== Container Status ==="
	@limactl shell ovs-lab -- sudo docker ps --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || echo "VM not running"
	@echo ""
	@echo "=== OVS Bridge Status ==="
	@limactl shell ovs-lab -- sudo ovs-vsctl show 2>/dev/null | head -15 || echo "OVS not available"
	@echo ""
	@echo "=== OVN Topology Status ==="
	@limactl shell ovs-lab -- sudo docker exec ovn-central ovn-nbctl show 2>/dev/null | head -15 || echo "OVN not available"

down:
	@echo "Stopping all containers..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo docker compose --profile testing --profile vpc --profile traffic --profile chaos down"
	@echo "✅ Containers stopped (VM still running)"

clean:
	@echo "🧹 Cleaning everything including VM..."
	@limactl delete ovs-lab --force 2>/dev/null || true
	@echo "✅ Everything cleaned up"

check:
	@echo "🔍 Running network diagnostics..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo NETWORK_CONFIG=$(NETWORK_CONFIG) python3 orchestrator.py check"

# ==================== TRAFFIC GENERATION ====================

traffic-run:
	@echo "📡 Generating normal traffic across VPCs..."
	@echo "Starting traffic generators with standard patterns..."
	@limactl shell ovs-lab -- bash -c "sudo docker exec -d traffic-gen-a bash -c 'cd /workspace && python3 traffic-gen.py standard'"
	@limactl shell ovs-lab -- bash -c "sudo docker exec -d traffic-gen-b bash -c 'cd /workspace && python3 traffic-gen.py standard'"
	@echo "Traffic generation started. Monitor in Grafana dashboard."
	@echo "Use 'make traffic-stop' to stop."

traffic-chaos:
	@echo "🔥 CHAOS MODE - Heavy internal traffic generation..."
	@echo "WARNING: This will generate heavy internal traffic to stress test the network!"
	@limactl shell ovs-lab -- bash -c "sudo docker exec -d traffic-gen-a bash -c 'cd /workspace && python3 traffic-gen.py chaos'"
	@limactl shell ovs-lab -- bash -c "sudo docker exec -d traffic-gen-b bash -c 'cd /workspace && python3 traffic-gen.py chaos'"
	@echo ""
	@echo "Starting Pumba chaos injection (runs for 5 minutes in background)..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo NETWORK_CONFIG=$(NETWORK_CONFIG) nohup python3 orchestrator.py chaos mixed --duration 300 --target 'vpc-.*' > /tmp/chaos.log 2>&1 &"
	@echo ""
	@echo "✅ Chaos traffic and network failures started!"
	@echo ""
	@echo "Monitor in Grafana: http://localhost:3000"
	@echo "Chaos will run for 5 minutes. Check /tmp/chaos.log for details."
	@echo ""
	@echo "To stop chaos early: make traffic-stop"

traffic-stop:
	@echo "🛑 Stopping all traffic generation..."
	@limactl shell ovs-lab -- bash -c "sudo docker exec traffic-gen-a pkill -f traffic-gen.py 2>/dev/null || true"
	@limactl shell ovs-lab -- bash -c "sudo docker exec traffic-gen-b pkill -f traffic-gen.py 2>/dev/null || true"
	@echo "✅ Traffic generation stopped"

# ==================== CHAOS ENGINEERING ====================

chaos-loss:
	@echo "🔥 Simulating 30% packet loss..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo NETWORK_CONFIG=$(NETWORK_CONFIG) python3 orchestrator.py chaos packet-loss --duration 60 --target 'vpc-.*'"

chaos-delay:
	@echo "⏰ Adding 100ms network delay..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo NETWORK_CONFIG=$(NETWORK_CONFIG) python3 orchestrator.py chaos latency --duration 60 --target 'vpc-.*'"

chaos-bandwidth:
	@echo "🚦 Limiting bandwidth to 1mbit..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo NETWORK_CONFIG=$(NETWORK_CONFIG) python3 orchestrator.py chaos bandwidth --duration 60 --target 'vpc-.*'"

chaos-partition:
	@echo "🔌 Creating network partition..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo NETWORK_CONFIG=$(NETWORK_CONFIG) python3 orchestrator.py chaos partition --duration 30 --target 'vpc-.*-web'"

chaos-corruption:
	@echo "💥 Introducing packet corruption..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo NETWORK_CONFIG=$(NETWORK_CONFIG) python3 orchestrator.py chaos corruption --duration 60 --target 'vpc-.*'"

chaos-duplication:
	@echo "👥 Introducing packet duplication..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo NETWORK_CONFIG=$(NETWORK_CONFIG) python3 orchestrator.py chaos duplication --duration 60 --target 'vpc-.*'"

# ==================== MONITORING ====================

logs:
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo docker compose logs -f"

dashboard:
	@echo "Opening Grafana dashboard..."
	@open http://localhost:3000 2>/dev/null || echo "Open: http://localhost:3000"

metrics:
	@echo "=== Current OVS Metrics ==="
	@curl -s http://localhost:9475/metrics 2>/dev/null | grep "ovs_" | head -15 || echo "Metrics not available"

# ==================== DEVELOPMENT ====================

shell-vm:
	@limactl shell ovs-lab

shell-ovn:
	@limactl shell ovs-lab -- sudo docker exec -it ovn-central bash

shell-ovs:
	@limactl shell ovs-lab -- sudo docker exec -it ovs bash

# ==================== INTERNAL HELPERS ====================

_ensure-vm:
	@if ! limactl list -q | grep -q "^ovs-lab$$"; then \
		echo "Creating new Lima VM..."; \
		limactl start --name=ovs-lab lima.yaml; \
		echo "Waiting for VM provisioning..."; \
		sleep 15; \
		echo "Installing OVS and OVN packages..."; \
		limactl shell ovs-lab -- sudo DEBIAN_FRONTEND=noninteractive apt-get update; \
		limactl shell ovs-lab -- sudo DEBIAN_FRONTEND=noninteractive apt-get install -y openvswitch-switch openvswitch-common python3-openvswitch ovn-host ovn-common; \
		limactl shell ovs-lab -- sudo systemctl start openvswitch-switch; \
		limactl shell ovs-lab -- sudo ovs-vsctl set open_vswitch . external_ids:system-id=chassis-host; \
		limactl shell ovs-lab -- sudo ovs-vsctl set open_vswitch . external_ids:ovn-encap-type=geneve; \
		limactl shell ovs-lab -- sudo ovs-vsctl --may-exist add-br br-int -- set bridge br-int datapath_type=netdev fail-mode=secure; \
	else \
		if ! limactl list | grep ovs-lab | grep -q Running; then \
			echo "Starting existing Lima VM..."; \
			limactl start ovs-lab; \
			sleep 5; \
		fi; \
	fi
	@echo "VM is ready"

.PHONY: test
test:
	@echo "Running connectivity tests..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo NETWORK_CONFIG=$(NETWORK_CONFIG) python3 orchestrator.py test"