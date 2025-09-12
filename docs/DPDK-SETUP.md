# OVS-DPDK Container Setup Guide

This guide covers setting up Open vSwitch with DPDK support in a containerized environment, specifically for Intel I350-T4 NICs.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Host System Preparation](#host-system-preparation)
3. [DPDK Configuration](#dpdk-configuration)
4. [OVS-DPDK Container Setup](#ovs-dpdk-container-setup)
5. [Monitoring Integration](#monitoring-integration)
6. [Testing and Validation](#testing-and-validation)
7. [Troubleshooting](#troubleshooting)

## Prerequisites

### Hardware Requirements
- **CPU**: Intel Xeon or Core processor with VT-d support
- **Memory**: Minimum 8GB RAM (16GB+ recommended)
- **NIC**: Intel I350-T4 (or other DPDK-compatible NIC)
- **OS**: Ubuntu 20.04/22.04 or RHEL/CentOS 8+

### Software Requirements
- Docker and Docker Compose
- Linux kernel 4.4+ with IOMMU support
- DPDK 20.11+ (will be installed in container)

## Host System Preparation

### 1. Enable IOMMU in BIOS

Enter BIOS/UEFI settings and enable:
- Intel VT-d (Virtualization Technology for Directed I/O)
- Intel VT-x (if not already enabled)
- Any IOMMU-related settings

### 2. Configure Kernel Parameters

```bash
# Edit GRUB configuration
sudo nano /etc/default/grub

# Add these parameters to GRUB_CMDLINE_LINUX
GRUB_CMDLINE_LINUX="default_hugepagesz=1G hugepagesz=1G hugepages=4 intel_iommu=on iommu=pt isolcpus=2-5 nohz_full=2-5 rcu_nocbs=2-5"

# For systems with limited memory, use 2MB pages instead
GRUB_CMDLINE_LINUX="default_hugepagesz=2M hugepagesz=2M hugepages=2048 intel_iommu=on iommu=pt isolcpus=2-5"

# Update GRUB and reboot
sudo update-grub
sudo reboot
```

### 3. Verify IOMMU is Enabled

```bash
# Check IOMMU is active
sudo dmesg | grep -e IOMMU -e DMAR
# Should see: "IOMMU enabled"

# Verify IOMMU groups
ls /sys/kernel/iommu_groups/
# Should list numbered directories

# Check hugepages
grep Huge /proc/meminfo
# Should show allocated hugepages
```

### 4. Install Host Dependencies

```bash
# Ubuntu/Debian
sudo apt-get update
sudo apt-get install -y \
    build-essential \
    linux-headers-$(uname -r) \
    python3-pip \
    pciutils \
    kmod

# RHEL/CentOS
sudo yum install -y \
    kernel-devel \
    kernel-headers \
    gcc \
    make \
    python3-pip \
    pciutils \
    kmod
```

## DPDK Configuration

### 1. Identify Intel I350-T4 Ports

```bash
# List network devices
lspci | grep -i ethernet

# Note the PCI addresses (e.g., 03:00.0, 03:00.1, 03:00.2, 03:00.3)
# Save for later use in container configuration
```

### 2. Prepare Network Interfaces

```bash
# Bring down interfaces that will be used by DPDK
sudo ifconfig enp3s0f0 down  # Adjust interface names as needed
sudo ifconfig enp3s0f1 down
sudo ifconfig enp3s0f2 down
sudo ifconfig enp3s0f3 down
```

## OVS-DPDK Container Setup

### 1. Create OVS-DPDK Dockerfile

Create `ovs-dpdk-container/Dockerfile`:

```dockerfile
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV DPDK_VERSION=22.11.1
ENV OVS_VERSION=3.1.0

# Install dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    wget \
    libnuma-dev \
    libpcap-dev \
    libssl-dev \
    python3 \
    python3-pip \
    autoconf \
    automake \
    libtool \
    kmod \
    pciutils \
    iproute2 \
    numactl \
    && rm -rf /var/lib/apt/lists/*

# Build and install DPDK
WORKDIR /opt
RUN wget https://fast.dpdk.org/rel/dpdk-${DPDK_VERSION}.tar.xz \
    && tar xf dpdk-${DPDK_VERSION}.tar.xz \
    && cd dpdk-stable-${DPDK_VERSION} \
    && meson build \
    && cd build \
    && ninja \
    && ninja install \
    && ldconfig

# Build and install OVS with DPDK support
WORKDIR /opt
RUN git clone https://github.com/openvswitch/ovs.git \
    && cd ovs \
    && git checkout v${OVS_VERSION} \
    && ./boot.sh \
    && ./configure --with-dpdk=shared \
    && make -j$(nproc) \
    && make install \
    && ldconfig

# Create necessary directories
RUN mkdir -p /var/run/openvswitch /var/log/openvswitch /etc/openvswitch

# Copy startup script
COPY start-ovs-dpdk.sh /start-ovs-dpdk.sh
RUN chmod +x /start-ovs-dpdk.sh

# Health check script
COPY healthcheck-dpdk.sh /healthcheck.sh
RUN chmod +x /healthcheck.sh

EXPOSE 6640 6641 9475

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD /healthcheck.sh

CMD ["/start-ovs-dpdk.sh"]
```

### 2. Create Startup Script

Create `ovs-dpdk-container/start-ovs-dpdk.sh`:

```bash
#!/bin/bash
set -e

# Load kernel modules if needed
modprobe openvswitch || true
modprobe vfio-pci || true

# Initialize OVSDB
if [ ! -f /etc/openvswitch/conf.db ]; then
    ovsdb-tool create /etc/openvswitch/conf.db /usr/local/share/openvswitch/vswitch.ovsschema
fi

# Start OVSDB server
ovsdb-server \
    --remote=punix:/var/run/openvswitch/db.sock \
    --remote=db:Open_vSwitch,Open_vSwitch,manager_options \
    --pidfile --detach --log-file

# Initialize OVS
ovs-vsctl --no-wait init

# Configure DPDK
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-init=true
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-socket-mem="1024,0"
ovs-vsctl --no-wait set Open_vSwitch . other_config:dpdk-lcore-mask=0x3
ovs-vsctl --no-wait set Open_vSwitch . other_config:pmd-cpu-mask=0xC

# Start OVS-DPDK
ovs-vswitchd unix:/var/run/openvswitch/db.sock \
    --pidfile --detach --log-file \
    --mlockall

echo "Waiting for OVS to start..."
sleep 5

# Create DPDK bridge
ovs-vsctl --may-exist add-br dpdk-br0 -- set bridge dpdk-br0 datapath_type=netdev

# Add DPDK ports (adjust PCI addresses based on your system)
# These will be passed as environment variables
if [ ! -z "$DPDK_PCI_ADDR_1" ]; then
    ovs-vsctl --may-exist add-port dpdk-br0 dpdk0 \
        -- set Interface dpdk0 type=dpdk \
        options:dpdk-devargs=$DPDK_PCI_ADDR_1
fi

if [ ! -z "$DPDK_PCI_ADDR_2" ]; then
    ovs-vsctl --may-exist add-port dpdk-br0 dpdk1 \
        -- set Interface dpdk1 type=dpdk \
        options:dpdk-devargs=$DPDK_PCI_ADDR_2
fi

echo "OVS-DPDK started successfully"

# Keep container running and show logs
tail -f /var/log/openvswitch/*.log
```

### 3. Create Health Check Script

Create `ovs-dpdk-container/healthcheck-dpdk.sh`:

```bash
#!/bin/bash

# Check if OVS is running
ovs-vsctl show > /dev/null 2>&1
if [ $? -ne 0 ]; then
    echo "OVS is not running"
    exit 1
fi

# Check if DPDK is initialized
dpdk_init=$(ovs-vsctl get Open_vSwitch . other_config:dpdk-init)
if [ "$dpdk_init" != "true" ]; then
    echo "DPDK is not initialized"
    exit 1
fi

# Check if bridge exists
ovs-vsctl br-exists dpdk-br0
if [ $? -ne 0 ]; then
    echo "DPDK bridge does not exist"
    exit 1
fi

echo "OVS-DPDK is healthy"
exit 0
```

### 4. Update Docker Compose

Create `docker-compose.dpdk.yml`:

```yaml
version: '3.8'

services:
  ovs-dpdk:
    build: ./ovs-dpdk-container
    container_name: ovs-dpdk
    restart: unless-stopped
    privileged: true
    network_mode: host
    pid: host
    volumes:
      # Hugepages
      - /dev/hugepages:/dev/hugepages
      - /mnt/huge:/mnt/huge
      # Device access
      - /sys/bus/pci/devices:/sys/bus/pci/devices
      - /sys/kernel/mm/hugepages:/sys/kernel/mm/hugepages
      - /sys/devices/system/node:/sys/devices/system/node
      - /dev:/dev
      # Persistence
      - ovs-dpdk-db:/etc/openvswitch
      - ovs-dpdk-logs:/var/log/openvswitch
      - ovs-dpdk-run:/var/run/openvswitch
    environment:
      # Adjust these PCI addresses based on your lspci output
      - DPDK_PCI_ADDR_1=0000:03:00.0
      - DPDK_PCI_ADDR_2=0000:03:00.1
      - DPDK_PCI_ADDR_3=0000:03:00.2
      - DPDK_PCI_ADDR_4=0000:03:00.3
    devices:
      - /dev/vfio:/dev/vfio
    cap_add:
      - IPC_LOCK
      - SYS_ADMIN
      - NET_ADMIN
      - SYS_NICE
      - SYS_RAWIO
    ulimits:
      memlock:
        soft: -1
        hard: -1
      nofile:
        soft: 65536
        hard: 65536

  # Enhanced OVS Exporter for DPDK metrics
  ovs-dpdk-exporter:
    build: ./ovs-exporter
    container_name: ovs-dpdk-exporter
    restart: unless-stopped
    network_mode: host
    pid: "container:ovs-dpdk"
    ports:
      - "9475:9475"
    depends_on:
      ovs-dpdk:
        condition: service_healthy
    volumes:
      - ovs-dpdk-run:/var/run/openvswitch:rw
      - ovs-dpdk-db:/etc/openvswitch:ro
      - ovs-dpdk-logs:/var/log/openvswitch:ro

  # Additional Prometheus config for DPDK metrics
  prometheus-dpdk:
    extends:
      file: docker-compose.yml
      service: prometheus
    volumes:
      - ./prometheus-dpdk.yml:/etc/prometheus/prometheus.yml:ro
      - prometheus-data:/prometheus

volumes:
  ovs-dpdk-db:
  ovs-dpdk-logs:
  ovs-dpdk-run:
  prometheus-data:
```

## Monitoring Integration

### 1. Update Prometheus Configuration

Create `prometheus-dpdk.yml`:

```yaml
global:
  scrape_interval: 15s
  evaluation_interval: 15s

scrape_configs:
  - job_name: 'ovs-dpdk'
    static_configs:
      - targets: ['localhost:9475']
    metric_relabel_configs:
      # Keep all DPDK-specific metrics
      - source_labels: [__name__]
        regex: 'ovs_(pmd|dpdk|emc|smc|rxq).*'
        action: keep

  - job_name: 'ovs-coverage'
    static_configs:
      - targets: ['localhost:9475']
    metric_relabel_configs:
      - source_labels: [__name__]
        regex: 'ovs_coverage.*'
        action: keep

  - job_name: 'node'
    static_configs:
      - targets: ['localhost:9100']
```

### 2. Create DPDK-Specific Grafana Dashboard

Save as `grafana/dashboards/ovs-dpdk-performance.json`:

```json
{
  "dashboard": {
    "title": "OVS-DPDK Performance Monitoring",
    "panels": [
      {
        "title": "PMD Thread CPU Usage",
        "targets": [
          {
            "expr": "rate(ovs_pmd_cpu_cycles[5m])"
          }
        ]
      },
      {
        "title": "EMC Hit Rate",
        "targets": [
          {
            "expr": "rate(ovs_emc_hits[5m]) / (rate(ovs_emc_hits[5m]) + rate(ovs_emc_misses[5m]))"
          }
        ]
      },
      {
        "title": "Packets per PMD Thread",
        "targets": [
          {
            "expr": "rate(ovs_pmd_packets_processed[5m])"
          }
        ]
      },
      {
        "title": "RX Batch Size",
        "targets": [
          {
            "expr": "ovs_pmd_rx_batch_size"
          }
        ]
      }
    ]
  }
}
```

## Testing and Validation

### 1. Bind NIC to DPDK

```bash
# Inside the container or on host
dpdk-devbind.py --status

# Bind Intel I350 ports to VFIO
dpdk-devbind.py --bind=vfio-pci 0000:03:00.0
dpdk-devbind.py --bind=vfio-pci 0000:03:00.1
```

### 2. Verify DPDK Initialization

```bash
# Check DPDK status
docker exec ovs-dpdk ovs-vsctl show

# Check DPDK configuration
docker exec ovs-dpdk ovs-vsctl get Open_vSwitch . other_config

# Check PMD threads
docker exec ovs-dpdk ovs-appctl dpif-netdev/pmd-stats-show

# Check DPDK ports
docker exec ovs-dpdk ovs-appctl dpctl/show
```

### 3. Monitor PMD Performance

```bash
# Real-time PMD statistics
docker exec ovs-dpdk ovs-appctl dpif-netdev/pmd-perf-show

# Coverage statistics
docker exec ovs-dpdk ovs-appctl coverage/show

# Memory statistics
docker exec ovs-dpdk ovs-appctl memory/show
```

### 4. Generate Test Traffic

```bash
# Create test containers connected via vhost-user
docker exec ovs-dpdk ovs-vsctl add-port dpdk-br0 vhost-user1 \
    -- set Interface vhost-user1 type=dpdkvhostuserclient \
    options:vhost-server-path=/tmp/vhost-user1

# Use testpmd for traffic generation
docker run --rm -it \
    --privileged \
    -v /dev/hugepages:/dev/hugepages \
    -v /tmp:/tmp \
    dpdk/testpmd \
    --vdev=virtio_user0,path=/tmp/vhost-user1 \
    -- --forward-mode=txonly --stats-period=1
```

## Performance Tuning

### 1. CPU Affinity

```bash
# Set PMD thread affinity
docker exec ovs-dpdk ovs-vsctl set Open_vSwitch . \
    other_config:pmd-cpu-mask=0xFF00

# Pin specific PMD threads
docker exec ovs-dpdk ovs-appctl dpif-netdev/pmd-rxq-rebalance
```

### 2. Memory Optimization

```bash
# Adjust socket memory
docker exec ovs-dpdk ovs-vsctl set Open_vSwitch . \
    other_config:dpdk-socket-mem="2048,2048"

# Configure memory channels
docker exec ovs-dpdk ovs-vsctl set Open_vSwitch . \
    other_config:dpdk-extra="-n 4"
```

### 3. Queue Configuration

```bash
# Set number of RX queues
docker exec ovs-dpdk ovs-vsctl set Interface dpdk0 \
    options:n_rxq=2

# Set RX queue size
docker exec ovs-dpdk ovs-vsctl set Interface dpdk0 \
    options:n_rxq_desc=2048
```

## Troubleshooting

### Common Issues and Solutions

#### 1. DPDK Initialization Fails

```bash
# Check hugepages
cat /proc/meminfo | grep Huge

# Check IOMMU groups
ls /sys/kernel/iommu_groups/

# Check VFIO module
lsmod | grep vfio
```

#### 2. No PMD Statistics

```bash
# Ensure PMD threads are created
docker exec ovs-dpdk ovs-appctl dpif-netdev/pmd-stats-show

# Check CPU mask configuration
docker exec ovs-dpdk ovs-vsctl get Open_vSwitch . other_config:pmd-cpu-mask
```

#### 3. Poor Performance

```bash
# Check for CPU isolation
cat /proc/cmdline | grep isolcpus

# Verify NUMA node assignment
docker exec ovs-dpdk ovs-appctl dpif-netdev/pmd-rxq-show

# Check for packet drops
docker exec ovs-dpdk ovs-appctl coverage/show | grep drop
```

### Useful Commands

```bash
# Reset DPDK configuration
docker exec ovs-dpdk ovs-vsctl remove Open_vSwitch . other_config dpdk-init

# Clear PMD statistics
docker exec ovs-dpdk ovs-appctl dpif-netdev/pmd-stats-clear

# Show detailed interface statistics
docker exec ovs-dpdk ovs-vsctl list Interface dpdk0

# Monitor in real-time
watch -n 1 'docker exec ovs-dpdk ovs-appctl dpif-netdev/pmd-stats-show'
```

## Security Considerations

1. **Privileged Container**: OVS-DPDK requires privileged mode for hardware access
2. **Host Network**: Uses host networking for performance
3. **Device Access**: Requires access to /dev/vfio for NIC binding
4. **Memory Locking**: Needs IPC_LOCK capability for hugepages

## Additional Resources

- [DPDK Documentation](https://doc.dpdk.org/)
- [OVS-DPDK Documentation](http://docs.openvswitch.org/en/latest/intro/install/dpdk/)
- [Intel DPDK Performance Reports](https://www.intel.com/content/www/us/en/developer/topic-technology/networking/dpdk-performance-reports.html)
- [DPDK Sample Applications](https://doc.dpdk.org/guides/sample_app_ug/)

## Next Steps

1. Install Intel I350-T4 NIC when it arrives
2. Follow host preparation steps
3. Build and run OVS-DPDK container
4. Configure monitoring with enhanced metrics
5. Run performance tests with traffic generators
6. Tune for optimal performance based on workload