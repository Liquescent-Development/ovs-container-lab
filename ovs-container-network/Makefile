# OVS Container Network Plugin Makefile

PLUGIN_NAME = ovs-container-network
PLUGIN_TAG ?= latest
PLUGIN_IMAGE = $(PLUGIN_NAME):$(PLUGIN_TAG)
PLUGIN_DIR = /run/docker/plugins

# Go parameters
GOCMD = go
GOBUILD = $(GOCMD) build
GOCLEAN = $(GOCMD) clean
GOTEST = $(GOCMD) test
GOGET = $(GOCMD) get
GOMOD = $(GOCMD) mod

# Build flags
LDFLAGS = -s -w
BUILD_FLAGS = -trimpath -ldflags "$(LDFLAGS)"

.PHONY: all build clean test docker-build docker-push install uninstall enable disable logs

# Default target
all: build

# Build the binary locally
build:
	@echo "Building $(PLUGIN_NAME)..."
	$(GOBUILD) $(BUILD_FLAGS) -o $(PLUGIN_NAME) .

# Clean build artifacts
clean:
	@echo "Cleaning..."
	$(GOCLEAN)
	rm -f $(PLUGIN_NAME)
	rm -rf rootfs

# Run tests
test:
	@echo "Running tests..."
	$(GOTEST) -v ./...

# Download dependencies
deps:
	@echo "Downloading dependencies..."
	$(GOMOD) download
	$(GOMOD) tidy

# Build Docker image
docker-build:
	@echo "Building Docker image $(PLUGIN_IMAGE)..."
	docker build -t $(PLUGIN_IMAGE) .

# Create plugin rootfs
rootfs: docker-build
	@echo "Creating plugin rootfs..."
	rm -rf rootfs
	mkdir -p rootfs
	docker create --name tmp-$(PLUGIN_NAME) $(PLUGIN_IMAGE)
	docker export tmp-$(PLUGIN_NAME) | tar -x -C rootfs
	docker rm tmp-$(PLUGIN_NAME)
	cp config.json .

# Create and install the plugin
plugin-create: rootfs
	@echo "Creating Docker plugin..."
	docker plugin rm -f $(PLUGIN_NAME):$(PLUGIN_TAG) 2>/dev/null || true
	docker plugin create $(PLUGIN_NAME):$(PLUGIN_TAG) .

# Install the plugin from directory
install: plugin-create
	@echo "Installing plugin $(PLUGIN_NAME):$(PLUGIN_TAG)..."
	docker plugin enable $(PLUGIN_NAME):$(PLUGIN_TAG)

# Uninstall the plugin
uninstall:
	@echo "Uninstalling plugin $(PLUGIN_NAME):$(PLUGIN_TAG)..."
	docker plugin disable $(PLUGIN_NAME):$(PLUGIN_TAG) 2>/dev/null || true
	docker plugin rm $(PLUGIN_NAME):$(PLUGIN_TAG) 2>/dev/null || true

# Enable the plugin
enable:
	@echo "Enabling plugin $(PLUGIN_NAME):$(PLUGIN_TAG)..."
	docker plugin enable $(PLUGIN_NAME):$(PLUGIN_TAG)

# Disable the plugin
disable:
	@echo "Disabling plugin $(PLUGIN_NAME):$(PLUGIN_TAG)..."
	docker plugin disable $(PLUGIN_NAME):$(PLUGIN_TAG)

# View plugin logs
logs:
	@echo "Viewing plugin logs..."
	journalctl -u docker -f | grep $(PLUGIN_NAME)

# Development mode - run plugin locally (not as Docker plugin)
dev-run: build
	@echo "Running plugin in development mode..."
	sudo ./$(PLUGIN_NAME) --debug

# Test network creation
test-network:
	@echo "Creating test network..."
	docker network create --driver $(PLUGIN_NAME):$(PLUGIN_TAG) \
		--subnet 172.20.0.0/24 \
		--opt bridge=br-int \
		--opt tenant_id=test-tenant \
		test-ovs-net

# Test container connection
test-container:
	@echo "Running test container..."
	docker run --rm -it \
		--network test-ovs-net \
		alpine sh -c "ip addr show; ping -c 3 172.20.0.1"

# Clean test resources
test-clean:
	@echo "Cleaning test resources..."
	docker rm -f test-container 2>/dev/null || true
	docker network rm test-ovs-net 2>/dev/null || true

# Full test suite
test-integration: install test-network test-container test-clean
	@echo "Integration tests completed"

# Push plugin to registry
push:
	@echo "Pushing plugin to registry..."
	docker plugin push $(PLUGIN_NAME):$(PLUGIN_TAG)

# Show plugin information
info:
	@echo "Plugin information:"
	docker plugin inspect $(PLUGIN_NAME):$(PLUGIN_TAG)

# Development environment setup
setup-dev:
	@echo "Setting up development environment..."
	$(GOMOD) download
	$(GOMOD) tidy
	@echo "Installing OVS dependencies..."
	@which ovs-vsctl > /dev/null || echo "Warning: ovs-vsctl not found. Please install Open vSwitch"

# Format code
fmt:
	@echo "Formatting code..."
	gofmt -s -w .

# Lint code
lint:
	@echo "Linting code..."
	golint ./...

# Security scan
security:
	@echo "Running security scan..."
	gosec ./...

# Help target
help:
	@echo "Available targets:"
	@echo "  make build          - Build the binary locally"
	@echo "  make docker-build   - Build Docker image"
	@echo "  make install        - Create and install the plugin"
	@echo "  make uninstall      - Uninstall the plugin"
	@echo "  make enable         - Enable the plugin"
	@echo "  make disable        - Disable the plugin"
	@echo "  make logs           - View plugin logs"
	@echo "  make dev-run        - Run plugin in development mode"
	@echo "  make test           - Run unit tests"
	@echo "  make test-integration - Run integration tests"
	@echo "  make clean          - Clean build artifacts"
	@echo "  make help           - Show this help"