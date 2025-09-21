# OVN Container Network Plugin

A modern Docker network plugin that provides native integration with Open Virtual Network (OVN) and Open vSwitch (OVS). **This plugin requires OVN configuration for all networks** and features automated OVN central management and transit network support for multi-VPC cloud environments.

⚠️ **Important**: This is an OVN-based plugin. All networks (except transit networks with `ovn.role=transit`) must specify OVN logical switch configuration. Networks cannot be created without proper OVN settings.

## Features

- ✅ **OVN-First Architecture** - All networks require OVN logical switch configuration
- ✅ **Docker Native Integration** - Works with standard Docker commands
- ✅ **OVS Bridge Management** - Automatic bridge creation and port management
- ✅ **Persistent State Management** - Survives plugin restarts, upgrades, and Docker daemon restarts
- ✅ **OVN Logical Networks** - Required logical switches and overlay networks
- ✅ **Auto-managed OVN Central** - Automatic OVN container creation and management
- ✅ **Transit Networks** - Gateway routers with external connectivity for multi-VPC
- ✅ **Multi-Host Networking** - GENEVE/VXLAN tunneling with OVN
- ✅ **OVN DHCP** - Built-in DHCP server via OVN
- ✅ **Multi-Tenancy** - Tenant tracking via external_ids
- ✅ **Port Mirroring** - Traffic mirroring for monitoring/debugging
- ✅ **Multiple IPAM Modes** - Docker managed, static, external DHCP
- ✅ **Docker Compose Compatible** - Seamless integration with compose files
- ✅ **Port Security Management** - Automatic port security handling for NAT gateways
- ✅ **Docker Socket Integration** - Direct container lifecycle management via Unix socket

## Quick Start

### Prerequisites

1. Install Open vSwitch:
```bash
# Ubuntu/Debian
sudo apt-get install openvswitch-switch

# RHEL/CentOS
sudo yum install openvswitch

# macOS (in Lima VM)
limactl shell default
sudo apt-get install openvswitch-switch
```

2. Start OVS:
```bash
sudo systemctl start openvswitch-switch
```

3. Create integration bridge:
```bash
sudo ovs-vsctl add-br br-int
```

4. Ensure Docker socket access:
   - The plugin requires access to `/var/run/docker.sock` to manage OVN containers and persist state
   - This is automatically mounted via the plugin configuration
   - Enables automatic container management and state recovery

### Installation

#### Option 1: Automated install from source
```bash
# Clone the repository
git clone https://github.com/ovs-container-lab/ovs-container-network
cd ovs-container-network

# Run the automated installer (requires sudo)
sudo ./install.sh
```

#### Option 2: Manual build and install
```bash
# Clone and enter directory
git clone https://github.com/ovs-container-lab/ovs-container-network
cd ovs-container-network

# Build the plugin
make docker-build
make plugin-create

# Install and enable
docker plugin enable ovs-container-network:latest
```

#### Option 3: Install pre-built plugin (when available)
```bash
docker plugin install ovs-container-network:latest --grant-all-permissions
```

### Quick Demo

After installation, run the quick start demo:
```bash
./quick-start.sh
```

### Basic Usage

⚠️ **All networks require OVN configuration**. You cannot create networks without specifying the required OVN options:

1. Create a network with required OVN configuration:
```bash
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-my-network \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  my-ovn-network
```

2. Run containers:
```bash
docker run --rm -it --network my-ovn-network alpine sh
```

**Note**: The example above will automatically create OVN central if it doesn't exist (`ovn.auto_create=true`).

## Network Architecture Overview

The plugin uses a two-network architecture when working with OVN (Open Virtual Network) to separate concerns and avoid IP conflicts:

### Transit-Overlay Network (Docker Bridge)
- **Purpose**: Docker bridge network that hosts the OVN central container
- **Default Subnet**: 172.30.0.0/24 (auto-selected to avoid conflicts)
- **Default Name**: `transit-overlay` (customizable via `ovn.transit_overlay_network`)
- **OVN Central IP**: Always .5 on this network (e.g., 172.30.0.5)
- **Management**: Automatically created and managed by the plugin when `ovn.auto_create=true`

### Transit-Net (OVN Logical Network)
- **Purpose**: OVN logical network for inter-VPC routing and external gateway connectivity
- **Default Subnet**: 192.168.100.0/24 (configurable via network creation)
- **Role**: Connects multiple VPC logical routers for inter-VPC communication
- **Gateway**: External gateway for NAT and routing to external networks

### Why Two Networks?

This separation provides several benefits:
1. **IP Conflict Avoidance**: OVN central runs on a different subnet than transit routing
2. **Network Isolation**: Docker management traffic is separate from OVN logical traffic
3. **Flexibility**: Transit routing subnet can be customized without affecting OVN central
4. **Reliability**: OVN central remains accessible even during transit network changes

### Smart Subnet Selection

When auto-creating the transit-overlay network, the plugin intelligently selects an available subnet:
1. **Primary**: 172.30.0.0/24 (most common choice)
2. **Fallback**: 172.31.0.0/24, 192.168.200.0/24, 192.168.201.0/24
3. **Auto-adjustment**: OVN connection strings automatically use the selected subnet's .5 address

### Persistent State Management

The plugin provides robust state persistence to ensure network configurations survive various restart scenarios:

#### State Storage
- **Location**: `/data` directory within plugin container (configurable via `PLUGIN_DATA_DIR` environment variable)
- **Technology**: Docker's `propagatedmount` feature for reliable persistence
- **Content**: Network mappings, endpoint configurations, IPAM state, OVN topology

#### What Persists
- **Network Definitions**: All created networks with their configuration options
- **Endpoint Mappings**: Container-to-network associations and IP assignments
- **IPAM State**: IP address allocations and availability tracking
- **OVN Topology**: Logical switches, routers, and port configurations
- **Bridge Mappings**: OVS bridge and port relationships

#### Recovery Scenarios
- **Plugin Restart**: Seamless recovery of all network states
- **Plugin Upgrade**: State preserved across version updates
- **Docker Daemon Restart**: Networks and endpoints automatically restored
- **System Reboot**: Full recovery after complete system restart

#### Why Persistence is Critical

Without persistence, plugin restarts would cause:
- **Lost Network Mappings**: Plugin forgets which containers belong to which networks
- **IP Address Conflicts**: IPAM state lost, leading to duplicate IP assignments
- **Broken Connectivity**: Containers can't reconnect to their original networks
- **Inconsistent State**: OVS configuration out of sync with Docker network state

With persistence:
- **Seamless Recovery**: All network configurations restored automatically
- **Zero Downtime**: Running containers maintain connectivity during plugin restarts
- **Consistent IPAM**: IP addresses remain properly allocated and tracked
- **Upgrade Safety**: Plugin upgrades don't disrupt existing deployments

### Required Configuration Examples

```bash
# Minimal OVN network (all required options)
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-my-network \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  my-ovn-network

# With auto-creation of OVN central (recommended)
docker network create --driver ovs-container-network:latest \
  --subnet 10.1.0.0/24 \
  --opt ovn.switch=ls-tenant2 \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  tenant2-overlay

# With additional optional configuration
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-tenant1 \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  --opt bridge=br-int \
  --opt tenant_id=tenant-1 \
  --opt vlan=100 \
  tenant1-network

# Transit network (exempt from OVN switch requirement)
docker network create --driver ovs-container-network:latest \
  --subnet 192.168.100.0/24 \
  --opt ovn.role=transit \
  --opt ovn.external_gateway=192.168.100.1 \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  transit-net
```

### What Will Fail (Missing Required Options)

