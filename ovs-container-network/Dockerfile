# Build stage
FROM golang:1.25-bookworm AS builder

# Set working directory
WORKDIR /build

# Copy go mod files
COPY go.mod go.sum ./

# Download dependencies
RUN go mod download

# Copy source code
COPY . .

# Build the plugin binary
RUN CGO_ENABLED=1 GOOS=linux go build -a -installsuffix cgo -o ovs-container-network .

# Runtime stage - Use Ubuntu 24.04 to match host OVS version
FROM ubuntu:24.04

# Install runtime dependencies including OVN client tools
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y \
    openvswitch-switch \
    openvswitch-common \
    python3-openvswitch \
    ovn-common \
    ovn-host \
    iproute2 \
    iptables \
    ca-certificates \
    netcat-openbsd \
    && rm -rf /var/lib/apt/lists/*

# Create plugin directory structure
RUN mkdir -p /run/docker/plugins /var/log/ovs-container-network

# Copy the binary from builder
COPY --from=builder /build/ovs-container-network /usr/local/bin/ovs-container-network

# Make it executable
RUN chmod +x /usr/local/bin/ovs-container-network

# Create a non-root user (Docker will override this with root for plugins)
RUN groupadd -g 1000 ovs 2>/dev/null || true && \
    useradd -u 1000 -g ovs -s /bin/bash ovs 2>/dev/null || true

# Set the entrypoint
ENTRYPOINT ["/usr/local/bin/ovs-container-network"]

# Default arguments
CMD ["--socket", "/run/docker/plugins/ovs-net.sock"]