package driver

import (
	"context"
	"crypto/rand"
	"encoding/json"
	"fmt"
	"net"
	"os"
	"os/exec"
	"strings"
	"sync"
	"time"

	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/filters"
	"github.com/docker/docker/api/types/image"
	"github.com/docker/docker/api/types/mount"
	"github.com/docker/docker/api/types/network"
	"github.com/docker/docker/client"
	"github.com/docker/go-connections/nat"
	dnetwork "github.com/docker/go-plugins-helpers/network"
	"github.com/ovs-container-lab/ovs-container-network/pkg/ovn"
	"github.com/ovs-container-lab/ovs-container-network/pkg/ovs"
	"github.com/ovs-container-lab/ovs-container-network/pkg/store"
	"github.com/ovs-container-lab/ovs-container-network/pkg/types"
	"github.com/sirupsen/logrus"
	"github.com/vishvananda/netlink"
)

// Driver implements the Docker network driver interface
type Driver struct {
	sync.RWMutex
	networks  map[string]*types.Network
	endpoints map[string]*types.Endpoint
	ovs       *ovs.Client
	ovn       *ovn.Client // Optional OVN client
	store     *store.Store
	logger    *logrus.Logger
}

// New creates a new OVS network driver
func New() (*Driver, error) {
	logger := logrus.New()
	logger.SetLevel(logrus.GetLevel())

	// Initialize persistent store
	dataDir := os.Getenv("PLUGIN_DATA_DIR")
	if dataDir == "" {
		dataDir = "/data"
	}

	pluginStore, err := store.NewStore(dataDir)
	if err != nil {
		return nil, fmt.Errorf("failed to initialize store: %w", err)
	}

	ovsClient, err := ovs.NewClient()
	if err != nil {
		return nil, fmt.Errorf("failed to create OVS client: %w", err)
	}

	// Verify OVS is accessible
	if err := ovsClient.Ping(); err != nil {
		return nil, fmt.Errorf("OVS is not accessible: %w", err)
	}

	driver := &Driver{
		networks:  make(map[string]*types.Network),
		endpoints: make(map[string]*types.Endpoint),
		ovs:       ovsClient,
		store:     pluginStore,
		logger:    logger,
	}

	// OVN client will be initialized per network if ovn.nb_connection is provided
	// This allows different networks to use different OVN clusters
	driver.ovn = nil

	// Recover existing state from persistent storage
	if err := driver.recoverState(); err != nil {
		logger.WithError(err).Error("Failed to recover state, starting fresh")
		// Non-fatal: we can continue with empty state
	}

	return driver, nil
}

// recoverState restores plugin state from persistent storage
func (d *Driver) recoverState() error {
	d.logger.Info("Recovering plugin state from persistent storage")

	// Load networks from store
	storedNetworks := d.store.ListNetworks()
	for _, netInfo := range storedNetworks {
		d.logger.Infof("Recovering network %s (%s)", netInfo.Name, netInfo.ID)

		// Reconstruct network object
		network := &types.Network{
			ID:       netInfo.ID,
			Bridge:   netInfo.Bridge,
			VLAN:     fmt.Sprintf("%d", netInfo.VLAN),
			TenantID: netInfo.TenantID,
			Options:  netInfo.Options,
		}

		// Verify OVS bridge still exists (just check if we can list it)
		bridges, err := d.ovs.ListBridges()
		if err == nil {
			found := false
			for _, br := range bridges {
				if br == netInfo.Bridge {
					found = true
					break
				}
			}
			if !found {
				d.logger.Warnf("Bridge %s for network %s no longer exists, will recreate on demand",
					netInfo.Bridge, netInfo.ID)
			}
		}

		// If OVN is configured, verify logical switch exists
		if netInfo.OVNSwitch != "" {
			// We'll check this when OVN client is initialized per-network
			network.Options["ovn.switch"] = netInfo.OVNSwitch
			if netInfo.OVNRouter != "" {
				network.Options["ovn.router"] = netInfo.OVNRouter
			}
		}

		d.networks[netInfo.ID] = network
	}

	// Load endpoints from store
	// Note: We don't recreate veth pairs here as Docker will call CreateEndpoint again
	// for any active containers when they restart
	endpoints := d.store.ListEndpoints()
	for _, epInfo := range endpoints {
		d.logger.Infof("Recovering endpoint %s on network %s", epInfo.EndpointID, epInfo.NetworkID)

		endpoint := &types.Endpoint{
			ID:          epInfo.EndpointID,
			NetworkID:   epInfo.NetworkID,
			VethName:    epInfo.VethName,
			MacAddress:  epInfo.MACAddress,
			IPv4Address: epInfo.IPAddress,
		}

		// Store in memory map
		key := fmt.Sprintf("%s:%s", epInfo.NetworkID, epInfo.EndpointID)
		d.endpoints[key] = endpoint
	}

	d.logger.Infof("Recovered %d networks and %d endpoints",
		len(d.networks), len(d.endpoints))

	return nil
}

// GetCapabilities returns the driver capabilities
func (d *Driver) GetCapabilities() (*dnetwork.CapabilitiesResponse, error) {
	d.logger.Debug("GetCapabilities called")
	return &dnetwork.CapabilitiesResponse{
		Scope:             dnetwork.LocalScope,
		ConnectivityScope: dnetwork.LocalScope,
	}, nil
}

