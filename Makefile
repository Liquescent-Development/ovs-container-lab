# OVS Container Lab - Simplified Makefile
# Clean, single-path workflow for all operations

.PHONY: help up down status clean check traffic-run traffic-chaos traffic-stop

# Default configuration file
# All configuration is now in docker-compose.yml

# Cache directory for downloads (on macOS host)
CACHE_DIR = .downloads

# Default target
help:
	@echo "OVS Container Lab - Simplified Commands"
	@echo "========================================"
	@echo ""
	@echo "PREPARATION:"
	@echo "  make prep         - Download and cache all required files"
	@echo "  make download     - Same as prep"
	@echo "  make show-downloads - Show what's cached"
	@echo "  make clean-downloads - Remove cached downloads"
	@echo ""
	@echo "CORE COMMANDS:"
	@echo "  make up           - Start everything (VM, containers, networking)"
	@echo "  make up DEBUG=1   - Start with detailed provisioning output"
	@echo "  make status       - Show status of entire lab"
	@echo "  make down         - Stop containers (VM stays running)"
	@echo "  make clean        - Clean everything including VM (keeps downloads)"
	@echo "  make check        - Verify configuration and topology"
	@echo "  make go-version   - Check Go version in VM"
	@echo ""
	@echo "TRAFFIC GENERATION (using ntttcp):"
	@echo "  make traffic-standard - Generate standard traffic (100 Mbps, 4 threads)"
	@echo "  make traffic-chaos    - Generate chaos traffic (1 Gbps, 16 threads)"
	@echo "  make traffic-stop     - Stop all traffic generation"
	@echo "  make traffic-status   - Check traffic generation status"
	@echo ""
	@echo "CHAOS ENGINEERING:"
	@echo "  make chaos-inject     - Run Pumba network chaos (5 min)"
	@echo "  make chaos-info       - Show available containers for chaos"
	@echo "  make chaos-loss       - Simulate 30% packet loss"
	@echo "  make chaos-delay      - Add 100ms network delay"
	@echo "  make chaos-bandwidth  - Limit bandwidth to 1mbit"
	@echo "  make chaos-partition  - Create network partition"
	@echo "  make chaos-corruption - Introduce packet corruption"
	@echo "  make chaos-duplication - Introduce packet duplication"
	@echo "  make chaos-underlay-down - Simulate underlay link failure (tunnel down)"
	@echo "  make chaos-vlan-down - Simulate VLAN tag mismatch on underlay"
	@echo "  make chaos-tunnel-status - Check OVS/OVN tunnel status"
	@echo "  make setup-tunnels    - Create GENEVE tunnels for testing"
	@echo "  make remove-tunnels   - Remove all GENEVE tunnels"
	@echo ""
	@echo "MONITORING:"
	@echo "  make logs             - Follow container logs"
	@echo "  make dashboard        - Open Grafana (http://localhost:3000)"
	@echo "  make metrics          - Show current metrics"
	@echo "  make setup-monitoring - Setup OVS/OVN exporters"
	@echo "  make monitoring-check - Check monitoring exporters status"
	@echo ""
	@echo "PLUGIN MANAGEMENT:"
	@echo "  make plugin-install   - Install OVS network plugin"
	@echo "  make plugin-uninstall - Uninstall OVS network plugin"
	@echo "  make plugin-status    - Check plugin status"
	@echo ""
	@echo "VM MANAGEMENT:"
	@echo "  make vpc-vms          - Create libvirt VMs in VPCs"
	@echo "  make vpc-vms-status   - Check VM status"
	@echo "  make vpc-vms-stop     - Stop running VMs"
	@echo "  make vpc-vms-start    - Start VMs"
	@echo "  make vpc-vms-restart  - Restart VMs"
	@echo "  make vpc-vms-destroy  - Remove all VMs completely"
	@echo "  make vpc-vms-watch-boot - Create/restart VMs and watch them boot (recommended)"
	@echo ""
	@echo "VM CONSOLE ACCESS:"
	@echo "  make vpc-a-console    - Connect to vpc-a-vm console"
	@echo "  make vpc-b-console    - Connect to vpc-b-vm console"
	@echo "  make vpc-vms-tmux     - Open VMs in tmux windows"
	@echo "  make vpc-vms-tmux-split - Open VMs in split panes (side-by-side)"
	@echo "  make vpc-vms-attach   - Reattach to existing tmux session"
	@echo "  make fix-vm-network   - Fix VM network (OVN binding + offloading)"
	@echo "  make debug-vm-network - Debug VM network configuration"
	@echo "  make fix-vm-offload   - Fix VM TAP interface offloading for TCP"
	@echo "  make check-vm-offload - Check VM TAP interface offloading status"
	@echo ""
	@echo "DEVELOPMENT:"
	@echo "  make shell-vm    - SSH into Lima VM"
	@echo "  make shell-ovn   - Shell into OVN container (if exists)"
	@echo "  make test-unit   - Run unit tests for plugin"
	@echo "  make test-full   - Run all tests including integration"
	@echo ""
	@echo "Configuration: docker-compose.yml"

