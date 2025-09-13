# OVS Container Lab - Simplified Makefile
# Multi-VPC Cloud Network Simulation with OVN/OVS

.PHONY: help up down status logs clean test demo stress chaos

# Default target
help:
	@echo "OVS Container Lab - Multi-VPC Cloud Network Simulation"
	@echo "======================================================"
	@echo ""
	@echo "BASIC OPERATIONS:"
	@echo "  make up         - Start entire VPC infrastructure"
	@echo "  make down       - Stop all containers"  
	@echo "  make status     - Show infrastructure status"
	@echo "  make logs       - Follow container logs"
	@echo "  make clean      - Remove all containers and volumes"
	@echo ""
	@echo "TESTING & DEMOS:"
	@echo "  make test       - Run connectivity tests"
	@echo "  make demo       - Run 10-minute demo with traffic"
	@echo "  make demo-full  - Run 30-minute comprehensive demo"
	@echo ""
	@echo "STRESS TESTING:"
	@echo "  make stress     - Run 2-minute stress test"
	@echo "  make stress-heavy - Run 5-minute heavy stress test"
	@echo "  make chaos      - Run chaos engineering scenarios"
	@echo ""
	@echo "MONITORING:"
	@echo "  make dashboard  - Open Grafana dashboard"
	@echo "  make metrics    - Show current metrics"
	@echo ""
	@echo "DEVELOPMENT:"
	@echo "  make shell-ovn  - Shell into OVN controller"
	@echo "  make shell-ovs  - Shell into OVS container" 
	@echo "  make build      - Rebuild all images"

# ==================== BASIC OPERATIONS ====================

up:
	@echo "Starting Multi-VPC Infrastructure..."
	@docker compose up -d ovn-central
	@sleep 5
	@docker compose up -d ovs-vpc-a ovs-vpc-b
	@sleep 5
	@docker compose up -d vrouter-vpc-a vrouter-vpc-b
	@sleep 3
	@echo "Configuring OVN topology..."
	@./scripts/setup-ovn-topology.sh
	@echo "Configuring vRouter routing..."
	@./scripts/setup-vrouters.sh
	@echo "Setting up test workloads..."
	@./scripts/setup-test-workloads.sh > /dev/null 2>&1
	@docker compose up -d prometheus grafana
	@echo ""
	@echo "✅ Infrastructure Ready!"
	@echo ""
	@echo "Access Points:"
	@echo "  Grafana:    http://localhost:3000 (admin/admin)"
	@echo "  Prometheus: http://localhost:9090"
	@echo "  OVS Metrics: http://localhost:9475/metrics (VPC-A), http://localhost:9477/metrics (VPC-B)"
	@echo ""
	@echo "Run 'make test' to verify connectivity"

down:
	@echo "Stopping all containers..."
	@docker compose down
	@echo "Infrastructure stopped"

status:
	@echo "=== Infrastructure Status ==="
	@echo ""
	@echo "OVN Controller:"
	@docker exec ovn-central ovn-nbctl show 2>/dev/null | head -10 || echo "  ❌ Not running"
	@echo ""
	@echo "OVS Instances:"
	@docker ps --format "table {{.Names}}\t{{.Status}}" | grep -E "(ovs-vpc|ovn)" || echo "  None running"
	@echo ""
	@echo "vRouters:"
	@docker ps --format "table {{.Names}}\t{{.Status}}" | grep vrouter || echo "  None running"
	@echo ""
	@echo "Inter-VPC Connectivity:"
	@docker exec ovs-vpc-a ip netns exec vpc-a-web-1 ping -c 1 -W 1 10.1.1.10 >/dev/null 2>&1 && echo "  ✅ Working" || echo "  ❌ Not working"

logs:
	@docker compose logs -f

clean:
	@echo "Cleaning up all containers and volumes..."
	@docker compose down -v --remove-orphans
	@docker kill $$(docker ps -q --filter "label=ovs-lab") 2>/dev/null || true
	@docker network prune -f
	@echo "Cleanup complete"

