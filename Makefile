# OVS Container Lab - Makefile
# Control everything from macOS using Lima VM

.PHONY: help up down status logs clean test build lima-start lima-ssh lima-stop lima-delete

# Default target
help:
	@echo "OVS Container Lab - Lima VM Control"
	@echo "===================================="
	@echo ""
	@echo "QUICK START:"
	@echo "  make up         - Start Lima VM and entire stack"
	@echo "  make status     - Show status of everything"
	@echo "  make down       - Stop containers (VM stays running)"
	@echo "  make clean      - Stop containers and delete VM"
	@echo ""
	@echo "TESTING:"
	@echo "  make test-start - Start test containers"
	@echo "  make setup-ovn  - Setup OVN topology"
	@echo "  make test       - Run connectivity tests"
	@echo "  make show-ovn   - Show OVN configuration"
	@echo "  make test-full  - Start containers, setup OVN, and test"
	@echo "  make setup-all  - Complete setup with everything"
	@echo ""
	@echo "TRAFFIC GENERATION:"
	@echo "  make traffic-start - Start traffic generator container"
	@echo "  make traffic-run   - Generate normal traffic"
	@echo "  make traffic-heavy - Generate heavy traffic load"
	@echo "  make traffic-stop  - Stop traffic generator"
	@echo ""
	@echo "CHAOS ENGINEERING:"
	@echo "  make chaos      - Run network partition scenario"
	@echo "  make chaos-loss - Simulate packet loss (20%)"
	@echo "  make chaos-delay - Add network delay (100ms)"
	@echo "  make chaos-kill - Kill random container"
	@echo "  make chaos-pause - Pause random containers"
	@echo ""
	@echo "MONITORING:"
	@echo "  make logs       - Follow container logs"
	@echo "  make dashboard  - Open Grafana (http://localhost:3000)"
	@echo "  make metrics    - Show current metrics"
	@echo ""
	@echo "DEVELOPMENT:"
	@echo "  make lima-ssh   - SSH into the Lima VM"
	@echo "  make shell-ovn  - Shell into OVN container"
	@echo "  make shell-ovs  - Shell into OVS container"
	@echo "  make build      - Rebuild container images"

# ==================== MAIN OPERATIONS ====================

setup-all: up traffic-start
	@echo ""
	@echo "=========================================="
	@echo "✅ Complete OVS Container Lab Setup Done!"
	@echo "=========================================="
	@echo ""
	@echo "Everything is running:"
	@echo "  - OVN SDN Controller"
	@echo "  - OVS bridges (VPC-A and VPC-B)"
	@echo "  - Test containers attached to OVS"
	@echo "  - Traffic generator ready"
	@echo ""
	@echo "Access points:"
	@echo "  - Grafana: http://localhost:3000"
	@echo "  - Prometheus: http://localhost:9090"
	@echo ""
	@echo "Next steps:"
	@echo "  - make traffic-run    # Generate traffic"
	@echo "  - make chaos-loss     # Simulate packet loss"
	@echo "  - make status         # Check status"

up: lima-start
	@echo "🚀 Starting OVS Container Lab..."
	@echo "Waiting for VM to be ready..."
	@sleep 5
	@echo "Setting up monitoring exporters on host..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 orchestrator.py setup-monitoring" || true
	@echo "Starting core services..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo docker compose up -d prometheus grafana ovn-central"
	@echo "Waiting for OVN to initialize..."
	@sleep 10
	@echo "Setting up OVN topology..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 orchestrator.py setup" || true
	@echo "Setting up OVS as OVN chassis..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 orchestrator.py setup-chassis" || true
	@echo "Starting test containers..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo docker compose --profile testing --profile vpc up -d"
	@sleep 5
	@echo "Binding containers to OVN..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 orchestrator.py bind-containers"
	@echo ""
	@echo "✅ Stack is running with proper SDN/OVN!"
	@echo ""
	@echo "Access from your Mac:"
	@echo "  Grafana:    http://localhost:3000 (admin/admin)"
	@echo "  Prometheus: http://localhost:9090"
	@echo ""
	@echo "Run 'make test' to verify connectivity"

down:
	@echo "Stopping containers..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo docker compose down"
	@echo "✅ Containers stopped (VM still running)"

clean: down
	@echo "✅ Containers cleaned up (VM preserved)"

clean-all: down lima-delete
	@echo "✅ Everything cleaned up including VM"

status:
	@echo "=== VM Status ==="
	@limactl list ovs-lab 2>/dev/null || echo "VM not created"
	@echo ""
	@echo "=== Container Status ==="
	@limactl shell ovs-lab -- sudo docker ps --format "table {{.Names}}\t{{.Status}}" 2>/dev/null || echo "VM not running"
	@echo ""
	@echo "=== OVS Status ==="
	@limactl shell ovs-lab -- sudo ovs-vsctl show 2>/dev/null | head -20 || echo "OVS not available"