# ==================== DOWNLOAD CACHE ====================

prep: download
	@echo "✅ All downloads cached and ready"

download: download-docker download-go download-ubuntu-image
	@echo "✅ All downloads completed"

download-docker:
	@echo "📦 Caching Docker installation script..."
	@mkdir -p $(CACHE_DIR)
	@if [ ! -f $(CACHE_DIR)/get-docker.sh ]; then \
		echo "  Downloading Docker install script..."; \
		curl -fsSL https://get.docker.com -o $(CACHE_DIR)/get-docker.sh; \
		chmod +x $(CACHE_DIR)/get-docker.sh; \
		echo "  ✓ Docker script cached"; \
	else \
		echo "  ✓ Docker script already cached"; \
	fi

download-go:
	@echo "📦 Caching Go installation for host architecture..."
	@mkdir -p $(CACHE_DIR)
	@GO_VERSION="1.25.1"; \
	if [ "$(shell uname -m)" = "arm64" ] || [ "$(shell uname -m)" = "aarch64" ]; then \
		ARCH="arm64"; \
		echo "  Detected Apple Silicon Mac"; \
	else \
		ARCH="amd64"; \
		echo "  Detected Intel Mac"; \
	fi; \
	FILE="go$${GO_VERSION}.linux-$${ARCH}.tar.gz"; \
	if [ ! -f $(CACHE_DIR)/$${FILE} ]; then \
		echo "  Downloading Go 1.25.1 for Linux $${ARCH}..."; \
		curl -L "https://go.dev/dl/$${FILE}" -o $(CACHE_DIR)/$${FILE}; \
		echo "  ✓ Go $${ARCH} cached"; \
	else \
		echo "  ✓ Go $${ARCH} already cached"; \
	fi

download-ubuntu-image:
	@echo "📦 Caching Ubuntu cloud image for host architecture..."
	@mkdir -p $(CACHE_DIR)/vm-images
	@if [ "$(shell uname -m)" = "arm64" ] || [ "$(shell uname -m)" = "aarch64" ]; then \
		if [ ! -f $(CACHE_DIR)/vm-images/ubuntu-24.04-server-cloudimg-arm64.img ]; then \
			echo "  Downloading Ubuntu 24.04 cloud image (arm64) for Apple Silicon..."; \
			curl -L "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-arm64.img" \
				-o $(CACHE_DIR)/vm-images/ubuntu-24.04-server-cloudimg-arm64.img; \
			echo "  ✓ Ubuntu arm64 image cached"; \
		else \
			echo "  ✓ Ubuntu arm64 image already cached"; \
		fi; \
	else \
		if [ ! -f $(CACHE_DIR)/vm-images/ubuntu-24.04-server-cloudimg-amd64.img ]; then \
			echo "  Downloading Ubuntu 24.04 cloud image (amd64) for Intel..."; \
			curl -L "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-amd64.img" \
				-o $(CACHE_DIR)/vm-images/ubuntu-24.04-server-cloudimg-amd64.img; \
			echo "  ✓ Ubuntu amd64 image cached"; \
		else \
			echo "  ✓ Ubuntu amd64 image already cached"; \
		fi; \
	fi

clean-downloads:
	@echo "🗑️  Cleaning download cache..."
	@echo "  Removing .downloads directory and all contents..."
	@rm -rf .downloads
	@echo "✅ Download cache cleaned"

show-downloads:
	@echo "📦 Cached downloads:"
	@if [ -d .downloads ]; then \
		echo "  Directory: .downloads/"; \
		find .downloads -type f -exec du -h {} \; | sed 's|.downloads/||' | sed 's/^/    /'; \
		echo ""; \
		echo "  Total size: $$(du -sh .downloads | cut -f1)"; \
	else \
		echo "  No downloads cached (run 'make prep' to cache)"; \
	fi

# ==================== CORE COMMANDS ====================

up: _ensure-vm
	@echo "🚀 Starting OVS Container Lab..."
	@echo ""
	@echo "Step 1: Building OVN central image..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker build -t ovn-central:latest ./ovn-container
	@echo ""
	@echo "Step 2: Installing OVS network plugin..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py install-plugin
	@echo ""
	@echo "Step 3: Setting up monitoring exporters..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py setup-monitoring
	@echo ""
	@echo "Step 4: Starting containers (networks created automatically by docker-compose)..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker compose up -d
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker compose --profile testing --profile vpc --profile traffic --profile chaos up -d
	@echo ""
	@echo "Step 5: Setting up OVS chassis connection to OVN..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py setup-chassis
	@echo ""
	@echo "Step 6: Connecting Prometheus to OVN network..."
	@limactl shell ovs-lab -- bash -c "sudo docker network connect transit-overlay prometheus 2>/dev/null || echo 'Already connected or network not ready yet'"
	@echo ""
	@echo "✅ OVS Container Lab is ready!"
	@echo "  Grafana:    http://localhost:3000 (admin/admin)"
	@echo "  Prometheus: http://localhost:9090"