# ==================== TESTING & DEMOS ====================

test:
	@echo "Testing VPC connectivity..."
	@echo ""
	@echo "1. VPC-A internal (web to app):"
	@docker exec ovs-vpc-a ip netns exec vpc-a-web-1 ping -c 2 -W 1 10.0.2.10 || echo "  ❌ Failed"
	@echo ""
	@echo "2. VPC-B internal (web to app):"
	@docker exec ovs-vpc-b ip netns exec vpc-b-web-1 ping -c 2 -W 1 10.1.2.10 || echo "  ❌ Failed"
	@echo ""
	@echo "3. Inter-VPC routing (VPC-A to VPC-B):"
	@docker exec ovs-vpc-a ip netns exec vpc-a-web-1 ping -c 2 -W 1 10.1.1.10 || echo "  ❌ Failed"
	@echo ""
	@echo "4. GENEVE tunnels:"
	@docker exec ovs-vpc-a ovs-vsctl show | grep -c "type: geneve" | xargs -I {} echo "  {} tunnels active"

demo:
	@echo "Starting 10-minute demo..."
	@./scripts/run-demo.sh standard

demo-full:
	@echo "Starting 30-minute comprehensive demo..."
	@./scripts/run-demo.sh comprehensive

# ==================== STRESS TESTING ====================

stress:
	@echo "Running 2-minute stress test..."
	@./scripts/stress-test.sh standard 120

stress-heavy:
	@echo "Running 5-minute heavy stress test..."
	@./scripts/stress-test.sh heavy 300

chaos:
	@echo "Select chaos scenario:"
	@echo "  1) Packet Loss (30%)"
	@echo "  2) CPU Stress"
	@echo "  3) Memory Pressure"
	@echo "  4) Network Partition"
	@echo "  5) Cascading Failure"
	@read -p "Enter choice [1-5]: " choice; \
	./scripts/chaos-scenario.sh $$choice

# ==================== MONITORING ====================

dashboard:
	@echo "Opening Grafana dashboard..."
	@open http://localhost:3000 2>/dev/null || \
	 xdg-open http://localhost:3000 2>/dev/null || \
	 echo "Open: http://localhost:3000 (admin/admin)"

metrics:
	@echo "=== Current Metrics ==="
	@echo ""
	@echo "OVN Statistics:"
	@curl -s http://localhost:9476/metrics | grep "ovn_" | head -5
	@echo ""
	@echo "Traffic Rates:"
	@curl -s http://localhost:9476/metrics | grep "ovs_interface_rx_packets" | head -5
	@echo ""
	@echo "Active Flows:"
	@curl -s http://localhost:9476/metrics | grep "ovs_flow_count"

# ==================== DEVELOPMENT ====================

shell-ovn:
	@docker exec -it ovn-central bash

shell-ovs:
	@docker exec -it ovs-vpc-a bash

shell-router:
	@docker exec -it vrouter-vpc-a bash

build:
	@echo "Building all images..."
	@docker compose build
	@echo "Build complete"

# ==================== ADVANCED ====================

.PHONY: stop start restart watch-traffic watch-flows debug

stop:
	@docker compose stop

start:
	@docker compose start

restart: down up

watch-traffic:
	@watch -n1 'curl -s http://localhost:9476/metrics | grep -E "ovs_interface_(rx|tx)_packets" | head -10'

watch-flows:
	@docker exec ovs-vpc-a watch -n1 'ovs-ofctl dump-flows br-vpc-a | grep n_packets'

debug:
	@echo "=== Debug Information ==="
	@echo ""
	@echo "OVN Northbound DB:"
	@docker exec ovn-central ovn-nbctl show
	@echo ""
	@echo "OVN Southbound DB:"
	@docker exec ovn-central ovn-sbctl show
	@echo ""
	@echo "OVS-VPC-A Bridges:"
	@docker exec ovs-vpc-a ovs-vsctl show
	@echo ""
	@echo "vRouter-A Routes:"
	@docker exec vrouter-vpc-a ip route | grep -E "10\."