// ensureOVNCentral checks if OVN central is running and optionally creates it
func (d *Driver) ensureOVNCentral(nbConn, sbConn string, autoCreate bool, transitNetwork string) error {
	// Extract host and port from connection string
	// Format: tcp:192.168.100.5:6641
	if !strings.HasPrefix(nbConn, "tcp:") {
		return fmt.Errorf("unsupported connection format: %s", nbConn)
	}

	nbAddr := strings.TrimPrefix(nbConn, "tcp:")

	// Try to connect to check if OVN is already running
	d.logger.Infof("Checking if OVN is reachable at %s", nbAddr)
	conn, err := net.DialTimeout("tcp", nbAddr, 2*time.Second)
	if err == nil {
		conn.Close()
		d.logger.Infof("OVN central is already running at %s", nbAddr)
		return nil
	}

	// OVN is not reachable
	if !autoCreate {
		return fmt.Errorf("OVN central not reachable at %s and auto-create not enabled", nbAddr)
	}

	// Auto-create OVN central container using Docker API
	d.logger.Infof("OVN central not found, creating container...")

	// Parse IP from connection string
	parts := strings.Split(nbAddr, ":")
	if len(parts) != 2 {
		return fmt.Errorf("invalid address format: %s", nbAddr)
	}
	ovnIP := parts[0]

	// Create Docker client using Unix socket
	// The plugin has access to /var/run/docker.sock
	cli, err := client.NewClientWithOpts(client.FromEnv, client.WithAPIVersionNegotiation())
	if err != nil {
		return fmt.Errorf("failed to create Docker client: %w", err)
	}
	defer cli.Close()

	ctx := context.Background()

	// Check if transit-overlay network exists, create if needed
	transitNetworkName := transitNetwork
	if transitNetworkName == "" {
		transitNetworkName = "transit-overlay" // default
	}
	networks, err := cli.NetworkList(ctx, network.ListOptions{})
	if err != nil {
		return fmt.Errorf("failed to list networks: %w", err)
	}

	transitNetworkExists := false
	var existingNetwork network.Summary
	for _, net := range networks {
		if net.Name == transitNetworkName {
			transitNetworkExists = true
			existingNetwork = net
			break
		}
	}

	// If network exists, get its subnet to determine OVN IP
	if transitNetworkExists && len(existingNetwork.IPAM.Config) > 0 {
		subnet := existingNetwork.IPAM.Config[0].Subnet
		if subnet != "" && subnet != "192.168.100.0/24" {
			// Extract the network prefix and use .5 for OVN central
			prefix := strings.TrimSuffix(subnet, ".0/24")
			ovnIP = prefix + ".5"
			d.logger.Infof("Using existing transit network %s, OVN central IP: %s", subnet, ovnIP)
		}
	}

	if !transitNetworkExists {
		d.logger.Infof("Creating transit-overlay network for OVN central...")

		// Try to create the network, using a different subnet than transit-net
		// transit-net uses 192.168.100.0/24, so we use 172.30.0.0/24 for transit-overlay
		subnets := []string{"172.30.0.0/24", "172.31.0.0/24", "192.168.200.0/24", "192.168.201.0/24"}
		var createErr error

		for _, subnet := range subnets {
			gateway := strings.Replace(subnet, ".0/24", ".1", 1)
			d.logger.Debugf("Trying to create transit-overlay with subnet %s", subnet)

			_, createErr = cli.NetworkCreate(ctx, transitNetworkName, network.CreateOptions{
				Driver: "bridge",
				IPAM: &network.IPAM{
					Config: []network.IPAMConfig{
						{
							Subnet:  subnet,
							Gateway: gateway,
						},
					},
				},
			})

			if createErr == nil {
				d.logger.Infof("Created transit-overlay network with subnet %s", subnet)

				// Always update the OVN IP to match the subnet we're using
				// Extract the network prefix and use .5 for OVN central
				prefix := strings.TrimSuffix(subnet, ".0/24")
				ovnIP = prefix + ".5"
				d.logger.Infof("OVN central will use IP %s on transit-overlay network", ovnIP)
				break
			}

			// If error is not about overlapping pool, fail immediately
			if !strings.Contains(createErr.Error(), "Pool overlaps") {
				return fmt.Errorf("failed to create transit-overlay network: %w", createErr)
			}
		}

		if createErr != nil {
			return fmt.Errorf("failed to create transit-overlay network: all subnets in use: %w", createErr)
		}
	}

	// Check if container already exists
	containers, err := cli.ContainerList(ctx, container.ListOptions{
		All:     true,
		Filters: filters.NewArgs(filters.Arg("name", "ovn-central")),
	})
	if err != nil {
		return fmt.Errorf("failed to list containers: %w", err)
	}

	if len(containers) > 0 {
		// Container exists, start it if not running
		containerID := containers[0].ID
		if containers[0].State != "running" {
			d.logger.Infof("Starting existing OVN central container...")
			if err := cli.ContainerStart(ctx, containerID, container.StartOptions{}); err != nil {
				return fmt.Errorf("failed to start OVN central container: %w", err)
			}
		}
	} else {
		// Create new container
		d.logger.Infof("Creating new OVN central container...")

		// Check if image exists, pull if necessary
		images, err := cli.ImageList(ctx, image.ListOptions{
			Filters: filters.NewArgs(filters.Arg("reference", "ovn-central:latest")),
		})
		if err != nil {
			return fmt.Errorf("failed to list images: %w", err)
		}

		if len(images) == 0 {
			// For now, we'll assume the image is already built
			// In production, you might want to pull from a registry
			return fmt.Errorf("OVN central image not found. Please build it first with: docker build -t ovn-central:latest ./ovn-container")
		}

		// Create container configuration
		containerConfig := &container.Config{
			Image:    "ovn-central:latest",
			Hostname: "ovn-central",
			ExposedPorts: nat.PortSet{
				"6641/tcp": struct{}{},
				"6642/tcp": struct{}{},
			},
		}

		hostConfig := &container.HostConfig{
			RestartPolicy: container.RestartPolicy{
				Name: "unless-stopped",
			},
			Privileged: true,
			PortBindings: nat.PortMap{
				"6641/tcp": []nat.PortBinding{{HostIP: "0.0.0.0", HostPort: "6641"}},
				"6642/tcp": []nat.PortBinding{{HostIP: "0.0.0.0", HostPort: "6642"}},
			},
			Mounts: []mount.Mount{
				{
					Type:   mount.TypeVolume,
					Source: "ovn-nb-db",
					Target: "/var/lib/ovn",
				},
				{
					Type:   mount.TypeVolume,
					Source: "ovn-logs",
					Target: "/var/log/ovn",
				},
			},
			CapAdd: []string{"NET_ADMIN", "SYS_MODULE", "SYS_NICE"},
		}

		networkingConfig := &network.NetworkingConfig{
			EndpointsConfig: map[string]*network.EndpointSettings{
				"transit-overlay": {
					IPAMConfig: &network.EndpointIPAMConfig{
						IPv4Address: ovnIP,
					},
				},
			},
		}

		resp, err := cli.ContainerCreate(ctx, containerConfig, hostConfig, networkingConfig, nil, "ovn-central")
		if err != nil {
			return fmt.Errorf("failed to create OVN central container: %w", err)
		}

		// Start the container
		if err := cli.ContainerStart(ctx, resp.ID, container.StartOptions{}); err != nil {
			return fmt.Errorf("failed to start OVN central container: %w", err)
		}

		d.logger.Infof("Created and started OVN central container: %s", resp.ID)
	}

	// Wait for OVN to be ready
	d.logger.Infof("Waiting for OVN central to be ready...")
	waitCtx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	for {
		select {
		case <-waitCtx.Done():
			return fmt.Errorf("timeout waiting for OVN central to be ready")
		case <-time.After(1 * time.Second):
			conn, err := net.DialTimeout("tcp", nbAddr, 1*time.Second)
			if err == nil {
				conn.Close()
				d.logger.Infof("OVN central is ready at %s", nbAddr)
				return nil
			}
		}
	}
}