# ==================== PLUGIN MANAGEMENT ====================

plugin-install: _ensure-vm
	@echo "🔌 Installing OVS Container Network plugin..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py install-plugin

plugin-uninstall: _ensure-vm
	@echo "🔌 Uninstalling OVS Container Network plugin..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py uninstall-plugin

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

check: _ensure-vm
	@echo "🔍 Running network diagnostics..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py check

# ==================== TRAFFIC GENERATION ====================

traffic-run: _ensure-vm
	@echo "📡 Generating normal traffic across VPCs..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py traffic-start --mode standard
	@echo ""
	@echo "✅ Standard traffic generation started!"
	@echo ""
	@echo "Monitor in Grafana: http://localhost:3000"
	@echo "To stop traffic: make traffic-stop"

traffic-standard: traffic-run  # Alias for consistency

traffic-chaos: _ensure-vm
	@echo "🔥 CHAOS MODE - Heavy internal traffic generation..."
	@echo "WARNING: This will generate heavy internal traffic to stress test the network!"
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py traffic-start --mode chaos
	@echo ""
	@echo "✅ Chaos traffic generation started!"
	@echo ""
	@echo "Monitor in Grafana: http://localhost:3000"
	@echo "To stop traffic: make traffic-stop"
	@echo ""
	@echo "To add network failures: make chaos-inject"

chaos-inject: _ensure-vm
	@echo "💥 Injecting network chaos with Pumba..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- "nohup sudo python3 orchestrator.py chaos mixed --duration 300 > /tmp/chaos.log 2>&1 &"
	@echo "✅ Network chaos injection started (5 minutes)"
	@echo "Check logs: tail -f /tmp/chaos.log in Lima VM"

traffic-stop: _ensure-vm
	@echo "🛑 Stopping all traffic generation..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py traffic-stop

traffic-status: _ensure-vm
	@echo "🔍 Checking traffic generation status..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py traffic-status

# ==================== CHAOS ENGINEERING ====================

chaos-info: _ensure-vm
	@echo "🔍 Discovering containers for chaos testing..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py chaos-info

chaos-loss: _ensure-vm
	@echo "🔥 Simulating 30% packet loss..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py chaos packet-loss --duration 60

chaos-delay: _ensure-vm
	@echo "⏰ Adding 100ms network delay..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py chaos latency --duration 60

chaos-bandwidth: _ensure-vm
	@echo "🚦 Limiting bandwidth to 1mbit..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py chaos bandwidth --duration 60

chaos-partition: _ensure-vm
	@echo "🔌 Creating network partition..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py chaos partition --duration 60

chaos-corruption: _ensure-vm
	@echo "💥 Introducing packet corruption..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py chaos corruption --duration 60

chaos-duplication: _ensure-vm
	@echo "👥 Introducing packet duplication..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py chaos duplication --duration 60

chaos-underlay-down: _ensure-vm
	@echo "🔌 CHAOS: Simulating underlay link failure (tunnel down)..."
	@echo "This will block GENEVE tunnel traffic, causing overlay network failure"
	@echo ""
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 underlay_chaos.py link-down --duration 60
	@echo "✅ Underlay link failure test completed"

chaos-vlan-down: _ensure-vm
	@echo "🏷️  CHAOS: Simulating VLAN tag mismatch on underlay..."
	@echo "This simulates VLAN configuration errors that drop tunnel packets"
	@echo ""
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 underlay_chaos.py vlan-mismatch --duration 60
	@echo "✅ VLAN mismatch test completed"

chaos-tunnel-status: _ensure-vm
	@echo "📊 Checking tunnel status..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 underlay_chaos.py status

setup-tunnels: _ensure-vm
	@echo "🚇 Setting up GENEVE tunnels for demonstration..."
	@echo "This creates real tunnel interfaces that will appear in OVS metrics"
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 setup_tunnels.py setup
	@echo ""
	@echo "✅ Tunnels created! Check metrics at http://localhost:9475/metrics"
	@echo "Look for 'ovs_interface' metrics with interface names starting with 'geneve-'"

remove-tunnels: _ensure-vm
	@echo "🧹 Removing all GENEVE tunnels..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 setup_tunnels.py remove

tunnel-status: _ensure-vm
	@echo "📊 Displaying GENEVE tunnel status..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 setup_tunnels.py status

# ==================== VM MANAGEMENT ====================

vpc-vms: _ensure-vm
	@echo "🖥️  Creating libvirt VMs in VPCs..."
	@echo "Ensuring libvirtd is running..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo systemctl start libvirtd
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 vm-manager/vm_manager.py create-all"
	@echo "🔧 Fixing VM network offloading for TCP traffic..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 fix_vm_offloading.py
	@echo "✅ VPC VMs created and connected with proper offloading settings"