```bash
# ❌ FAILS - Missing ovn.switch
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  my-network
# Error: ovn.switch is required - this plugin requires OVN configuration

# ❌ FAILS - Missing OVN connections
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-my-network \
  my-network
# Error: ovn.nb_connection and ovn.sb_connection are required when using ovn.switch

# ❌ FAILS - Incomplete OVN connections
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-my-network \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  my-network
# Error: ovn.nb_connection and ovn.sb_connection are required when using ovn.switch
```

## Network Options

### Required Options (for all non-transit networks)

| Option | Description | Default |
|--------|-------------|---------|
| `ovn.switch` | **REQUIRED** - OVN logical switch name | none |
| `ovn.nb_connection` | **REQUIRED** - OVN Northbound DB connection (tcp:host:port) | none |
| `ovn.sb_connection` | **REQUIRED** - OVN Southbound DB connection (tcp:host:port) | none |

### Optional Configuration Options

| Option | Description | Default |
|--------|-------------|---------|
| `bridge` | OVS bridge name | `br-int` |
| `tenant_id` | Tenant identifier for multi-tenancy | none |
| `vlan` | VLAN tag for network isolation | none |
| `mtu` | Maximum transmission unit | 1500 |
| `ipam` | IPAM mode (docker/static/external/ovn) | docker |
| `mirror.ports` | Ports to mirror (comma-separated or "all") | none |
| `mirror.dest` | Destination port for mirrored traffic | none |
| `ovn.router` | OVN logical router name for L3 connectivity | none |
| `ovn.role` | Network role ("transit" for gateway networks, exempts from OVN requirements) | none |
| `ovn.external_gateway` | IP address of external gateway for transit networks | none |
| `ovn.transit_network` | Name of transit network to connect to | none |
| `ovn.auto_create` | Auto-create OVN central container and transit-overlay network if not running | false |
| `ovn.transit_overlay_network` | Custom name for transit overlay Docker network | transit-overlay |
| `ovn.encap` | Encapsulation type (geneve/vxlan) | geneve |
| `ovn.encap_ip` | Encapsulation endpoint IP | none |
| `dhcp` | DHCP mode (none/ovn/external) | none |

### Environment Variables

The plugin supports several environment variables for configuration:

| Variable | Description | Default |
|----------|-------------|---------|
| `PLUGIN_DATA_DIR` | Directory path for persistent state storage | `/data` |
| `PLUGIN_LOG_LEVEL` | Logging level (debug/info/warn/error) | `info` |
| `PLUGIN_STATE_BACKUP` | Enable automatic state file backups | `true` |
| `PLUGIN_RECOVERY_MODE` | State recovery behavior (strict/lenient/skip) | `lenient` |

#### State Recovery Modes

- **strict**: Fail plugin startup if any state file is corrupted or inconsistent
- **lenient**: Skip corrupted state files but log warnings, continue with partial recovery
- **skip**: Ignore all persistent state and start fresh (useful for debugging)

Example plugin configuration with custom environment:
```bash
docker plugin install ovs-container-network:latest \
  --grant-all-permissions \
  PLUGIN_DATA_DIR=/custom/data \
  PLUGIN_LOG_LEVEL=debug \
  PLUGIN_RECOVERY_MODE=strict
```

## Docker Compose Example

```yaml
version: '3.8'

networks:
  ovn-net:
    driver: ovs-container-network:latest
    driver_opts:
      # Required OVN configuration
      ovn.switch: ls-development
      ovn.nb_connection: tcp:172.30.0.5:6641
      ovn.sb_connection: tcp:172.30.0.5:6642
      ovn.auto_create: "true"
      # Optional configuration
      bridge: br-int
      tenant_id: development
      vlan: "100"
    ipam:
      config:
        - subnet: 10.0.0.0/24

services:
  web:
    image: nginx
    networks:
      - ovn-net

  db:
    image: postgres
    networks:
      - ovn-net
```

## IPAM Modes

### Docker Managed (Default)
```bash
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-my-network \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  my-network
```