// CreateNetwork creates a new network
func (d *Driver) CreateNetwork(req *dnetwork.CreateNetworkRequest) error {
	d.Lock()
	defer d.Unlock()

	d.logger.WithFields(logrus.Fields{
		"network_id": req.NetworkID,
		"options":    req.Options,
		"ipv4_data":  req.IPv4Data,
		"ipv6_data":  req.IPv6Data,
	}).Info("CreateNetwork called")

	// Check if network already exists
	if _, exists := d.networks[req.NetworkID]; exists {
		return fmt.Errorf("network %s already exists", req.NetworkID)
	}

	// Parse network options
	netConfig := &types.Network{
		ID:      req.NetworkID,
		Bridge:  "br-int", // Default bridge
		Options: make(map[string]string),
	}

	// Docker passes driver options under the "com.docker.network.generic" key
	var driverOpts map[string]interface{}
	if generic, ok := req.Options["com.docker.network.generic"]; ok {
		if genericMap, ok := generic.(map[string]interface{}); ok {
			driverOpts = genericMap
			d.logger.Infof("Found driver options under generic key: %v", driverOpts)
		} else {
			d.logger.Warnf("Generic options not a map: %T", generic)
			driverOpts = req.Options
		}
	} else {
		// Fallback to direct options
		driverOpts = req.Options
	}

	// Process options
	d.logger.Infof("Processing %d driver options", len(driverOpts))
	for key, value := range driverOpts {
		strValue, ok := value.(string)
		if !ok {
			// If it's not a string, try to convert it
			strValue = fmt.Sprintf("%v", value)
		}

		d.logger.Debugf("Option %s = %s", key, strValue)

		switch key {
		case "bridge":
			netConfig.Bridge = strValue
			d.logger.Infof("Set bridge to: %s", strValue)
		case "tenant_id":
			netConfig.TenantID = strValue
			d.logger.Infof("Set tenant_id to: %s", strValue)
		case "vlan":
			netConfig.VLAN = strValue
			d.logger.Infof("Set VLAN to: %s", strValue)
		case "mtu":
			netConfig.MTU = strValue
			d.logger.Infof("Set MTU to: %s", strValue)
		case "ovn.switch":
			netConfig.OVNSwitch = strValue
			d.logger.Infof("Set OVN switch to: %s", strValue)
		case "ovn.router":
			netConfig.OVNRouter = strValue
			d.logger.Infof("Set OVN router to: %s", strValue)
		case "ovn.role":
			netConfig.Options["ovn.role"] = strValue
			d.logger.Infof("Set OVN role to: %s", strValue)
		case "ovn.external_gateway":
			netConfig.Options["ovn.external_gateway"] = strValue
			d.logger.Infof("Set external gateway to: %s", strValue)
		case "ovn.transit_network":
			netConfig.Options["ovn.transit_network"] = strValue
			d.logger.Infof("Set transit network to: %s", strValue)
		case "mirror.ports":
			netConfig.MirrorPorts = strValue
			d.logger.Infof("Set mirror ports to: %s", strValue)
		case "mirror.dest":
			netConfig.MirrorDest = strValue
			d.logger.Infof("Set mirror dest to: %s", strValue)
		default:
			netConfig.Options[key] = strValue
			d.logger.Debugf("Stored option %s = %s", key, strValue)
		}
	}

	// Store IPv4 configuration
	if len(req.IPv4Data) > 0 {
		netConfig.IPv4Data = req.IPv4Data[0]
	}

	// Store IPv6 configuration if provided
	if len(req.IPv6Data) > 0 {
		netConfig.IPv6Data = req.IPv6Data[0]
	}

	// Create or verify the OVS bridge exists
	if err := d.ovs.EnsureBridge(netConfig.Bridge); err != nil {
		return fmt.Errorf("failed to ensure bridge %s: %w", netConfig.Bridge, err)
	}

	// Check if this is a transit network
	if role := netConfig.Options["ovn.role"]; role == "transit" {
		d.logger.Infof("Creating transit network")
		return d.createTransitNetwork(req, netConfig)
	}

	// OVN configuration is REQUIRED for all non-transit networks
	if netConfig.OVNSwitch == "" {
		return fmt.Errorf("ovn.switch is required - this plugin requires OVN configuration")
	}

	// Check that OVN connections are provided
	nbConn := netConfig.Options["ovn.nb_connection"]
	sbConn := netConfig.Options["ovn.sb_connection"]

	d.logger.Infof("OVN switch: '%s'", netConfig.OVNSwitch)
	d.logger.Infof("OVN NB connection: '%s'", nbConn)
	d.logger.Infof("OVN SB connection: '%s'", sbConn)

	if nbConn == "" || sbConn == "" {
		return fmt.Errorf("ovn.nb_connection and ovn.sb_connection are required when using ovn.switch '%s'", netConfig.OVNSwitch)
	}

	// Check if auto-create is enabled
	autoCreate := netConfig.Options["ovn.auto_create"] == "true"
	transitNetwork := netConfig.Options["ovn.transit_overlay_network"] // optional custom network

	// Ensure OVN central is running (create if needed and enabled)
	if err := d.ensureOVNCentral(nbConn, sbConn, autoCreate, transitNetwork); err != nil {
		return fmt.Errorf("failed to ensure OVN central: %w", err)
	}

	// Initialize OVN client for this network if not already done
	if d.ovn == nil {
		d.logger.Infof("Initializing OVN client for NB=%s, SB=%s", nbConn, sbConn)
		ovnClient, err := ovn.NewClient(nbConn, sbConn)
		if err != nil {
			d.logger.Errorf("Failed to connect to OVN: %v", err)
			return fmt.Errorf("failed to connect to OVN at %s: %w", nbConn, err)
		}
		d.ovn = ovnClient
		d.logger.Infof("Connected to OVN at %s", nbConn)
	} else {
		d.logger.Infof("Using existing OVN client")
	}
	d.logger.Infof("Creating OVN logical switch: %s", netConfig.OVNSwitch)

	ovnOptions := make(map[string]string)
	ovnOptions["network_id"] = req.NetworkID
	if netConfig.TenantID != "" {
		ovnOptions["tenant_id"] = netConfig.TenantID
	}

	if err := d.ovn.CreateLogicalSwitch(netConfig.OVNSwitch, ovnOptions); err != nil {
		return fmt.Errorf("failed to create OVN logical switch: %w", err)
	}

	// If DHCP is enabled, create DHCP options
	if netConfig.Options["dhcp"] == "ovn" && netConfig.IPv4Data != nil {
		dhcpOpts := map[string]string{
			"lease_time": "3600",
			"router":     netConfig.IPv4Data.Gateway,
		}
		if dns := netConfig.Options["dns_server"]; dns != "" {
			dhcpOpts["dns_server"] = dns
		}

		dhcpUUID, err := d.ovn.CreateDHCPOptions(
			netConfig.IPv4Data.Pool,
			"02:00:00:00:00:01", // Default server MAC
			netConfig.IPv4Data.Gateway,
			dhcpOpts,
		)
		if err != nil {
			d.logger.Warnf("Failed to create OVN DHCP options: %v", err)
		} else {
			netConfig.Options["dhcp_uuid"] = dhcpUUID
		}
	}

	// Encapsulation is configured at the chassis level via orchestrator setup-chassis command
	// The Docker plugin doesn't need to handle this

	// Create or connect to L3 router if specified
	if netConfig.OVNRouter != "" && netConfig.IPv4Data != nil {
		d.logger.Infof("Setting up L3 gateway with router: %s", netConfig.OVNRouter)

		// Create router if it doesn't exist
		routerOpts := make(map[string]string)
		routerOpts["network_id"] = req.NetworkID
		if netConfig.TenantID != "" {
			routerOpts["tenant_id"] = netConfig.TenantID
		}

		if err := d.ovn.CreateLogicalRouter(netConfig.OVNRouter, routerOpts); err != nil {
			return fmt.Errorf("failed to create logical router %s: %w", netConfig.OVNRouter, err)
		}

		// Create router port - must be unique per switch
		routerPort := fmt.Sprintf("rp-%s", netConfig.OVNSwitch)
		routerMAC := "02:00:00:00:01:01" // Default router MAC
		// The gateway already includes CIDR notation from Docker
		routerNetwork := netConfig.IPv4Data.Gateway

		// Create the router port
		if err := d.ovn.CreateLogicalRouterPort(
			netConfig.OVNRouter,
			routerPort,
			routerMAC,
			[]string{routerNetwork},
		); err != nil {
			return fmt.Errorf("failed to create router port: %w", err)
		}

		// Create corresponding switch port of type "router" - must be unique per switch
		switchPort := fmt.Sprintf("sp-%s-%s", netConfig.OVNRouter, netConfig.OVNSwitch)
		switchPortOpts := map[string]string{
			"type":        "router",
			"router-port": routerPort,
		}

		if err := d.ovn.CreateLogicalPort(
			netConfig.OVNSwitch,
			switchPort,
			"", // No MAC needed for router type port
			"", // No IP needed for router type port
			switchPortOpts,
		); err != nil {
			return fmt.Errorf("failed to create switch port for router connection: %w", err)
		}
		d.logger.Infof("Connected router %s to switch %s", netConfig.OVNRouter, netConfig.OVNSwitch)

		// Connect to transit network if specified
		if transitNet := netConfig.Options["ovn.transit_network"]; transitNet != "" {
			d.logger.Infof("Connecting to transit network: %s", transitNet)
			if err := d.connectToTransitNetwork(netConfig.OVNRouter, transitNet); err != nil {
				return fmt.Errorf("failed to connect to transit network: %w", err)
			}
		}

		// Add default route if external gateway is specified
		if extGW := netConfig.Options["ovn.external_gateway"]; extGW != "" {
			// This would add a default route to the external gateway
			// Implementation depends on your network topology
			d.logger.Infof("External gateway configured: %s", extGW)
		}
	}

	// Store the network configuration
	d.networks[req.NetworkID] = netConfig

	// Persist to store
	vlan := 0
	if netConfig.VLAN != "" {
		fmt.Sscanf(netConfig.VLAN, "%d", &vlan)
	}

	storeInfo := &store.NetworkInfo{
		ID:        req.NetworkID,
		Name:      req.NetworkID, // Docker doesn't provide a separate name
		Bridge:    netConfig.Bridge,
		VLAN:      vlan,
		TenantID:  netConfig.TenantID,
		OVNSwitch: netConfig.OVNSwitch,
		OVNRouter: netConfig.OVNRouter,
		Options:   netConfig.Options,
	}

	if req.IPv4Data != nil && len(req.IPv4Data) > 0 {
		ipamData, _ := json.Marshal(req.IPv4Data[0])
		storeInfo.IPAMData = ipamData
	}

	if err := d.store.SaveNetwork(storeInfo); err != nil {
		d.logger.WithError(err).Warn("Failed to persist network to store")
		// Non-fatal: continue even if we can't persist
	}

	d.logger.Infof("Network %s created successfully on bridge %s", req.NetworkID, netConfig.Bridge)
	return nil
}

