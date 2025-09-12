# OVS Container Lab Makefile
# Simplifies common operations and reduces shell script dependencies

.PHONY: help up down start stop restart status logs demo demo-quick demo-full \
        traffic-high traffic-low chaos clean build test-containers traffic-generator \
        connect-containers dashboard metrics

# Default target
help:
	@echo "OVS Container Lab - Available Commands"
	@echo "======================================"
	@echo ""
	@echo "Core Operations:"
	@echo "  make up                 - Start monitoring stack (OVS, Prometheus, Grafana)"
	@echo "  make down               - Stop all containers"
	@echo "  make restart            - Restart all services"
	@echo "  make status             - Show container status"
	@echo "  make logs               - Follow container logs"
	@echo ""
	@echo "Demo Operations:"
	@echo "  make demo               - Run quick 10-minute demo"
	@echo "  make demo-quick         - Run quick 10-minute demo"
	@echo "  make demo-full          - Run full 30-minute demo"
	@echo "  make demo-status        - Check demo status"
	@echo "  make demo-stop          - Stop all demo components"
	@echo ""
	@echo "Traffic Generation:"
	@echo "  make traffic-high       - Start high-intensity traffic (200k+ pps)"
	@echo "  make traffic-low        - Start low-intensity traffic (10k pps)"
	@echo "  make traffic-stop       - Stop traffic generation"
	@echo ""
	@echo "Chaos Engineering:"
	@echo "  make chaos SCENARIO=packet-loss-30 DURATION=120"
	@echo "                          - Run chaos scenario (default: packet-loss-30 for 120s)"
	@echo "  make chaos-stop         - Stop all chaos scenarios"
	@echo ""
	@echo "Utility Commands:"
	@echo "  make build              - Build all custom images"
	@echo "  make clean              - Clean up everything (containers, volumes, images)"
	@echo "  make dashboard          - Open Grafana dashboards in browser"
	@echo "  make metrics            - Show current OVS metrics"
	@echo "  make test-containers    - Start test containers"
	@echo "  make connect-containers - Connect containers to OVS bridge"

# Core operations
up:
	@echo "Starting OVS monitoring stack..."
	@docker compose up -d
	@echo "Waiting for services to initialize..."
	@sleep 5
	@docker compose ps
	@echo ""
	@echo "Access points:"
	@echo "  Grafana:    http://localhost:3000 (admin/admin)"
	@echo "  Prometheus: http://localhost:9090"
	@echo "  OVS Metrics: http://localhost:9475/metrics"

down:
	@echo "Stopping all containers..."
	@docker compose --profile testing --profile traffic --profile chaos down

stop:
	@echo "Stopping all containers..."
	@docker compose --profile testing --profile traffic --profile chaos stop

start:
	@echo "Starting all containers..."
	@docker compose --profile testing --profile traffic --profile chaos start

restart: down up

status:
	@docker compose ps
	@echo ""
	@echo "OVS Bridge Status:"
	@docker exec ovs ovs-vsctl show 2>/dev/null || echo "OVS not running"

logs:
	@docker compose logs -f

# Demo operations
demo: demo-quick

demo-quick:
	@echo "Starting quick demo (10 minutes)..."
	@./scripts/network-simulation/demo.sh quick-demo

demo-full:
	@echo "Starting full demo (30 minutes)..."
	@./scripts/network-simulation/demo.sh full-demo

demo-status:
	@./scripts/network-simulation/demo.sh status

demo-stop:
	@./scripts/network-simulation/demo.sh stop

# Traffic generation
traffic-high: traffic-generator
	@echo "Starting high-intensity traffic generation (200k+ pps)..."
	@./scripts/network-simulation/demo.sh traffic-only high

traffic-low: traffic-generator
	@echo "Starting low-intensity traffic generation (10k pps)..."
	@./scripts/network-simulation/demo.sh traffic-only low

traffic-stop:
	@echo "Stopping traffic generation..."
	@docker exec traffic-generator pkill -f "hping3|python3" 2>/dev/null || true
	@docker compose --profile traffic stop