### Static IP Assignment
```bash
docker run --network my-network --ip 10.0.0.100 alpine
```

### External DHCP
```bash
docker network create --driver ovs-container-network:latest \
  --opt ovn.switch=ls-dhcp-network \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  --opt ipam=external \
  --opt dhcp=ovn \
  dhcp-network
```

## Port Mirroring Example

```bash
# Create network with port mirroring
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-monitored \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  --opt mirror.ports=all \
  --opt mirror.dest=monitor-port \
  monitored-network

# All traffic will be mirrored to monitor-port
```

## OVN Overlay Network Example

```bash
# Create OVN-backed overlay network with auto-managed OVN central
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-prod \
  --opt ovn.encap=geneve \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  --opt dhcp=ovn \
  ovn-overlay

# Containers will use OVN logical switch with GENEVE tunneling
# OVN central will be automatically created and managed
```

## State Persistence Example

Demonstration of how persistent state ensures continuity across plugin lifecycle events:

```bash
# 1. Create network with persistent state
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-prod \
  --opt ovn.auto_create=true \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  production-net

# 2. Launch containers
docker run -d --name web1 --network production-net nginx
docker run -d --name web2 --network production-net nginx

# 3. Verify connectivity
docker exec web1 ping -c 2 web2

# 4. Simulate plugin restart (upgrade scenario)
docker plugin disable ovs-container-network:latest
docker plugin upgrade ovs-container-network:latest
docker plugin enable ovs-container-network:latest

# 5. Verify persistence - containers maintain connectivity
docker exec web1 ping -c 2 web2  # Still works!

# 6. Check state recovery in logs
docker plugin logs ovs-container-network:latest 2>&1 | grep -i "restored\|recovered"

# 7. Launch new container - gets next available IP
docker run -d --name web3 --network production-net nginx
docker exec web3 ping -c 2 web1  # Immediate connectivity

# 8. Inspect persistent state files
sudo find /var/lib/docker/plugins -name "*.json" -path "*/data/*" | head -5
```

### Expected Behavior

- **Before restart**: Containers web1 and web2 communicate successfully
- **During restart**: Plugin state is preserved to disk automatically
- **After restart**:
  - Containers immediately reconnect without IP changes
  - New containers get correct next available IPs
  - OVN topology is fully restored
  - No manual intervention required

## Multi-VPC Transit Network Example

```bash
# 1. Create transit network for inter-VPC routing
docker network create --driver ovs-container-network:latest \
  --subnet 192.168.100.0/24 \
  --opt ovn.role=transit \
  --opt ovn.external_gateway=192.168.100.1 \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  transit-net

# 2. Create VPC-A network
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt tenant_id=tenant-a \
  --opt ovn.switch=ls-vpc-a \
  --opt ovn.router=lr-vpc-a \
  --opt ovn.transit_network=transit-net \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  vpc-a-net

# 3. Create VPC-B network
docker network create --driver ovs-container-network:latest \
  --subnet 10.1.0.0/24 \
  --opt tenant_id=tenant-b \
  --opt ovn.switch=ls-vpc-b \
  --opt ovn.router=lr-vpc-b \
  --opt ovn.transit_network=transit-net \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  vpc-b-net

# 4. Run containers in isolated VPCs with inter-VPC routing
docker run -d --network vpc-a-net --name app-a nginx
docker run -d --network vpc-b-net --name app-b nginx
```

## Multi-Tenant Example

```bash
# Create networks for different tenants with VLAN isolation
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-tenant-a \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  --opt tenant_id=tenant-a \
  --opt vlan=100 \
  tenant-a-net

docker network create --driver ovs-container-network:latest \
  --subnet 10.1.0.0/24 \
  --opt ovn.switch=ls-tenant-b \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  --opt tenant_id=tenant-b \
  --opt vlan=200 \
  tenant-b-net

# Run containers in isolated networks
docker run -d --network tenant-a-net --name app-a nginx
docker run -d --network tenant-b-net --name app-b nginx
```

