package ovs

import (
	"fmt"
	"os/exec"
	"strings"

	"github.com/sirupsen/logrus"
	"github.com/vishvananda/netlink"
)

// Client provides an interface to Open vSwitch
type Client struct {
	logger *logrus.Logger
}

// NewClient creates a new OVS client
func NewClient() (*Client, error) {
	logger := logrus.New()
	logger.SetLevel(logrus.GetLevel())

	return &Client{
		logger: logger,
	}, nil
}

// Ping verifies that OVS is accessible
func (c *Client) Ping() error {
	cmd := exec.Command("ovs-vsctl", "--version")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("ovs-vsctl not accessible: %w (output: %s)", err, string(output))
	}
	c.logger.Debugf("OVS version: %s", strings.TrimSpace(string(output)))
	return nil
}

// ListBridges returns a list of all OVS bridges
func (c *Client) ListBridges() ([]string, error) {
	cmd := exec.Command("ovs-vsctl", "list-br")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("failed to list bridges: %w (output: %s)", err, string(output))
	}

	bridges := []string{}
	for _, line := range strings.Split(string(output), "\n") {
		bridge := strings.TrimSpace(line)
		if bridge != "" {
			bridges = append(bridges, bridge)
		}
	}

	return bridges, nil
}

// EnsureBridge ensures that an OVS bridge exists
func (c *Client) EnsureBridge(bridge string) error {
	// Check if bridge exists
	cmd := exec.Command("ovs-vsctl", "br-exists", bridge)
	if err := cmd.Run(); err == nil {
		c.logger.Debugf("Bridge %s already exists", bridge)
		return nil
	}

	// Create the bridge
	c.logger.Infof("Creating OVS bridge %s", bridge)
	cmd = exec.Command("ovs-vsctl", "add-br", bridge)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("failed to create bridge %s: %w (output: %s)", bridge, err, string(output))
	}

	// Set bridge to secure mode
	cmd = exec.Command("ovs-vsctl", "set", "bridge", bridge, "fail-mode=secure")
	if output, err := cmd.CombinedOutput(); err != nil {
		c.logger.Warnf("Failed to set bridge %s to secure mode: %v (output: %s)", bridge, err, string(output))
	}

	return nil
}

// AddPort adds a port to an OVS bridge
func (c *Client) AddPort(bridge, port string, options map[string]string) error {
	args := []string{"add-port", bridge, port}

	// Separate options by table
	var portOptions []string
	var interfaceOptions []string

	// Add port and interface options
	for key, value := range options {
		if key == "tag" {
			// VLAN tag is set on the Port table
			portOptions = append(portOptions, "--", "set", "Port", port, "tag="+value)
		} else if strings.HasPrefix(key, "external_ids:") {
			// External IDs are set on the Interface table
			interfaceOptions = append(interfaceOptions, "--", "set", "Interface", port, key+"="+value)
		} else {
			// Other options go to Interface table
			interfaceOptions = append(interfaceOptions, "--", "set", "Interface", port, key+"="+value)
		}
	}

	// Combine all options
	args = append(args, portOptions...)
	args = append(args, interfaceOptions...)

	c.logger.Debugf("Adding port to OVS: ovs-vsctl %v", args)
	cmd := exec.Command("ovs-vsctl", args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		// Check if port already exists
		if strings.Contains(string(output), "already exists") {
			c.logger.Warnf("Port %s already exists on bridge %s", port, bridge)
			return nil
		}
		return fmt.Errorf("failed to add port %s to bridge %s: %w (output: %s)", port, bridge, err, string(output))
	}

	c.logger.Infof("Added port %s to bridge %s", port, bridge)
	return nil
}

// DeletePort removes a port from an OVS bridge
func (c *Client) DeletePort(bridge, port string) error {
	cmd := exec.Command("ovs-vsctl", "--if-exists", "del-port", bridge, port)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("failed to delete port %s from bridge %s: %w (output: %s)", port, bridge, err, string(output))
	}

	c.logger.Infof("Deleted port %s from bridge %s", port, bridge)
	return nil
}

// CreateVethPair creates a veth pair
func (c *Client) CreateVethPair(vethName, peerName string) error {
	// Check if veth already exists
	if _, err := netlink.LinkByName(vethName); err == nil {
		c.logger.Warnf("Veth %s already exists, deleting it", vethName)
		// Try to delete existing veth
		if link, err := netlink.LinkByName(vethName); err == nil {
			netlink.LinkDel(link)
		}
	}

	// Create the veth pair
	veth := &netlink.Veth{
		LinkAttrs: netlink.LinkAttrs{
			Name: vethName,
		},
		PeerName: peerName,
	}

	if err := netlink.LinkAdd(veth); err != nil {
		return fmt.Errorf("failed to create veth pair %s <-> %s: %w", vethName, peerName, err)
	}

	// Bring up both interfaces
	if link, err := netlink.LinkByName(vethName); err == nil {
		if err := netlink.LinkSetUp(link); err != nil {
			c.logger.Warnf("Failed to bring up %s: %v", vethName, err)
		}
	}

	if link, err := netlink.LinkByName(peerName); err == nil {
		if err := netlink.LinkSetUp(link); err != nil {
			c.logger.Warnf("Failed to bring up %s: %v", peerName, err)
		}
	}

	c.logger.Infof("Created veth pair %s <-> %s", vethName, peerName)
	return nil
}

