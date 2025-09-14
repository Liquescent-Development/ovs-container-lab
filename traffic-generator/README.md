# Traffic Generator for OVS/OVN Multi-VPC Lab

This directory contains the consolidated traffic generation system for testing the multi-VPC OVS/OVN setup.

## Overview

The traffic generator (`traffic-gen.py`) simulates realistic network traffic between VPC-A and VPC-B containers to test:
- Inter-VPC routing through OVN
- Network performance under various loads
- Chaos scenarios and failure handling
- SDN flow programming and optimization

## Traffic Modes

### Standard Mode
- Moderate traffic load
- 100 packets/second rate limit
- 10 Mbps bandwidth limit
- 2 worker threads
- Suitable for normal testing and demos

### High Mode
- Increased traffic load
- 500 packets/second rate limit
- 50 Mbps bandwidth limit
- 3 worker threads
- Tests system under stress

### Chaos Mode
- Maximum controlled load (with safety limits)
- 1000 packets/second rate limit
- 100 Mbps bandwidth limit
- 4 worker threads
- CPU limited to 50% to prevent system hang
- Tests failure scenarios and recovery

## Target Containers

The generator automatically targets containers in both VPCs:

**VPC-A (Tenant 1):**
- `10.0.1.10` - vpc-a-web
- `10.0.2.10` - vpc-a-app
- `10.0.3.10` - vpc-a-db

**VPC-B (Tenant 2):**
- `10.1.1.10` - vpc-b-web
- `10.1.2.10` - vpc-b-app
- `10.1.3.10` - vpc-b-db

## Traffic Types

The generator creates various realistic traffic patterns:
- **ICMP**: Ping tests for basic connectivity
- **TCP**: Connection tests on ports 80, 443, 8080, 3000
- **UDP**: Packet streams with rate limiting
- **HTTP**: Simulated web requests via curl
- **iperf3**: Bandwidth testing with automatic throttling

## Usage

### Via Make Commands (Recommended)

```bash
# Start standard traffic
make traffic-run

# Start high-intensity traffic
make traffic-heavy

# Start chaos mode traffic (with safety limits)
make traffic-chaos

# Check traffic generator status
make traffic-status

# Stop all traffic generation
make traffic-stop
```

### Manual Control

```bash
# Via orchestrator
sudo python3 orchestrator.py traffic start --mode standard
sudo python3 orchestrator.py traffic start --mode high
sudo python3 orchestrator.py traffic stop

# Inside the container directly
docker exec traffic-generator python3 /workspace/traffic-gen.py standard
```

## Architecture

The generator runs inside a Docker container with all necessary network tools:

### Container Tools
- **Basic**: ping, netcat, curl, wget
- **Advanced**: hping3, iperf3, nmap, tcpdump
- **Python**: Scapy for custom packet crafting

### Design Features
- Multi-threading for concurrent traffic flows
- Process pooling with strict limits to prevent resource exhaustion
- Rate limiting to prevent system overload
- Graceful shutdown handling (SIGINT/SIGTERM)
- Real-time statistics reporting every 5 seconds

## Resource Controls

To prevent system overload, the generator implements multiple safety mechanisms:

| Mode | Threads | Max Processes | PPS Limit | Bandwidth | CPU Limit |
|------|---------|---------------|-----------|-----------|-----------|
| Standard | 2 | 4 | 100 | 10 Mbps | 25% |
| High | 3 | 6 | 500 | 50 Mbps | 40% |
| Chaos | 4 | 8 | 1000 | 100 Mbps | 50% |

Additional safety features:
- Automatic process cleanup
- Timeout on all operations
- Delay between traffic bursts
- Connection limits per mode

## Monitoring

### Real-time Statistics
The generator prints statistics every 5 seconds showing:
- Total packets sent
- Protocol breakdown (ICMP, UDP, TCP)
- HTTP requests and connections
- Bandwidth usage
- Active process count

### Grafana Dashboards
View traffic impact in real-time:
- **OVS VPC Architecture**: Shows per-VPC traffic rates
- **OVS Docker Monitoring**: Interface packet rates
- **Multi-VPC Monitoring**: Inter-VPC traffic patterns

## Building

The container is built automatically when you run `make up`, but you can rebuild manually:

```bash
# Rebuild the traffic generator container
docker compose build traffic-generator

# Or via Make
make build
```

## Troubleshooting

### Traffic Not Visible
- Ensure containers are running: `docker ps | grep vpc`
- Check VPC connectivity: `make test`
- Verify OVN bindings: `make show-ovn`

### System Overload
- Stop traffic immediately: `make traffic-stop`
- Use standard mode instead of chaos
- Check resource usage: `docker stats`

### Container Issues
- Restart container: `docker restart traffic-generator`
- Check logs: `docker logs traffic-generator`
- Verify network binding: `sudo ovs-vsctl show`