## Debugging

### View plugin logs:
```bash
make logs
# or
journalctl -u docker -f | grep ovs-container-network
```

### Inspect OVS configuration:
```bash
# Show bridges
sudo ovs-vsctl show

# Show ports on bridge
sudo ovs-vsctl list-ports br-int

# Show port details
sudo ovs-vsctl list interface <port-name>
```

### Inspect OVN configuration:
```bash
# Show OVN logical topology
docker exec ovn-central ovn-nbctl show

# Show OVN physical bindings
docker exec ovn-central ovn-sbctl show

# List logical switches
docker exec ovn-central ovn-nbctl ls-list

# List logical routers
docker exec ovn-central ovn-nbctl lr-list
```

### Inspect network:
```bash
docker network inspect my-ovs-network
```

## Development

### Building from source:
```bash
make build           # Build binary
make docker-build    # Build Docker image
make test           # Run tests
```

### Running in development mode:
```bash
make dev-run        # Run plugin locally with debug logging
```

### Testing:
```bash
make test-integration  # Run full integration test suite
```

## Architecture

### Plugin Configuration
The plugin requires access to several system resources:
- `/var/run/docker.sock` - **Critical**: Docker API access for OVN container and transit-overlay network management
- `/var/run/openvswitch` - OVS daemon socket access for bridge operations
- `/var/run/ovn` - OVN daemon socket access (when available locally)
- `/sys` - System information for network namespace operations
- `/data` - Persistent state storage directory (configurable via `PLUGIN_DATA_DIR`)
- `CAP_NET_ADMIN`, `CAP_SYS_ADMIN`, `CAP_SYS_MODULE` capabilities

**Note**: Docker socket access is essential for:
- Creating and managing the transit-overlay Docker network when `ovn.auto_create=true`
- Automatic OVN central container lifecycle management
- Persistent state management and recovery operations
- Container network attachment and detachment operations

### State Persistence Architecture

The plugin uses Docker's `propagatedmount` feature to maintain persistent state:

#### Storage Structure
```
/data/
├── networks/           # Network configuration files
│   ├── <network-id>.json
│   └── ...
├── endpoints/          # Endpoint state files
│   ├── <endpoint-id>.json
│   └── ...
├── ipam/              # IPAM state tracking
│   ├── <network-id>-pool.json
│   └── ...
└── ovn/               # OVN topology state
    ├── logical-switches.json
    ├── logical-routers.json
    └── port-bindings.json
```

#### Recovery Process
1. **Plugin Start**: Read all state files from `/data` directory
2. **Network Restoration**: Recreate network objects from saved configurations
3. **Endpoint Recovery**: Restore container-to-network mappings
4. **IPAM Synchronization**: Rebuild IP allocation tracking
5. **OVS Reconciliation**: Ensure OVS configuration matches saved state
6. **OVN Topology Rebuild**: Restore logical switches and routers if using OVN

#### Consistency Guarantees
- **Atomic Updates**: State changes written atomically to prevent corruption
- **Checksum Validation**: State files include checksums for integrity verification
- **Rollback Protection**: Invalid state files are backed up and skipped during recovery
- **Lock Coordination**: File-based locking prevents concurrent state modifications

### OVN Auto-Management
When `ovn.auto_create: true` is set, the plugin automatically manages OVN central:

#### Transit-Overlay Network Creation
1. **Network Discovery**: Checks if transit-overlay network exists (default name: `transit-overlay`)
2. **Smart Subnet Selection**: If network doesn't exist, tries multiple subnets:
   - Primary: 172.30.0.0/24
   - Fallbacks: 172.31.0.0/24, 192.168.200.0/24, 192.168.201.0/24
3. **Network Creation**: Creates Docker bridge network with selected subnet
4. **IP Assignment**: Assigns .5 address to OVN central (e.g., 172.30.0.5)