// AllocateNetwork allocates resources for a network
func (d *Driver) AllocateNetwork(req *dnetwork.AllocateNetworkRequest) (*dnetwork.AllocateNetworkResponse, error) {
	d.logger.WithField("network_id", req.NetworkID).Debug("AllocateNetwork called")
	// No special allocation needed for OVS
	return &dnetwork.AllocateNetworkResponse{}, nil
}

// DeleteNetwork deletes a network
func (d *Driver) DeleteNetwork(req *dnetwork.DeleteNetworkRequest) error {
	d.Lock()
	defer d.Unlock()

	d.logger.WithField("network_id", req.NetworkID).Info("DeleteNetwork called")

	net, exists := d.networks[req.NetworkID]
	if !exists {
		d.logger.Warnf("Network %s not found", req.NetworkID)
		return nil // Idempotent
	}

	// Check if there are any endpoints still attached
	for _, ep := range d.endpoints {
		if ep.NetworkID == req.NetworkID {
			return fmt.Errorf("network %s still has active endpoints", req.NetworkID)
		}
	}

	// In a multi-host environment, OVN logical switches and routers are shared
	// resources that may have containers from other hosts. We should NOT delete them.
	// The orchestrator or admin should manage the lifecycle of these shared resources.
	if net.OVNSwitch != "" && d.ovn != nil {
		d.logger.Infof("Network %s removed, keeping OVN switch %s (shared resource)", req.NetworkID, net.OVNSwitch)
	}

	// Clean up any OVS-specific resources if needed
	// For now, we keep the bridge as it might be shared

	delete(d.networks, req.NetworkID)

	// Remove from store
	if err := d.store.DeleteNetwork(req.NetworkID); err != nil {
		d.logger.WithError(err).Warn("Failed to remove network from store")
		// Non-fatal: continue even if we can't remove from store
	}

	d.logger.Infof("Network %s deleted", req.NetworkID)
	return nil
}