vpc-vms-status: _ensure-vm
	@echo "📊 Checking VM status..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo systemctl start libvirtd 2>/dev/null || true
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo virsh list --all

vpc-vms-destroy: _ensure-vm
	@echo "🗑️  Destroying VPC VMs..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo systemctl start libvirtd 2>/dev/null || true
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 vm-manager/vm_manager.py destroy-all"
	@echo "✅ VPC VMs destroyed"

vpc-vms-stop: _ensure-vm
	@echo "⏹️  Stopping VPC VMs..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo virsh destroy vpc-a-vm 2>/dev/null || true
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo virsh destroy vpc-b-vm 2>/dev/null || true
	@echo "✅ VPC VMs stopped"

vpc-vms-start: _ensure-vm
	@echo "▶️  Starting VPC VMs..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo virsh start vpc-a-vm 2>/dev/null || true
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo virsh start vpc-b-vm 2>/dev/null || true
	@echo "✅ VPC VMs started"

vpc-vms-restart: vpc-vms-stop vpc-vms-start
	@echo "✅ VPC VMs restarted"

vpc-vms-create-stopped: _ensure-vm
	@echo "🖥️  Creating VPC VMs (without starting)..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo systemctl start libvirtd
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c "cd /home/lima/code/ovs-container-lab && sudo python3 vm-manager/vm_manager.py create-all"
	@echo "⏹️  Stopping VMs to prepare for console monitoring..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo virsh destroy vpc-a-vm 2>/dev/null || true
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo virsh destroy vpc-b-vm 2>/dev/null || true
	@echo "✅ VPC VMs created and stopped. Ready for console monitoring."

vpc-vms-console: _ensure-vm
	@if [ -z "$(VM)" ]; then \
		echo "❌ Error: VM name required. Use: make vpc-vms-console VM=vpc-a-vm"; \
		exit 1; \
	fi
	@echo "🖥️  Connecting to $(VM) console (use Ctrl+] to exit)..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo systemctl start libvirtd 2>/dev/null || true
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo virsh console $(VM)

vpc-a-console: _ensure-vm
	@echo "🖥️  Connecting to vpc-a-vm console (use Ctrl+] to exit)..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo systemctl start libvirtd 2>/dev/null || true
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo virsh console vpc-a-vm

vpc-b-console: _ensure-vm
	@echo "🖥️  Connecting to vpc-b-vm console (use Ctrl+] to exit)..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo systemctl start libvirtd 2>/dev/null || true
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo virsh console vpc-b-vm

vpc-vms-tmux: _ensure-vm
	@echo "🖥️  Starting tmux session with VM consoles..."
	@echo "Use 'Ctrl+B, n' to switch windows, 'Ctrl+B, d' to detach"
	@echo "For iTerm2 integration: 'Ctrl+B, :' then 'set -g @optionCC -cc \"\"'"
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c '\
		sudo systemctl start libvirtd 2>/dev/null || true; \
		echo "Ensuring VMs are running..."; \
		sudo virsh start vpc-a-vm 2>/dev/null || true; \
		sudo virsh start vpc-b-vm 2>/dev/null || true; \
		sleep 2; \
		tmux has-session -t vm-consoles 2>/dev/null && tmux kill-session -t vm-consoles; \
		tmux new-session -d -s vm-consoles -n vpc-a "sudo virsh console vpc-a-vm --force"; \
		tmux new-window -t vm-consoles -n vpc-b "sudo virsh console vpc-b-vm --force"; \
		tmux attach-session -t vm-consoles'

vpc-vms-tmux-split: _ensure-vm
	@echo "🖥️  Starting tmux session with split panes for VM consoles..."
	@echo "Use 'Ctrl+B, o' to switch panes, 'Ctrl+B, d' to detach"
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c '\
		sudo systemctl start libvirtd 2>/dev/null || true; \
		tmux has-session -t vm-consoles 2>/dev/null && tmux kill-session -t vm-consoles; \
		tmux new-session -d -s vm-consoles "sudo virsh console vpc-a-vm"; \
		tmux split-window -h -t vm-consoles "sudo virsh console vpc-b-vm"; \
		tmux select-layout -t vm-consoles even-horizontal; \
		tmux attach-session -t vm-consoles'

vpc-vms-attach: _ensure-vm
	@echo "🖥️  Attaching to existing tmux session..."
	@echo ""
	@echo "VM Login Credentials:"
	@echo "  Username: admin"
	@echo "  Password: admin"
	@echo ""
	@echo "NOTE: If you see no prompt, press Enter. Cloud-init takes ~30-60 seconds to complete."
	@echo "      You may see boot messages initially - this is normal."
	@echo ""
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- tmux attach-session -t vm-consoles || echo "No tmux session found. Run 'make vpc-vms-tmux' first."

vpc-vms-list-sessions: _ensure-vm
	@echo "📋 Active tmux sessions:"
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- tmux list-sessions 2>/dev/null || echo "No active tmux sessions"