// DeleteVethPair deletes a veth pair
func (c *Client) DeleteVethPair(vethName, peerName string) error {
	// Deleting one end of a veth pair deletes both
	if link, err := netlink.LinkByName(vethName); err == nil {
		if err := netlink.LinkDel(link); err != nil {
			c.logger.Warnf("Failed to delete veth %s: %v", vethName, err)
		} else {
			c.logger.Infof("Deleted veth pair %s <-> %s", vethName, peerName)
		}
	} else {
		// Try the peer name
		if link, err := netlink.LinkByName(peerName); err == nil {
			if err := netlink.LinkDel(link); err != nil {
				c.logger.Warnf("Failed to delete veth %s: %v", peerName, err)
			} else {
				c.logger.Infof("Deleted veth pair via peer %s", peerName)
			}
		}
	}

	return nil
}

// SetPortVLAN sets the VLAN tag for a port
func (c *Client) SetPortVLAN(port string, vlan int) error {
	cmd := exec.Command("ovs-vsctl", "set", "port", port, fmt.Sprintf("tag=%d", vlan))
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("failed to set VLAN %d on port %s: %w (output: %s)", vlan, port, err, string(output))
	}

	c.logger.Infof("Set VLAN %d on port %s", vlan, port)
	return nil
}

// GetPortInfo retrieves information about a port
func (c *Client) GetPortInfo(port string) (map[string]string, error) {
	info := make(map[string]string)

	// Get external_ids
	cmd := exec.Command("ovs-vsctl", "get", "interface", port, "external_ids")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("failed to get port info for %s: %w", port, err)
	}

	// Parse the output (format: {key1=value1, key2=value2})
	externalIDs := strings.TrimSpace(string(output))
	externalIDs = strings.Trim(externalIDs, "{}")
	if externalIDs != "" {
		pairs := strings.Split(externalIDs, ", ")
		for _, pair := range pairs {
			kv := strings.SplitN(pair, "=", 2)
			if len(kv) == 2 {
				key := strings.Trim(kv[0], "\"")
				value := strings.Trim(kv[1], "\"")
				info["external_id:"+key] = value
			}
		}
	}

	// Get VLAN tag if set
	cmd = exec.Command("ovs-vsctl", "get", "port", port, "tag")
	if output, err := cmd.CombinedOutput(); err == nil {
		tag := strings.TrimSpace(string(output))
		if tag != "[]" {
			info["vlan"] = tag
		}
	}

	return info, nil
}

// CreateMirror sets up port mirroring
func (c *Client) CreateMirror(bridge, mirrorName, sourcePort, outputPort string, options map[string]string) error {
	// Build the command to create a mirror
	args := []string{
		"--", "--id=@m", "create", "mirror",
		fmt.Sprintf("name=%s", mirrorName),
	}

	// Add source ports (what to mirror)
	if sourcePort != "" {
		args = append(args, fmt.Sprintf("select-src-port=@%s", sourcePort))
		args = append(args, fmt.Sprintf("select-dst-port=@%s", sourcePort))
	}

	// Add output port (where to send mirrored traffic)
	if outputPort != "" {
		args = append(args, fmt.Sprintf("output-port=@%s", outputPort))
	}

	// Add the mirror to the bridge
	args = append(args, "--", "set", "bridge", bridge, "mirrors=@m")

	// Get port references
	if sourcePort != "" {
		args = append(args, "--", fmt.Sprintf("--id=@%s", sourcePort), "get", "port", sourcePort)
	}
	if outputPort != "" {
		args = append(args, "--", fmt.Sprintf("--id=@%s", outputPort), "get", "port", outputPort)
	}

	c.logger.Debugf("Creating mirror: ovs-vsctl %v", args)
	cmd := exec.Command("ovs-vsctl", args...)
	output, err := cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("failed to create mirror %s: %w (output: %s)", mirrorName, err, string(output))
	}

	c.logger.Infof("Created mirror %s on bridge %s", mirrorName, bridge)
	return nil
}

// DeleteMirror removes a port mirror
func (c *Client) DeleteMirror(bridge, mirrorName string) error {
	// First, clear the mirror from the bridge
	cmd := exec.Command("ovs-vsctl", "remove", "bridge", bridge, "mirrors", mirrorName)
	output, err := cmd.CombinedOutput()
	if err != nil {
		c.logger.Warnf("Failed to remove mirror from bridge: %v (output: %s)", err, string(output))
	}

	// Then destroy the mirror
	cmd = exec.Command("ovs-vsctl", "--if-exists", "destroy", "mirror", mirrorName)
	output, err = cmd.CombinedOutput()
	if err != nil {
		return fmt.Errorf("failed to delete mirror %s: %w (output: %s)", mirrorName, err, string(output))
	}

	c.logger.Infof("Deleted mirror %s", mirrorName)
	return nil
}

// ListMirrors lists all mirrors on a bridge
func (c *Client) ListMirrors(bridge string) ([]string, error) {
	cmd := exec.Command("ovs-vsctl", "get", "bridge", bridge, "mirrors")
	output, err := cmd.CombinedOutput()
	if err != nil {
		return nil, fmt.Errorf("failed to list mirrors: %w", err)
	}

	// Parse output - format is like [uuid1, uuid2] or []
	result := strings.TrimSpace(string(output))
	result = strings.Trim(result, "[]")

	if result == "" {
		return []string{}, nil
	}

	// Get mirror names from UUIDs
	var mirrors []string
	uuids := strings.Split(result, ",")
	for _, uuid := range uuids {
		uuid = strings.TrimSpace(uuid)
		if uuid != "" {
			// Get mirror name from UUID
			cmd := exec.Command("ovs-vsctl", "get", "mirror", uuid, "name")
			if output, err := cmd.CombinedOutput(); err == nil {
				name := strings.TrimSpace(string(output))
				name = strings.Trim(name, "\"")
				mirrors = append(mirrors, name)
			}
		}
	}

	return mirrors, nil
}