// FreeNetwork frees network resources
func (d *Driver) FreeNetwork(req *dnetwork.FreeNetworkRequest) error {
	d.logger.WithField("network_id", req.NetworkID).Debug("FreeNetwork called")
	// No special cleanup needed
	return nil
}

// CreateEndpoint creates a new endpoint
func (d *Driver) CreateEndpoint(req *dnetwork.CreateEndpointRequest) (*dnetwork.CreateEndpointResponse, error) {
	d.Lock()
	defer d.Unlock()

	d.logger.WithFields(logrus.Fields{
		"network_id":  req.NetworkID,
		"endpoint_id": req.EndpointID,
		"interface":   req.Interface,
		"options":     req.Options,
	}).Info("CreateEndpoint called")

	net, exists := d.networks[req.NetworkID]
	if !exists {
		return nil, fmt.Errorf("network %s not found", req.NetworkID)
	}

	ep := &types.Endpoint{
		ID:        req.EndpointID,
		NetworkID: req.NetworkID,
		Network:   net,
	}

	// Store MAC address if provided
	if req.Interface != nil && req.Interface.MacAddress != "" {
		ep.MacAddress = req.Interface.MacAddress
	}

	// Store IPv4 address if provided
	if req.Interface != nil && req.Interface.Address != "" {
		ep.IPv4Address = req.Interface.Address
	}

	// Store IPv6 address if provided
	if req.Interface != nil && req.Interface.AddressIPv6 != "" {
		ep.IPv6Address = req.Interface.AddressIPv6
	}

	// Process endpoint options
	ep.Options = make(map[string]string)
	for key, value := range req.Options {
		strValue, ok := value.(string)
		if !ok {
			strValue = fmt.Sprintf("%v", value)
		}
		ep.Options[key] = strValue
	}

	// Store the endpoint
	d.endpoints[req.EndpointID] = ep

	// Persist to store
	storeEp := &store.EndpointInfo{
		ID:         fmt.Sprintf("%s:%s", req.NetworkID, req.EndpointID),
		NetworkID:  req.NetworkID,
		EndpointID: req.EndpointID,
		VethName:   ep.VethName,
		IPAddress:  ep.IPv4Address,
		MACAddress: ep.MacAddress,
		Gateway:    "", // Will be set later if needed
		OVNPort:    ep.Options["ovn_port"],
	}

	if err := d.store.SaveEndpoint(storeEp); err != nil {
		d.logger.WithError(err).Warn("Failed to persist endpoint to store")
		// Non-fatal: continue even if we can't persist
	}

	d.logger.Infof("Endpoint %s created for network %s", req.EndpointID, req.NetworkID)

	resp := &dnetwork.CreateEndpointResponse{}

	// If no MAC was provided, we'll generate one when joining
	if ep.MacAddress != "" {
		resp.Interface = &dnetwork.EndpointInterface{
			MacAddress: ep.MacAddress,
		}
	}

	return resp, nil
}

// DeleteEndpoint deletes an endpoint
func (d *Driver) DeleteEndpoint(req *dnetwork.DeleteEndpointRequest) error {
	d.Lock()
	defer d.Unlock()

	d.logger.WithFields(logrus.Fields{
		"network_id":  req.NetworkID,
		"endpoint_id": req.EndpointID,
	}).Info("DeleteEndpoint called")

	ep, exists := d.endpoints[req.EndpointID]
	if !exists {
		d.logger.Warnf("Endpoint %s not found", req.EndpointID)
		return nil // Idempotent
	}

	// Clean up OVN logical port if it exists
	if ep.Options != nil && ep.Options["ovn_port"] != "" && d.ovn != nil {
		logicalPort := ep.Options["ovn_port"]
		if err := d.ovn.DeleteLogicalPort(logicalPort); err != nil {
			d.logger.WithError(err).Warnf("Failed to delete OVN logical port %s", logicalPort)
		} else {
			d.logger.Infof("Deleted OVN logical port %s", logicalPort)
		}
	}

	// Clean up OVS port if it exists
	if ep.PortName != "" {
		if err := d.ovs.DeletePort(ep.Network.Bridge, ep.PortName); err != nil {
			d.logger.WithError(err).Warnf("Failed to delete OVS port %s", ep.PortName)
			// Continue anyway - port might already be gone
		}
	}

	delete(d.endpoints, req.EndpointID)

	// Remove from store
	if err := d.store.DeleteEndpoint(req.NetworkID, req.EndpointID); err != nil {
		d.logger.WithError(err).Warn("Failed to remove endpoint from store")
		// Non-fatal: continue even if we can't remove from store
	}

	d.logger.Infof("Endpoint %s deleted", req.EndpointID)
	return nil
}

// EndpointInfo returns endpoint information
func (d *Driver) EndpointInfo(req *dnetwork.InfoRequest) (*dnetwork.InfoResponse, error) {
	d.RLock()
	defer d.RUnlock()

	d.logger.WithFields(logrus.Fields{
		"network_id":  req.NetworkID,
		"endpoint_id": req.EndpointID,
	}).Debug("EndpointInfo called")

	ep, exists := d.endpoints[req.EndpointID]
	if !exists {
		return nil, fmt.Errorf("endpoint %s not found", req.EndpointID)
	}

	res := &dnetwork.InfoResponse{
		Value: make(map[string]string),
	}

	// Add endpoint information
	if ep.MacAddress != "" {
		res.Value["mac_address"] = ep.MacAddress
	}
	if ep.IPv4Address != "" {
		res.Value["ipv4_address"] = ep.IPv4Address
	}
	if ep.IPv6Address != "" {
		res.Value["ipv6_address"] = ep.IPv6Address
	}
	if ep.PortName != "" {
		res.Value["ovs_port"] = ep.PortName
	}

	return res, nil
}