vpc-vms-status: _ensure-vm
	@echo "🔍 Checking VM status..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c '\
		echo "VM States:"; \
		sudo virsh list --all | grep vpc; \
		echo ""; \
		echo "Checking if VMs are ready for login (cloud-init completion):"; \
		for vm in vpc-a-vm vpc-b-vm; do \
			if sudo virsh list --name | grep -q $$vm; then \
				echo -n "  $$vm: "; \
				if sudo virsh qemu-agent-command $$vm "{\"execute\":\"guest-ping\"}" 2>/dev/null | grep -q return; then \
					echo "✅ Ready (guest agent responding)"; \
				elif sudo virsh dominfo $$vm | grep -q "State.*running"; then \
					echo "⏳ Booting (cloud-init in progress, wait 30-60s)"; \
				else \
					echo "❌ Not running"; \
				fi; \
			fi; \
		done; \
		echo ""; \
		echo "Login: username=admin password=admin"'

fix-vm-network: _ensure-vm
	@echo "🔧 Fixing VM network configuration for OVN..."
	@echo "This will set up proper OVN bindings and fix offloading"
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c '\
		for vm_name in vpc-a-vm vpc-b-vm; do \
			echo "Checking $$vm_name..."; \
			if sudo virsh list --name | grep -q "$$vm_name"; then \
				tap=$$(sudo virsh dumpxml $$vm_name | grep -oP "target dev='"'"'(tap[^'"'"']+|vnet[^'"'"']+)" | cut -d"'"'"'" -f2); \
				if [ -n "$$tap" ]; then \
					echo "  Found interface: $$tap"; \
					echo "  Setting OVN binding..."; \
					sudo ovs-vsctl set Interface $$tap external_ids:iface-id=lsp-$$vm_name; \
					echo "  Disabling offloading..."; \
					for feature in rx tx sg tso gso gro; do \
						sudo ethtool -K $$tap $$feature off 2>/dev/null; \
					done; \
					echo "  ✅ $$vm_name fixed"; \
				else \
					echo "  ⚠️  No TAP interface found for $$vm_name"; \
				fi; \
			else \
				echo "  ⚠️  $$vm_name not running"; \
			fi; \
		done'
	@echo "✅ VM network configuration fixed"
	@echo "VMs should now be able to ping their gateways"

debug-vm-network: _ensure-vm
	@echo "🔍 Debugging VM network configuration..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 debug_vm_network.py

fix-tcp: _ensure-vm
	@echo "🔧 Fixing TCP connectivity between containers and VMs..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash fix_tcp_issue.sh

fix-vm-userspace: _ensure-vm
	@echo "🔧 Ensuring VMs use OVS userspace datapath..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash fix_userspace_datapath.sh

fix-vm-offload: _ensure-vm
	@echo "🔧 Fixing VM TAP interface offloading settings..."
	@echo "This will disable offloading features that prevent TCP traffic from working"
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 fix_vm_offloading.py
	@echo ""
	@echo "You can now test TCP connectivity with: make test"

check-vm-offload: _ensure-vm
	@echo "📊 Checking VM TAP interface offloading status..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 fix_vm_offloading.py --check-only

monitor-vm-offload: _ensure-vm
	@echo "👀 Monitoring and fixing VM interfaces as they appear..."
	@echo "This will continuously check for new VM interfaces and fix their offloading"
	@echo "Press Ctrl+C to stop"
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 fix_vm_offloading.py --monitor

vpc-vms-watch-boot: _ensure-vm
	@echo "🚀 Preparing to watch VMs boot..."
	@echo "Step 1: Ensuring VMs exist..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c '\
		sudo systemctl start libvirtd; \
		if ! sudo virsh list --all | grep -q vpc-a-vm; then \
			echo "Creating VMs..."; \
			cd /home/lima/code/ovs-container-lab && sudo python3 vm-manager/vm_manager.py create-all; \
		else \
			echo "VMs already exist, stopping them for fresh boot..."; \
			sudo virsh destroy vpc-a-vm 2>/dev/null || true; \
			sudo virsh destroy vpc-b-vm 2>/dev/null || true; \
		fi'
	@echo "Step 2: Starting tmux with consoles and booting VMs..."
	@echo "You will see both VMs boot side-by-side. Use Ctrl+B,d to detach."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c '\
		tmux has-session -t vm-boot 2>/dev/null && tmux kill-session -t vm-boot; \
		tmux new-session -d -s vm-boot "echo Starting vpc-a-vm... && sleep 1 && sudo virsh start vpc-a-vm && sudo virsh console vpc-a-vm"; \
		tmux split-window -h -t vm-boot "echo Starting vpc-b-vm... && sleep 1 && sudo virsh start vpc-b-vm && sudo virsh console vpc-b-vm"; \
		tmux select-layout -t vm-boot even-horizontal; \
		tmux attach-session -t vm-boot'

# ==================== MONITORING ====================

setup-monitoring: _ensure-vm
	@echo "📊 Setting up monitoring exporters..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py setup-monitoring
	@echo "✅ Monitoring exporters installed and started"

restart-exporters: _ensure-vm
	@echo "🔄 Restarting monitoring exporters..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py restart-exporters

debug-exporter: _ensure-vm
	@echo "🔍 Debugging OVS exporter..."
	@limactl shell ovs-lab -- bash -c "sudo systemctl status ovs-exporter --no-pager || true"
	@echo ""
	@echo "Last 10 log lines:"
	@limactl shell ovs-lab -- bash -c "sudo journalctl -u ovs-exporter -n 10 --no-pager || true"
	@echo ""
	@echo "Testing exporter help:"
	@limactl shell ovs-lab -- bash -c "sudo /usr/local/bin/ovs-exporter --help 2>&1 || true"
	@echo ""
	@echo "🔍 Debugging OVN exporter..."
	@limactl shell ovs-lab -- bash -c "docker exec ovn-central ps aux | grep -E 'ovn-exporter|PID' | grep -v grep || echo 'OVN exporter not running in container'"
	@limactl shell ovs-lab -- bash -c "docker exec ovn-central netstat -tulpn 2>/dev/null | grep 9476 || echo 'Port 9476 not listening in container'"
	@limactl shell ovs-lab -- bash -c "docker logs ovn-central 2>&1 | grep -i exporter | tail -5 || echo 'No exporter logs found'"

check-monitoring: _ensure-vm
	@echo "🔍 Checking monitoring exporters..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py check-monitoring

restart-prometheus: _ensure-vm
	@echo "🔄 Restarting Prometheus to load new configuration..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker compose restart prometheus
	@echo "✅ Prometheus restarted"
	@echo "Check targets at: http://localhost:9090/targets"

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
		echo "======================================"; \
		echo "🚀 Creating new Lima VM..."; \
		echo "======================================"; \
		echo "This will install:"; \
		echo "  📦 KVM/QEMU/libvirt for VM support"; \
		echo "  🐳 Docker for containerization"; \
		echo "  🔌 OVS/OVN for SDN networking"; \
		echo ""; \
		echo "⏱️  This may take 5-10 minutes on first run..."; \
		echo ""; \
		if [ "$(DEBUG)" = "1" ] || [ "$(DEBUG)" = "true" ]; then \
			echo "🔍 Debug mode enabled - showing detailed provisioning output..."; \
			echo ""; \
			limactl start --debug --name=ovs-lab lima.yaml; \
		else \
			echo "💡 TIP: Use 'make up DEBUG=1' to see detailed provisioning output"; \
			echo ""; \
			limactl start --name=ovs-lab lima.yaml; \
		fi; \
		echo ""; \
		echo "⏳ Finalizing VM setup..."; \
		sleep 15; \
		echo ""; \
		echo "📦 Installing OVS and OVN packages..."; \
		limactl shell --workdir /home/lima ovs-lab -- sudo DEBIAN_FRONTEND=noninteractive apt-get update; \
		limactl shell --workdir /home/lima ovs-lab -- sudo DEBIAN_FRONTEND=noninteractive apt-get install -y openvswitch-switch openvswitch-common python3-openvswitch ovn-host ovn-common; \
		limactl shell --workdir /home/lima ovs-lab -- sudo systemctl start openvswitch-switch; \
		limactl shell --workdir /home/lima ovs-lab -- sudo ovs-vsctl set open_vswitch . external_ids:system-id=chassis-host; \
		limactl shell --workdir /home/lima ovs-lab -- sudo ovs-vsctl set open_vswitch . external_ids:ovn-encap-type=geneve; \
		limactl shell --workdir /home/lima ovs-lab -- sudo ovs-vsctl --may-exist add-br br-int -- set bridge br-int datapath_type=netdev fail-mode=secure; \
		echo "✅ OVS/OVN configured successfully"; \
		echo ""; \
	else \
		if ! limactl list | grep ovs-lab | grep -q Running; then \
			echo "Starting existing Lima VM..."; \
			limactl start ovs-lab; \
			sleep 5; \
		fi; \
	fi
	@echo "✅ VM is ready"
	@echo "Checking Go installation..."
	@if ! limactl shell --workdir /home/lima ovs-lab -- which go > /dev/null 2>&1; then \
		echo "Go not found, installing..."; \
		limactl shell --workdir /home/lima ovs-lab -- bash -c 'GO_VERSION="1.25.1"; \
			ARCH=$$(dpkg --print-architecture); \
			CACHE_FILE="/home/lima/code/ovs-container-lab/.downloads/go$${GO_VERSION}.linux-$${ARCH}.tar.gz"; \
			if [ -f "$${CACHE_FILE}" ]; then \
				echo "Using cached Go installation..."; \
				sudo tar -C /usr/local -xzf "$${CACHE_FILE}"; \
			else \
				echo "Downloading Go..."; \
				sudo curl -L "https://go.dev/dl/go$${GO_VERSION}.linux-$${ARCH}.tar.gz" -o /tmp/go.tar.gz; \
				sudo tar -C /usr/local -xzf /tmp/go.tar.gz; \
				sudo rm /tmp/go.tar.gz; \
			fi; \
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
	@echo "=== Checking for VMs ==="
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c 'if sudo virsh list --name 2>/dev/null | grep -q "vpc-.-vm"; then \
		echo "VMs detected, including in tests..."; \
		for vm in vpc-a-vm vpc-b-vm; do \
			if sudo virsh list --name 2>/dev/null | grep -q "$$vm"; then \
				ip=$$(sudo virsh domifaddr $$vm 2>/dev/null | grep -oE "10\.[0-9]+\.[0-9]+\.[0-9]+" | head -1); \
				if [ -z "$$ip" ]; then \
					case $$vm in \
						vpc-a-vm) ip="10.0.5.10" ;; \
						vpc-b-vm) ip="10.1.5.10" ;; \
					esac; \
				fi; \
				echo "  $$vm: $$ip (VPC $${vm:4:1})"; \
			fi; \
		done; \
	else \
		echo "No VMs running, skipping VM tests"; \
	fi'
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
	@echo "=== Testing VM Connectivity (if VMs are running) ==="
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c 'if sudo virsh list --name 2>/dev/null | grep -q "vpc-.-vm"; then \
		echo "Note: VMs may need 1-2 minutes to fully boot after creation"; \
		echo ""; \
		echo "Testing VM to Container connectivity within same VPC:"; \
		if sudo virsh list --name 2>/dev/null | grep -q "vpc-a-vm"; then \
			for container in vpc-a-web vpc-a-app vpc-a-db; do \
				dst_ip=$$(sudo docker inspect $$container --format "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" 2>/dev/null); \
				if [ -n "$$dst_ip" ]; then \
					echo -n "  vpc-a-vm -> $$container ($$dst_ip): "; \
					sudo virsh domexec vpc-a-vm -- ping -c 1 -W 2 $$dst_ip > /dev/null 2>&1 && echo "✅ PASS" || \
						(sudo virsh domexec vpc-a-vm -- /bin/sh -c "ping -c 1 -W 2 $$dst_ip" > /dev/null 2>&1 && echo "✅ PASS" || echo "⚠️  VM may not be ready"); \
				fi; \
			done; \
		fi; \
		if sudo virsh list --name 2>/dev/null | grep -q "vpc-b-vm"; then \
			for container in vpc-b-web vpc-b-app vpc-b-db; do \
				dst_ip=$$(sudo docker inspect $$container --format "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}" 2>/dev/null); \
				if [ -n "$$dst_ip" ]; then \
					echo -n "  vpc-b-vm -> $$container ($$dst_ip): "; \
					sudo virsh domexec vpc-b-vm -- ping -c 1 -W 2 $$dst_ip > /dev/null 2>&1 && echo "✅ PASS" || \
						(sudo virsh domexec vpc-b-vm -- /bin/sh -c "ping -c 1 -W 2 $$dst_ip" > /dev/null 2>&1 && echo "✅ PASS" || echo "⚠️  VM may not be ready"); \
				fi; \
			done; \
		fi; \
		echo ""; \
		echo "Testing Container to VM connectivity within same VPC:"; \
		for container in vpc-a-web vpc-a-app vpc-a-db; do \
			if sudo docker inspect $$container > /dev/null 2>&1 && sudo virsh list --name 2>/dev/null | grep -q "vpc-a-vm"; then \
				echo -n "  $$container -> vpc-a-vm (10.0.5.10): "; \
				sudo docker exec $$container ping -c 1 -W 2 10.0.5.10 > /dev/null 2>&1 && echo "✅ PASS" || echo "❌ FAIL"; \
			fi; \
		done; \
		for container in vpc-b-web vpc-b-app vpc-b-db; do \
			if sudo docker inspect $$container > /dev/null 2>&1 && sudo virsh list --name 2>/dev/null | grep -q "vpc-b-vm"; then \
				echo -n "  $$container -> vpc-b-vm (10.1.5.10): "; \
				sudo docker exec $$container ping -c 1 -W 2 10.1.5.10 > /dev/null 2>&1 && echo "✅ PASS" || echo "❌ FAIL"; \
			fi; \
		done; \
		echo ""; \
		echo "Testing VM isolation across VPCs:"; \
		if sudo virsh list --name 2>/dev/null | grep -q "vpc-a-vm" && sudo virsh list --name 2>/dev/null | grep -q "vpc-b-vm"; then \
			echo -n "  vpc-a-vm -> vpc-b-vm (10.1.5.10): "; \
			sudo virsh domexec vpc-a-vm -- ping -c 1 -W 2 10.1.5.10 > /dev/null 2>&1 && echo "❌ CONNECTED (should be isolated)" || echo "✅ ISOLATED"; \
			echo -n "  vpc-b-vm -> vpc-a-vm (10.0.5.10): "; \
			sudo virsh domexec vpc-b-vm -- ping -c 1 -W 2 10.0.5.10 > /dev/null 2>&1 && echo "❌ CONNECTED (should be isolated)" || echo "✅ ISOLATED"; \
		fi; \
	else \
		echo "No VMs running, skipping VM connectivity tests"; \
	fi'
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
	@echo "=== Testing External Connectivity (if VMs are running) ==="
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- bash -c 'if sudo virsh list --name 2>/dev/null | grep -q "vpc-.-vm"; then \
		echo "Testing VM external connectivity (via NAT gateway):"; \
		for vm in vpc-a-vm vpc-b-vm; do \
			if sudo virsh list --name 2>/dev/null | grep -q "$$vm"; then \
				echo -n "  $$vm -> 8.8.8.8 (external): "; \
				sudo virsh domexec $$vm -- ping -c 1 -W 2 8.8.8.8 > /dev/null 2>&1 && echo "✅ PASS" || \
					(sudo virsh domexec $$vm -- /bin/sh -c "ping -c 1 -W 2 8.8.8.8" > /dev/null 2>&1 && echo "✅ PASS" || echo "⚠️  External access may not be configured"); \
			fi; \
		done; \
	fi'
	@echo ""
	@echo "========================================="

# ==================== TESTING ====================

# Unit tests for the plugin
test-unit: _ensure-vm
	@echo "🧪 Running unit tests for OVS Container Network plugin..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py test-unit

# Integration tests - requires plugin to be installed
test-integration: _ensure-vm
	@echo "🧪 Running integration tests in Lima VM..."
	@echo "Step 1: Checking if plugin is installed..."
	@if ! limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker plugin ls | grep -q "ovs-container-network.*true"; then \
		echo "Plugin not found or not enabled. Installing..."; \
		limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py install-plugin; \
	else \
		echo "Plugin is already installed and enabled"; \
	fi
	@echo ""
	@echo "Step 2: Running integration tests..."
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py test-integration

# Full test suite
test-all: _ensure-vm
	@echo "🧪 Running all tests..."
	@echo "Checking if plugin is installed..."
	@if ! limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo docker plugin ls | grep -q "ovs-container-network.*true"; then \
		echo "Plugin not found or not enabled. Installing..."; \
		limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py install-plugin; \
	else \
		echo "Plugin is already installed and enabled"; \
	fi
	@limactl shell --workdir /home/lima/code/ovs-container-lab ovs-lab -- sudo python3 orchestrator.py test-all

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

# ==================== VM IMAGE MANAGEMENT ====================

# Save the current VM as a reusable image
save-image: _ensure-vm
	@echo "📦 Saving VM image for quick restore..."
	@echo "This will create a snapshot of the fully configured VM"
	@limactl stop ovs-lab 2>/dev/null || true
	@echo "Exporting VM image (this may take a few minutes)..."
	@mkdir -p .vm-images
	@limactl export ovs-lab .vm-images/ovs-lab-$(shell date +%Y%m%d-%H%M%S).tar
	@# Create a symlink to the latest image
	@cd .vm-images && ln -sf ovs-lab-$(shell date +%Y%m%d-%H%M%S).tar ovs-lab-latest.tar
	@echo "✅ VM image saved to .vm-images/ovs-lab-latest.tar"
	@echo "Starting VM back up..."
	@limactl start ovs-lab
	@echo ""
	@echo "To restore this image later, use: make restore-image"

# Restore VM from saved image (much faster than building from scratch)
restore-image:
	@if [ ! -f .vm-images/ovs-lab-latest.tar ]; then \
		echo "❌ No saved image found. Run 'make save-image' first."; \
		exit 1; \
	fi
	@echo "📦 Restoring VM from saved image..."
	@limactl delete ovs-lab --force 2>/dev/null || true
	@limactl import .vm-images/ovs-lab-latest.tar ovs-lab
	@echo "Starting restored VM..."
	@limactl start ovs-lab
	@echo "✅ VM restored and running!"
	@echo ""
	@echo "The VM has all dependencies pre-installed:"
	@echo "  - Docker & Docker Compose"
	@echo "  - KVM/QEMU/libvirt"
	@echo "  - OVS/OVN"
	@echo "  - Go toolchain"
	@echo ""
	@echo "Run 'make status' to verify everything is working"

# Show available saved images
list-images:
	@echo "📦 Available VM images:"
	@if [ -d .vm-images ]; then \
		ls -lah .vm-images/*.tar 2>/dev/null | awk '{print "  " $$9 " (" $$5 ")"}' || echo "  No images found"; \
	else \
		echo "  No images directory found"; \
	fi

# Clean saved images
clean-images:
	@echo "🧹 Cleaning saved VM images..."
	@rm -rf .vm-images
	@echo "✅ Saved images removed"

.PHONY: test-unit test-integration test-all test-quick test-persistence test-ovn-auto test-clean