#### OVN Central Container Management
1. **Reachability Check**: Tests OVN connection at specified endpoints
2. **Container Creation**: If unreachable, creates `ovn-central` container with:
   - Connection to transit-overlay network at .5 IP
   - Proper OVN northbound/southbound database configuration
   - Required volumes and environment variables
   - Persistent storage for OVN database state
3. **Service Readiness**: Waits for OVN services to become available
4. **State Recovery**: Restores OVN logical topology from persistent state if available
5. **Network Configuration**: Proceeds with logical network setup

#### Connection String Auto-Update
- OVN connection strings automatically adjust to the selected subnet
- Default connections use 172.30.0.5:6641/6642 (northbound/southbound)
- Custom transit overlay networks use their respective .5 addresses

### Transit Networks
Transit networks (`ovn.role: transit`) enable inter-VPC routing by:
1. Creating a gateway logical router (`lr-gateway`)
2. Setting up external gateway configuration for NAT
3. Automatically disabling port security for NAT gateway ports
4. Enabling routing between connected VPC networks

## Troubleshooting

### Common Configuration Errors

#### Missing OVN Configuration

**Error**: `ovn.switch is required - this plugin requires OVN configuration`

**Cause**: Attempting to create a network without specifying the required `ovn.switch` option.

**Solution**: All networks (except transit networks) must specify an OVN logical switch:
```bash
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-my-network \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  my-network
```

#### Missing OVN Database Connections

**Error**: `ovn.nb_connection and ovn.sb_connection are required when using ovn.switch`

**Cause**: Specified `ovn.switch` but missing one or both OVN database connection strings.

**Solution**: Both northbound and southbound connections are required:
```bash
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-my-network \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  my-network
```

#### OVN Central Not Reachable

**Error**: `OVN central not reachable at tcp:172.30.0.5:6641 and auto-create not enabled`

**Cause**: OVN central container is not running and `ovn.auto_create` is not set to `true`.

**Solution**: Either manually start OVN central or enable auto-creation:
```bash
# Option 1: Enable auto-creation (recommended)
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-my-network \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  my-network

# Option 2: Manually start OVN central
docker run -d --name ovn-central \
  --network transit-overlay \
  --ip 172.30.0.5 \
  -p 6641:6641 -p 6642:6642 \
  ovn-central:latest
```

#### Legacy Configuration Attempts

**Error**: Trying to create networks without OVN configuration based on older documentation.

**Cause**: This plugin now requires OVN for all networks. The old OVS-only mode is no longer supported.

**Solution**: Migrate to OVN-based configuration:
```bash
# Old (no longer works):
# docker network create --driver ovs-container-network:latest --subnet 10.0.0.0/24 my-net

# New (required):
docker network create --driver ovs-container-network:latest \
  --subnet 10.0.0.0/24 \
  --opt ovn.switch=ls-my-network \
  --opt ovn.nb_connection=tcp:172.30.0.5:6641 \
  --opt ovn.sb_connection=tcp:172.30.0.5:6642 \
  --opt ovn.auto_create=true \
  my-network
```

### Installation and Runtime Issues

#### Plugin won't install
- Ensure Docker daemon is running
- Check OVS is installed and running: `sudo ovs-vsctl show`
- Verify permissions: `--grant-all-permissions` flag is needed
- Ensure Docker socket is accessible: `ls -la /var/run/docker.sock`

### OVN auto-creation fails
- Verify Docker socket access: `docker ps` should work
- Check if `ovn-central:latest` image exists: `docker images | grep ovn-central`
- Ensure transit network exists if specified in connection string
- Check plugin logs for Docker API errors
- Verify persistent state directory is writable: `ls -la /var/lib/docker/plugins/<plugin-id>/data`
- Check for state file corruption: look for `.backup` files in state directory