// Join joins an endpoint - this is where the actual network connection happens
func (d *Driver) Join(req *dnetwork.JoinRequest) (*dnetwork.JoinResponse, error) {
	d.Lock()
	defer d.Unlock()

	d.logger.WithFields(logrus.Fields{
		"network_id":  req.NetworkID,
		"endpoint_id": req.EndpointID,
		"sandbox_key": req.SandboxKey,
		"options":     req.Options,
	}).Info("Join called")

	ep, exists := d.endpoints[req.EndpointID]
	if !exists {
		return nil, fmt.Errorf("endpoint %s not found", req.EndpointID)
	}

	// Generate veth pair names
	vethName := fmt.Sprintf("veth%s", req.EndpointID[:7])
	vethPeer := fmt.Sprintf("veth%s-p", req.EndpointID[:7])

	// Create the veth pair and connect to OVS
	if err := d.ovs.CreateVethPair(vethName, vethPeer); err != nil {
		return nil, fmt.Errorf("failed to create veth pair: %w", err)
	}

	// Add the peer to the OVS bridge
	portOptions := make(map[string]string)

	// Set external_ids
	portOptions["external_ids:container_id"] = req.EndpointID
	portOptions["external_ids:network_id"] = req.NetworkID

	if ep.Network.TenantID != "" {
		portOptions["external_ids:tenant_id"] = ep.Network.TenantID
	}

	// If using OVN, set iface-id to bind this port to the logical port
	if ep.Network.OVNSwitch != "" {
		// The iface-id must match the OVN logical port name
		logicalPortName := fmt.Sprintf("lsp-%s", req.EndpointID[:12])
		portOptions["external_ids:iface-id"] = logicalPortName
		d.logger.Infof("Setting iface-id for OVN binding: %s", logicalPortName)
	}

	// Set VLAN if specified
	if ep.Network.VLAN != "" {
		portOptions["tag"] = ep.Network.VLAN
	}

	// Add port to OVS bridge
	if err := d.ovs.AddPort(ep.Network.Bridge, vethPeer, portOptions); err != nil {
		// Clean up veth pair
		d.ovs.DeleteVethPair(vethName, vethPeer)
		return nil, fmt.Errorf("failed to add port to OVS: %w", err)
	}

	// Store the port name for cleanup
	ep.PortName = vethPeer
	ep.VethName = vethName

	// Now create OVN logical port with the ACTUAL MAC address of the interface
	if ep.Network.OVNSwitch != "" && d.ovn != nil {
		// Get the actual MAC address of the veth interface
		link, err := netlink.LinkByName(vethName)
		if err != nil {
			// Clean up what we created
			d.ovs.DeletePort(ep.Network.Bridge, vethPeer)
			d.ovs.DeleteVethPair(vethName, vethPeer)
			return nil, fmt.Errorf("failed to get veth link info for OVN: %w", err)
		}

		actualMAC := link.Attrs().HardwareAddr.String()
		d.logger.Infof("Actual veth MAC address: %s", actualMAC)

		// Create logical port name (use endpoint ID for uniqueness)
		logicalPort := fmt.Sprintf("lsp-%s", req.EndpointID[:12])

		// Use the actual MAC and the IP address
		ip := ep.IPv4Address

		// Create OVN logical port with the real MAC
		ovnOptions := make(map[string]string)
		ovnOptions["endpoint_id"] = req.EndpointID
		ovnOptions["network_id"] = req.NetworkID
		if ep.Network.TenantID != "" {
			ovnOptions["tenant_id"] = ep.Network.TenantID
		}

		if err := d.ovn.CreateLogicalPort(ep.Network.OVNSwitch, logicalPort, actualMAC, ip, ovnOptions); err != nil {
			// This is FATAL - networking will not work without the OVN port
			// Clean up everything we created
			d.ovs.DeletePort(ep.Network.Bridge, vethPeer)
			d.ovs.DeleteVethPair(vethName, vethPeer)
			return nil, fmt.Errorf("FATAL: failed to create OVN logical port %s: %w", logicalPort, err)
		}

		// Special handling for NAT gateway - disable port security
		if ep.Network.Options["ovn.role"] == "transit" && ep.Network.Options["ovn.external_gateway"] != "" {
			// Check if this is the NAT gateway joining (has the external gateway IP)
			if ip == ep.Network.Options["ovn.external_gateway"] {
				d.logger.Infof("NAT gateway detected at %s, disabling port security", ip)
				if err := d.ovn.DisablePortSecurity(logicalPort); err != nil {
					// Port security disable failure is critical for NAT gateway
					d.ovs.DeletePort(ep.Network.Bridge, vethPeer)
					d.ovs.DeleteVethPair(vethName, vethPeer)
					d.ovn.DeleteLogicalPort(logicalPort)
					return nil, fmt.Errorf("FATAL: failed to disable port security for NAT gateway: %w", err)
				}
			}
		}

		// Port binding happens automatically via ovn-controller on the chassis
		chassis := getChassisID()
		if chassis != "" {
			d.logger.Infof("Port %s will be bound by ovn-controller on chassis %s", logicalPort, chassis)
		}

		// Enable DHCP if configured
		if dhcpUUID := ep.Network.Options["dhcp_uuid"]; dhcpUUID != "" {
			if err := d.ovn.SetPortDHCP(logicalPort, dhcpUUID); err != nil {
				// DHCP failure is also critical if it was requested
				d.ovs.DeletePort(ep.Network.Bridge, vethPeer)
				d.ovs.DeleteVethPair(vethName, vethPeer)
				d.ovn.DeleteLogicalPort(logicalPort)
				return nil, fmt.Errorf("FATAL: failed to set OVN DHCP for port %s: %w", logicalPort, err)
			}
		}

		// Store logical port name for cleanup
		ep.Options["ovn_port"] = logicalPort
		d.logger.Infof("Created OVN logical port %s with MAC %s", logicalPort, actualMAC)
	}

	// Set up port mirroring if configured
	if ep.Network.MirrorPorts != "" && ep.Network.MirrorDest != "" {
		// Check if this port should be mirrored
		mirrorPorts := strings.Split(ep.Network.MirrorPorts, ",")
		for _, mp := range mirrorPorts {
			mp = strings.TrimSpace(mp)
			if mp == vethPeer || mp == "all" {
				// Create a mirror for this port
				mirrorName := fmt.Sprintf("mirror-%s", req.EndpointID[:7])
				if err := d.ovs.CreateMirror(ep.Network.Bridge, mirrorName, vethPeer, ep.Network.MirrorDest, nil); err != nil {
					d.logger.WithError(err).Warnf("Failed to set up port mirror")
					// Continue anyway - mirroring is not critical
				} else {
					d.logger.Infof("Port mirroring enabled for %s -> %s", vethPeer, ep.Network.MirrorDest)
				}
				break
			}
		}
	}

	// Build the response
	resp := &dnetwork.JoinResponse{
		InterfaceName: dnetwork.InterfaceName{
			SrcName:   vethName,
			DstPrefix: "eth",
		},
	}

	// Set gateway if we have IPv4 data
	if ep.Network.IPv4Data != nil && ep.Network.IPv4Data.Gateway != "" {
		// Strip CIDR notation if present (Docker expects just the IP)
		gateway := ep.Network.IPv4Data.Gateway
		if idx := strings.Index(gateway, "/"); idx != -1 {
			gateway = gateway[:idx]
		}
		resp.Gateway = gateway
	}

	// Set IPv6 gateway if we have IPv6 data
	if ep.Network.IPv6Data != nil && ep.Network.IPv6Data.Gateway != "" {
		// Strip CIDR notation if present
		gateway := ep.Network.IPv6Data.Gateway
		if idx := strings.Index(gateway, "/"); idx != -1 {
			gateway = gateway[:idx]
		}
		resp.GatewayIPv6 = gateway
	}

	// Disable Docker's gateway service if we're using external DHCP
	if ep.Network.Options["ipam"] == "external" || ep.Network.Options["dhcp"] == "true" {
		resp.DisableGatewayService = true
	}

	d.logger.Infof("Container joined network %s via %s", req.NetworkID, vethName)
	return resp, nil
}