traffic-generator:
	@echo "Ensuring traffic generator is running..."
	@docker compose --profile traffic up -d traffic-generator
	@sleep 2
	@./scripts/ovs-docker-connect.sh traffic-generator 172.18.0.30 2>/dev/null || true

# Chaos engineering
SCENARIO ?= packet-loss-30
DURATION ?= 120

chaos:
	@echo "Running chaos scenario: $(SCENARIO) for $(DURATION) seconds..."
	@./scripts/network-simulation/demo.sh chaos-only $(SCENARIO) $(DURATION)

chaos-stop:
	@echo "Stopping all chaos scenarios..."
	@docker kill $$(docker ps -q --filter "name=chaos-") 2>/dev/null || true
	@docker kill $$(docker ps -q --filter "name=demo-pumba-") 2>/dev/null || true

# Test containers
test-containers:
	@echo "Starting test containers..."
	@docker compose --profile testing up -d
	@sleep 2
	@./scripts/network-simulation/container-setup.sh setup

connect-containers:
	@echo "Connecting containers to OVS bridge..."
	@./scripts/ovs-docker-connect.sh test-container-1 172.18.0.10
	@./scripts/ovs-docker-connect.sh test-container-2 172.18.0.11
	@./scripts/ovs-docker-connect.sh test-container-3 172.18.0.12

# Build operations
build:
	@echo "Building custom images..."
	@docker compose build ovs
	@docker compose build ovs_exporter
	@docker compose build traffic-generator
	@echo "Build complete!"

# Utility commands
dashboard:
	@echo "Opening Grafana dashboards..."
	@open http://localhost:3000/d/ovs-underlay-failure/ovs-underlay-failure-detection 2>/dev/null || \
	 xdg-open http://localhost:3000/d/ovs-underlay-failure/ovs-underlay-failure-detection 2>/dev/null || \
	 echo "Please open: http://localhost:3000 (admin/admin)"

metrics:
	@echo "Current OVS Metrics:"
	@echo "==================="
	@curl -s http://localhost:9475/metrics | grep -E "ovs_interface_(rx|tx)_packets{" | head -10 || \
	 echo "Metrics not available. Is the stack running?"
	@echo ""
	@echo "Packet Rate:"
	@docker exec ovs sh -c 'p1=$$(ovs-ofctl -O OpenFlow13 dump-flows ovs-br0 | grep -o "n_packets=[0-9]*" | cut -d= -f2); \
	 sleep 2; \
	 p2=$$(ovs-ofctl -O OpenFlow13 dump-flows ovs-br0 | grep -o "n_packets=[0-9]*" | cut -d= -f2); \
	 echo "$$((($${p2:-0} - $${p1:-0}) / 2)) pps"' 2>/dev/null || echo "Unable to calculate"

clean:
	@echo "WARNING: This will remove all containers, volumes, and custom images!"
	@echo "Press Ctrl+C to cancel, or wait 5 seconds to continue..."
	@sleep 5
	@echo "Cleaning up..."
	@docker compose --profile testing --profile traffic --profile chaos down -v
	@docker rmi ovs-container-lab-traffic-generator 2>/dev/null || true
	@docker rmi ovs-container-lab-ovs 2>/dev/null || true
	@docker rmi ovs-container-lab-ovs_exporter 2>/dev/null || true
	@echo "Cleanup complete!"

# Development helpers
.PHONY: shell-ovs shell-traffic lint

shell-ovs:
	@docker exec -it ovs bash

shell-traffic:
	@docker exec -it traffic-generator bash

lint:
	@echo "Checking shell scripts..."
	@shellcheck scripts/*.sh scripts/network-simulation/*.sh 2>/dev/null || \
	 echo "shellcheck not installed - skipping lint"

# Performance monitoring
.PHONY: watch-metrics watch-flows watch-drops

watch-metrics:
	@watch -n1 'curl -s http://localhost:9475/metrics | grep -E "ovs_interface_(rx|tx)_packets" | head -10'

watch-flows:
	@docker exec ovs watch -n1 'ovs-ofctl -O OpenFlow13 dump-flows ovs-br0 | grep n_packets'

watch-drops:
	@docker exec ovs watch -n1 'ovs-ofctl -O OpenFlow13 dump-ports ovs-br0 | grep drop'