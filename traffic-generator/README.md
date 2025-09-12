# Professional Traffic Generator

This container provides professional-grade traffic generation tools for stress testing the OVS infrastructure.

## Tools Included

- **hping3**: Advanced packet crafting and flood attacks
- **iperf3**: Bandwidth and performance testing
- **netperf**: Network performance benchmarking
- **tcpreplay**: Replay captured traffic patterns
- **Python Scapy**: Custom traffic pattern generation

## Traffic Generation Capabilities

The traffic generator can produce:
- **200,000+ packets per second** sustained traffic
- TCP SYN/ACK floods on multiple ports
- UDP floods with varying packet sizes
- ICMP floods with large packets (1400 bytes)
- Fragmented packet streams
- ARP broadcast storms
- Custom traffic patterns via Scapy

## Usage

### Via Docker Compose

```bash
# Start the traffic generator
docker compose --profile traffic up -d traffic-generator

# Connect to OVS bridge (required)
./scripts/ovs-docker-connect.sh traffic-generator 172.18.0.30
```

### Via Make

```bash
# Start high-intensity traffic (200k+ pps)
make traffic-high

# Start low-intensity traffic (10k pps)
make traffic-low

# Stop traffic generation
make traffic-stop
```

### Via Demo Script

```bash
# Run traffic generation as part of demo
./scripts/network-simulation/demo.sh traffic-only high
```

## Traffic Patterns

### High Intensity (200k+ pps)
- TCP SYN floods with random source IPs
- UDP floods on multiple ports
- ICMP floods with 1400-byte packets
- Python Scapy generating complex patterns

### Medium Intensity (50k pps)
- Controlled TCP SYN at 1000 pps per target
- UDP traffic at 500 pps per target
- Basic ICMP echo requests

### Low Intensity (10k pps)
- TCP SYN at 100 pps per target
- Minimal UDP and ICMP traffic
- Suitable for baseline measurements

## Python Traffic Generator

The `traffic-gen.py` script uses Scapy to generate:
- TCP SYN floods
- UDP floods with varying sizes
- ICMP floods
- ARP requests
- Fragmented packets
- Burst traffic patterns

Multiple threads run different generators simultaneously for maximum impact.

## Building

```bash
# Build via Docker Compose
docker compose build traffic-generator

# Build via Make
make build
```

## Container Details

- **Base Image**: Ubuntu 22.04
- **Network Mode**: None (connected via OVS scripts)
- **Privileges**: Required for raw packet generation
- **Default IP**: 172.18.0.30 (when connected to OVS)