// Leave leaves an endpoint
func (d *Driver) Leave(req *dnetwork.LeaveRequest) error {
	d.Lock()
	defer d.Unlock()

	d.logger.WithFields(logrus.Fields{
		"network_id":  req.NetworkID,
		"endpoint_id": req.EndpointID,
	}).Info("Leave called")

	ep, exists := d.endpoints[req.EndpointID]
	if !exists {
		d.logger.Warnf("Endpoint %s not found", req.EndpointID)
		return nil // Idempotent
	}

	// Remove OVN logical port if it exists
	if ovnPort := ep.Options["ovn_port"]; ovnPort != "" && d.ovn != nil {
		if err := d.ovn.DeleteLogicalPort(ovnPort); err != nil {
			d.logger.WithError(err).Warnf("Failed to delete OVN logical port %s", ovnPort)
		} else {
			d.logger.Infof("Deleted OVN logical port %s", ovnPort)
		}
	}

	// Remove the OVS port
	if ep.PortName != "" {
		if err := d.ovs.DeletePort(ep.Network.Bridge, ep.PortName); err != nil {
			d.logger.WithError(err).Warnf("Failed to delete OVS port %s", ep.PortName)
		}
	}

	// Delete the veth pair
	if ep.VethName != "" {
		if err := d.ovs.DeleteVethPair(ep.VethName, ep.PortName); err != nil {
			d.logger.WithError(err).Warnf("Failed to delete veth pair %s", ep.VethName)
		}
	}

	// Clear the port information but keep the endpoint record
	ep.PortName = ""
	ep.VethName = ""

	d.logger.Infof("Container left network %s", req.NetworkID)
	return nil
}

// DiscoverNew handles discovery notifications
func (d *Driver) DiscoverNew(req *dnetwork.DiscoveryNotification) error {
	d.logger.WithField("type", req.DiscoveryType).Debug("DiscoverNew called")
	return nil
}

// DiscoverDelete handles discovery delete notifications
func (d *Driver) DiscoverDelete(req *dnetwork.DiscoveryNotification) error {
	d.logger.WithField("type", req.DiscoveryType).Debug("DiscoverDelete called")
	return nil
}

// ProgramExternalConnectivity programs external connectivity
func (d *Driver) ProgramExternalConnectivity(req *dnetwork.ProgramExternalConnectivityRequest) error {
	d.logger.WithFields(logrus.Fields{
		"network_id":  req.NetworkID,
		"endpoint_id": req.EndpointID,
		"options":     req.Options,
	}).Debug("ProgramExternalConnectivity called")
	// External connectivity will be handled by OVS/OVN
	return nil
}

// RevokeExternalConnectivity revokes external connectivity
func (d *Driver) RevokeExternalConnectivity(req *dnetwork.RevokeExternalConnectivityRequest) error {
	d.logger.WithFields(logrus.Fields{
		"network_id":  req.NetworkID,
		"endpoint_id": req.EndpointID,
	}).Debug("RevokeExternalConnectivity called")
	return nil
}

// generateMAC generates a random MAC address
func generateMAC() string {
	mac := make([]byte, 6)
	rand.Read(mac)
	// Set local bit and unset multicast bit
	mac[0] = (mac[0] | 0x02) & 0xfe
	return fmt.Sprintf("%02x:%02x:%02x:%02x:%02x:%02x",
		mac[0], mac[1], mac[2], mac[3], mac[4], mac[5])
}

// getChassisID gets the OVN chassis ID for this host
func getChassisID() string {
	// Try to get from environment first
	if chassis := os.Getenv("OVN_CHASSIS_ID"); chassis != "" {
		return chassis
	}

	// Try to get from OVS database
	cmd := exec.Command("ovs-vsctl", "get", "open_vswitch", ".", "external_ids:system-id")
	output, err := cmd.Output()
	if err != nil {
		// Try hostname as fallback
		hostname, _ := os.Hostname()
		return hostname
	}

	chassis := strings.TrimSpace(string(output))
	chassis = strings.Trim(chassis, "\"")
	return chassis
}