### Transit-overlay network creation issues
- **Subnet conflicts**: If all default subnets (172.30.0.0/24, 172.31.0.0/24, 192.168.200.0/24, 192.168.201.0/24) are in use:
  ```bash
  # Check existing networks and their subnets
  docker network ls
  docker network inspect <network_name> | grep Subnet

  # Pre-create custom transit-overlay network
  docker network create --driver bridge \
    --subnet 10.200.0.0/24 \
    --gateway 10.200.0.1 \
    my-transit-overlay

  # Use custom network in plugin
  --opt ovn.transit_overlay_network=my-transit-overlay \
  --opt ovn.nb_connection=tcp:10.200.0.5:6641 \
  --opt ovn.sb_connection=tcp:10.200.0.5:6642
  ```
- **Network name conflicts**: Use custom name via `ovn.transit_overlay_network` option
- **IP assignment conflicts**: Plugin automatically uses .5 address on selected subnet

### Network separation confusion
- **Transit-overlay (172.30.0.0/24)**: Docker bridge hosting OVN central container
- **Transit-net (192.168.100.0/24)**: OVN logical network for inter-VPC routing
- These are separate networks with different purposes and IP ranges
- OVN central connections always use transit-overlay IPs (e.g., 172.30.0.5)
- VPC routing uses transit-net IPs (e.g., 192.168.100.x)

### Containers can't communicate
- Check VLAN configuration matches between containers
- Verify OVS flows: `sudo ovs-ofctl dump-flows br-int`
- Check external_ids: `sudo ovs-vsctl list interface`
- For OVN networks, verify logical topology: `docker exec ovn-central ovn-nbctl show`
- Check persistent state consistency: compare saved state with actual OVS/OVN configuration
- Verify endpoint state files exist: `ls /var/lib/docker/plugins/<plugin-id>/data/endpoints/`

### Inter-VPC routing issues
- Verify transit network is properly configured with `ovn.role=transit`
- Check gateway router exists: `docker exec ovn-central ovn-nbctl lr-list`
- Ensure external gateway is set for transit network
- Verify port security is disabled on NAT gateway ports

### Performance issues
- Check MTU settings for overlay networks
- Verify OVS datapath: `sudo ovs-dpctl show`
- Monitor CPU usage of ovs-vswitchd process
- For OVN, check tunnel status: `docker exec ovn-central ovn-sbctl show`
- Monitor state file I/O: persistent operations can impact performance during high churn
- Check state directory disk usage: large numbers of networks/endpoints require adequate storage

### State persistence issues
- **State corruption**: Check for `.backup` files indicating recovery failures:
  ```bash
  ls /var/lib/docker/plugins/<plugin-id>/data/*/*.backup
  ```
- **Permission issues**: Ensure plugin can write to data directory:
  ```bash
  ls -la /var/lib/docker/plugins/<plugin-id>/data/
  ```
- **Disk space**: Verify adequate storage for state files:
  ```bash
  df -h /var/lib/docker/plugins/<plugin-id>/data/
  ```
- **Recovery failures**: Check plugin logs for state loading errors during startup
- **Inconsistent state**: Compare saved network state with actual Docker networks:
  ```bash
  # Compare saved networks with Docker networks
  docker network ls --format "table {{.ID}}\t{{.Name}}\t{{.Driver}}"
  ls /var/lib/docker/plugins/<plugin-id>/data/networks/
  ```

## Roadmap

- [x] Phase 1: Basic OVS integration
- [x] Phase 2: Advanced OVS features (VLANs, tenant tracking)
- [x] Phase 3: OVN integration (logical switches, overlay)
- [x] Phase 4: Auto-managed OVN central and transit networks
- [ ] Phase 5: Production features (IPv6, QoS, metrics)
- [ ] Phase 6: High availability and clustering

## Contributing

Contributions are welcome! Please see CONTRIBUTING.md for guidelines.

## License

MIT License - See LICENSE file for details

## Support

For issues and questions:
- GitHub Issues: https://github.com/liquescent-development/ovs-container-network/issues
- Documentation: https://github.com/liquescent-development/ovs-container-network/wiki