# ==================== LIMA CONTROL ====================

lima-start:
	@if limactl list -q | grep -q "^ovs-lab$$"; then \
		echo "Lima VM already exists, starting..."; \
		limactl start ovs-lab; \
		echo "Ensuring OVN packages are installed..."; \
		limactl shell ovs-lab -- sudo DEBIAN_FRONTEND=noninteractive apt-get update; \
		limactl shell ovs-lab -- sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" openvswitch-switch openvswitch-common python3-openvswitch ovn-host ovn-common; \
		echo "Configuring OVS for OVN..."; \
		limactl shell ovs-lab -- sudo ovs-vsctl set open_vswitch . external_ids:system-id=chassis-host; \
		limactl shell ovs-lab -- sudo bash -c "echo 'chassis-host' > /etc/openvswitch/system-id.conf"; \
		limactl shell ovs-lab -- sudo ovs-vsctl set open_vswitch . external_ids:ovn-encap-type=geneve; \
		limactl shell ovs-lab -- sudo ovs-vsctl --may-exist add-br br-int -- set bridge br-int datapath_type=netdev fail-mode=secure; \
		echo "OVN controller will be started when OVN central is ready..."; \
		limactl shell ovs-lab -- sudo systemctl stop ovn-controller 2>/dev/null || true; \
	else \
		echo "Creating new Lima VM..."; \
		limactl start --name=ovs-lab lima.yaml; \
		echo "Waiting for VM provisioning to complete..."; \
		sleep 15; \
		echo "Installing OVS and OVN packages..."; \
		limactl shell ovs-lab -- sudo DEBIAN_FRONTEND=noninteractive apt-get update; \
		limactl shell ovs-lab -- sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -o Dpkg::Options::="--force-confdef" -o Dpkg::Options::="--force-confold" openvswitch-switch openvswitch-common python3-openvswitch ovn-host ovn-common; \
		limactl shell ovs-lab -- sudo systemctl start openvswitch-switch; \
		echo "Setting initial OVS system-id..."; \
		limactl shell ovs-lab -- sudo ovs-vsctl set open_vswitch . external_ids:system-id=chassis-host; \
		limactl shell ovs-lab -- sudo bash -c "echo 'chassis-host' > /etc/openvswitch/system-id.conf"; \
	fi
	@echo "Verifying OVS and OVN installation..."
	@limactl shell ovs-lab -- which ovs-vsctl || (echo "ERROR: OVS not installed!" && exit 1)
	@limactl shell ovs-lab -- which ovn-controller || (echo "ERROR: ovn-controller not installed!" && exit 1)
	@limactl shell ovs-lab -- sudo ovs-vsctl --version
	@limactl shell ovs-lab -- ovn-controller --version

lima-ssh:
	@limactl shell ovs-lab

lima-stop:
	@echo "Stopping Lima VM..."
	@limactl stop ovs-lab

lima-delete:
	@echo "Deleting Lima VM..."
	@limactl delete ovs-lab --force

# ==================== TESTING ====================

test-start:
	@echo "Starting test containers..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo docker compose --profile testing --profile vpc up -d"
	@echo "Waiting for containers to start..."
	@sleep 5
	@echo "Binding containers to OVN..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 orchestrator.py bind-containers"
	@echo "Test containers ready with OVN networking"

attach:
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 orchestrator.py bind-containers"

test:
	@echo "Running connectivity tests..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 orchestrator.py test"

setup-ovn:
	@echo "Setting up OVN topology..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 orchestrator.py setup"

show-ovn:
	@echo "Showing OVN topology..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 orchestrator.py show"

test-driver:
	@echo "Testing Docker network driver..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 orchestrator.py test-driver"

chaos:
	@echo "Running chaos scenario..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 orchestrator.py chaos --scenario network-partition --duration 30"

test-full: test-start test

# ==================== TRAFFIC GENERATION ====================

traffic-start:
	@echo "Starting traffic generator..."
	@echo "Ensuring Docker is healthy..."
	@limactl shell ovs-lab -- sudo systemctl restart docker 2>/dev/null || true
	@sleep 3
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo docker compose --profile traffic build traffic-generator"
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo docker compose --profile traffic up -d traffic-generator"
	@echo "Connecting traffic generator to OVN transit network..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 orchestrator.py bind-containers"
	@echo "Traffic generator ready. Use 'make traffic-run' to generate traffic"

traffic-run:
	@echo "Generating multi-VPC traffic patterns..."
	@echo "Starting traffic generator in background (it will run until stopped)..."
	@limactl shell ovs-lab -- sudo docker exec -d traffic-generator python3 /workspace/multi-vpc-traffic-gen.py standard
	@echo "Traffic is being generated. Check Grafana dashboards to see the traffic."
	@echo "Use 'make traffic-status' to check status or 'make traffic-stop' to stop."