// createTransitNetwork creates a transit network with gateway router
func (d *Driver) createTransitNetwork(req *dnetwork.CreateNetworkRequest, netConfig *types.Network) error {
	d.logger.Infof("Creating transit network %s", req.NetworkID)

	// Ensure OVN client is initialized
	nbConn := netConfig.Options["ovn.nb_connection"]
	sbConn := netConfig.Options["ovn.sb_connection"]

	if nbConn == "" || sbConn == "" {
		return fmt.Errorf("transit network requires ovn.nb_connection and ovn.sb_connection")
	}

	// Check if auto-create is enabled
	autoCreate := netConfig.Options["ovn.auto_create"] == "true"
	transitNetwork := netConfig.Options["ovn.transit_overlay_network"] // optional custom network

	// Ensure OVN central is running (create if needed and enabled)
	if err := d.ensureOVNCentral(nbConn, sbConn, autoCreate, transitNetwork); err != nil {
		return fmt.Errorf("failed to ensure OVN central: %w", err)
	}

	if d.ovn == nil {
		ovnClient, err := ovn.NewClient(nbConn, sbConn)
		if err != nil {
			return fmt.Errorf("failed to connect to OVN: %w", err)
		}
		d.ovn = ovnClient
	}

	// Use network name as switch name if not specified
	switchName := netConfig.OVNSwitch
	if switchName == "" {
		switchName = fmt.Sprintf("ls-transit-%s", req.NetworkID[:12])
		netConfig.OVNSwitch = switchName
	}

	// Create the transit logical switch
	ovnOptions := map[string]string{
		"network_id": req.NetworkID,
		"role":       "transit",
	}
	if err := d.ovn.CreateLogicalSwitch(switchName, ovnOptions); err != nil {
		return fmt.Errorf("failed to create transit switch: %w", err)
	}

	// Create gateway router
	gatewayRouter := "lr-gateway"
	routerOpts := map[string]string{
		"role": "gateway",
	}
	if err := d.ovn.CreateLogicalRouter(gatewayRouter, routerOpts); err != nil {
		return fmt.Errorf("failed to create gateway router: %w", err)
	}

	// Connect gateway router to transit network
	if netConfig.IPv4Data != nil {
		// Use .1 address for gateway router on transit network
		gwIP := netConfig.IPv4Data.Gateway
		if gwIP == "" && netConfig.IPv4Data.Pool != "" {
			// Extract gateway IP from pool (first IP in subnet)
			// Parse subnet and use .1 address
			gwIP = strings.Split(netConfig.IPv4Data.Pool, "/")[0]
			parts := strings.Split(gwIP, ".")
			if len(parts) == 4 {
				parts[3] = "1"
				gwIP = strings.Join(parts, ".") + "/" + strings.Split(netConfig.IPv4Data.Pool, "/")[1]
			}
		}

		routerPort := fmt.Sprintf("rp-%s-%s", gatewayRouter, switchName)
		routerMAC := "02:00:00:00:00:01"

		if err := d.ovn.CreateLogicalRouterPort(
			gatewayRouter,
			routerPort,
			routerMAC,
			[]string{gwIP},
		); err != nil {
			return fmt.Errorf("failed to create gateway router port: %w", err)
		}

		// Create switch port for router connection
		switchPort := fmt.Sprintf("sp-%s-%s", switchName, gatewayRouter)
		switchPortOpts := map[string]string{
			"type":        "router",
			"router-port": routerPort,
		}

		if err := d.ovn.CreateLogicalPort(
			switchName,
			switchPort,
			"", "", // No MAC/IP for router ports
			switchPortOpts,
		); err != nil {
			return fmt.Errorf("failed to create switch port for gateway router: %w", err)
		}
	}

	// Add external gateway route if specified
	if extGW := netConfig.Options["ovn.external_gateway"]; extGW != "" {
		d.logger.Infof("Adding default route to external gateway %s", extGW)
		if err := d.ovn.AddStaticRoute(gatewayRouter, "0.0.0.0/0", extGW); err != nil {
			// Check if error is about duplicate route
			if !strings.Contains(err.Error(), "duplicate prefix") {
				return fmt.Errorf("failed to add default route: %w", err)
			}
			d.logger.Infof("Default route already exists on gateway router")
		}
		// Don't pre-create the gateway port - it will be created when the NAT gateway container joins
		// Store the gateway IP so we can identify it later
		netConfig.Options["external_gateway_ip"] = strings.Split(extGW, "/")[0]
	}

	// Store the network configuration
	d.networks[req.NetworkID] = netConfig

	d.logger.Infof("Transit network %s created successfully", req.NetworkID)
	return nil
}

// connectToTransitNetwork connects a VPC router to the transit network
func (d *Driver) connectToTransitNetwork(vpcRouter, transitNetName string) error {
	// Look up the transit network configuration
	var transitNet *types.Network
	for _, net := range d.networks {
		if net.Options["ovn.role"] == "transit" {
			transitNet = net
			break
		}
	}

	if transitNet == nil {
		return fmt.Errorf("transit network %s not found", transitNetName)
	}

	// Determine the next available IP on the transit network
	// In production, this would need proper IPAM
	// For now, use a simple scheme: .10 for vpc-a, .20 for vpc-b, etc.
	var transitIP string
	if strings.Contains(vpcRouter, "vpc-a") {
		transitIP = "192.168.100.10/24"
	} else if strings.Contains(vpcRouter, "vpc-b") {
		transitIP = "192.168.100.20/24"
	} else {
		// Generate based on hash or sequence
		transitIP = "192.168.100.100/24"
	}

	// Create router port on transit network
	routerPort := fmt.Sprintf("rp-%s-transit", vpcRouter)
	routerMAC := "02:00:00:00:00:10" // Should be unique per router

	if err := d.ovn.CreateLogicalRouterPort(
		vpcRouter,
		routerPort,
		routerMAC,
		[]string{transitIP},
	); err != nil {
		return fmt.Errorf("failed to create router port on transit: %w", err)
	}

	// Create switch port on transit network
	switchPort := fmt.Sprintf("sp-transit-%s", vpcRouter)
	switchPortOpts := map[string]string{
		"type":        "router",
		"router-port": routerPort,
	}

	if err := d.ovn.CreateLogicalPort(
		transitNet.OVNSwitch,
		switchPort,
		"", "", // No MAC/IP for router ports
		switchPortOpts,
	); err != nil {
		return fmt.Errorf("failed to create switch port on transit: %w", err)
	}

	// Add routes for inter-VPC and external connectivity
	// Add default route via gateway router
	if err := d.ovn.AddStaticRoute(vpcRouter, "0.0.0.0/0", "192.168.100.1"); err != nil {
		// Check if error is about duplicate route (multiple networks on same VPC router)
		if !strings.Contains(err.Error(), "duplicate prefix") {
			return fmt.Errorf("failed to add default route: %w", err)
		}
		d.logger.Infof("Default route already exists on router %s", vpcRouter)
	}

	// Add routes on gateway router for this VPC's subnet
	// This would need to be determined from the VPC's networks
	// For now, use a simple mapping
	var vpcSubnet string
	if strings.Contains(vpcRouter, "vpc-a") {
		vpcSubnet = "10.0.0.0/16"
	} else if strings.Contains(vpcRouter, "vpc-b") {
		vpcSubnet = "10.1.0.0/16"
	}

	if vpcSubnet != "" {
		if err := d.ovn.AddStaticRoute("lr-gateway", vpcSubnet, strings.Split(transitIP, "/")[0]); err != nil {
			// Check if error is about duplicate route (multiple networks from same VPC)
			if !strings.Contains(err.Error(), "duplicate prefix") {
				return fmt.Errorf("failed to add route for VPC subnet: %w", err)
			}
			d.logger.Infof("Route for VPC subnet %s already exists on gateway router", vpcSubnet)
		}
	}

	d.logger.Infof("Connected router %s to transit network", vpcRouter)
	return nil
}
