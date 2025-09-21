package types

import (
	"github.com/docker/go-plugins-helpers/network"
)

// Network represents a network configuration
type Network struct {
	ID          string            // Docker network ID
	Bridge      string            // OVS bridge name
	TenantID    string            // Tenant identifier
	VLAN        string            // VLAN tag
	MTU         string            // Maximum transmission unit
	OVNSwitch   string            // OVN logical switch name
	OVNRouter   string            // OVN logical router name
	MirrorPorts string            // Comma-separated list of ports to mirror
	MirrorDest  string            // Destination port for mirrored traffic
	IPv4Data    *network.IPAMData // IPv4 configuration
	IPv6Data    *network.IPAMData // IPv6 configuration
	Options     map[string]string // Additional options
}

// Endpoint represents a network endpoint (container connection)
type Endpoint struct {
	ID          string            // Docker endpoint ID
	NetworkID   string            // Associated network ID
	Network     *Network          // Network configuration
	MacAddress  string            // MAC address
	IPv4Address string            // IPv4 address with prefix
	IPv6Address string            // IPv6 address with prefix
	PortName    string            // OVS port name
	VethName    string            // Veth interface name
	Options     map[string]string // Additional options
}