traffic-status:
	@echo "Checking traffic generator status..."
	@limactl shell ovs-lab -- bash -c "sudo docker exec traffic-generator ps aux | grep -v grep | grep multi-vpc && echo 'Traffic generator is running' || echo 'Traffic generator is not running'"

traffic-heavy:
	@echo "Generating heavy traffic load..."
	@limactl shell ovs-lab -- sudo docker exec traffic-generator python3 /workspace/multi-vpc-traffic-gen.py high

traffic-overload:
	@echo "Generating overload traffic (includes malformed packets)..."
	@limactl shell ovs-lab -- sudo docker exec traffic-generator python3 /workspace/multi-vpc-traffic-gen.py overload

traffic-stop:
	@echo "Stopping traffic generator processes..."
	@limactl shell ovs-lab -- sudo docker exec traffic-generator pkill -f multi-vpc || true
	@echo "Traffic generation stopped. Container is still running for future use."
	@echo "Use 'make traffic-stop-container' to stop the container completely."

traffic-stop-container:
	@echo "Stopping traffic generator container..."
	@limactl shell ovs-lab -- sudo docker compose --profile traffic down

# ==================== CHAOS ENGINEERING ====================

chaos-loss:
	@echo "Simulating 20% packet loss on all containers..."
	@limactl shell ovs-lab -- sudo docker run --rm -v /var/run/docker.sock:/var/run/docker.sock gaiaadm/pumba \
		netem --duration 60s --tc-image gaiadocker/iproute2 loss --percent 20 re2:"^vpc-"

chaos-delay:
	@echo "Adding 100ms delay to all containers..."
	@limactl shell ovs-lab -- sudo docker run --rm -v /var/run/docker.sock:/var/run/docker.sock gaiaadm/pumba \
		netem --duration 60s --tc-image gaiadocker/iproute2 delay --time 100 re2:"^vpc-"

chaos-kill:
	@echo "Randomly killing a container..."
	@limactl shell ovs-lab -- sudo docker run --rm -v /var/run/docker.sock:/var/run/docker.sock gaiaadm/pumba \
		kill --signal SIGKILL re2:"^vpc-.*-web"

chaos-pause:
	@echo "Pausing random containers for 30s..."
	@limactl shell ovs-lab -- sudo docker run --rm -v /var/run/docker.sock:/var/run/docker.sock gaiaadm/pumba \
		pause --duration 30s re2:"^vpc-"

# ==================== MONITORING ====================

logs:
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo docker compose logs -f"

logs-ovs:
	@limactl shell ovs-lab -- sudo docker logs -f ovs-vpc-a

logs-ovn:
	@limactl shell ovs-lab -- sudo docker logs -f ovn-central

dashboard:
	@echo "Opening Grafana dashboard..."
	@open http://localhost:3000 2>/dev/null || echo "Open: http://localhost:3000"

metrics:
	@echo "=== Current Metrics ==="
	@curl -s http://localhost:9475/metrics | grep "ovs_" | head -10

# ==================== DEVELOPMENT ====================

build:
	@echo "Building container images..."
	@limactl shell ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo docker compose build"

shell-ovn:
	@limactl shell ovs-lab -- sudo docker exec -it ovn-central bash

shell-ovs:
	@limactl shell ovs-lab -- sudo docker exec -it ovs-vpc-a bash

shell-vm:
	@limactl shell ovs-lab

# ==================== ADVANCED ====================

watch-traffic:
	@watch -n2 'curl -s http://localhost:9475/metrics | grep -E "ovs_interface_(rx|tx)_packets" | head -10'

restart: down up

rebuild: build up

# Quick VM restart
restart-vm: lima-stop lima-start

# Full reset
reset: clean up

.PHONY: info
info:
	@echo "Project: OVS Container Lab"
	@echo "VM Type: Lima (using macOS native virtualization)"
	@echo ""
	@echo "Port Forwards:"
	@echo "  3000 -> 3000  (Grafana)"
	@echo "  9090 -> 9090  (Prometheus)"
	@echo "  9475 -> 9475  (OVS Exporter)"
	@echo "  6641 -> 6641  (OVN NB)"
	@echo "  6642 -> 6642  (OVN SB)"
	@echo ""
	@echo "VM Management:"
	@echo "  limactl list          # List VMs"
	@echo "  limactl shell ovs-lab # SSH into VM"
	@echo "  limactl stop ovs-lab  # Stop VM"

# Install Lima if not present
.PHONY: install-lima
install-lima:
	@if ! command -v limactl &> /dev/null; then \
		echo "Installing Lima..."; \
		brew install lima; \
	else \
		echo "Lima is already installed"; \
	fi