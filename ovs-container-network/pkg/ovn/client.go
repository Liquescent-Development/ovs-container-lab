package ovn

import (
	"bytes"
	"context"
	"fmt"
	"os/exec"
	"strings"
	"time"

	"github.com/sirupsen/logrus"
)

// Client provides an interface to OVN (Open Virtual Network) using ovn-nbctl
type Client struct {
	logger       *logrus.Logger
	nbConnection string // TCP address for OVN Northbound DB
	sbConnection string // TCP address for OVN Southbound DB
}

// NewClient creates a new OVN client using ovn-nbctl commands
func NewClient(nbConn, sbConn string) (*Client, error) {
	logger := logrus.New()
	logger.SetLevel(logrus.GetLevel())

	// Default connections if not specified
	if nbConn == "" {
		nbConn = "tcp:127.0.0.1:6641"
	}
	if sbConn == "" {
		sbConn = "tcp:127.0.0.1:6642"
	}

	c := &Client{
		logger:       logger,
		nbConnection: nbConn,
		sbConnection: sbConn,
	}

	// Test connection by running a simple command
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()

	cmd := exec.CommandContext(ctx, "ovn-nbctl", "--db="+nbConn, "ls-list")
	if err := cmd.Run(); err != nil {
		return nil, fmt.Errorf("failed to connect to OVN northbound at %s: %w", nbConn, err)
	}

	c.logger.Infof("Connected to OVN northbound at %s", nbConn)
	return c, nil
}

// execNBCtl executes an ovn-nbctl command with the remote connection
func (c *Client) execNBCtl(args ...string) (string, error) {
	// Prepend the database connection
	cmdArgs := append([]string{"--db=" + c.nbConnection}, args...)

	cmd := exec.Command("ovn-nbctl", cmdArgs...)
	var stdout, stderr bytes.Buffer
	cmd.Stdout = &stdout
	cmd.Stderr = &stderr

	c.logger.Debugf("Executing: ovn-nbctl %s", strings.Join(cmdArgs, " "))

	if err := cmd.Run(); err != nil {
		return "", fmt.Errorf("ovn-nbctl failed: %w, stderr: %s", err, stderr.String())
	}

	return strings.TrimSpace(stdout.String()), nil
}

// Connect establishes connection to OVN (compatibility method, connection is tested in NewClient)
func (c *Client) Connect(ctx context.Context) error {
	// Connection is already established and tested in NewClient
	return nil
}

// Disconnect closes the connection to OVN (compatibility method, no persistent connection with exec)
func (c *Client) Disconnect() {
	// No persistent connection to close when using exec
	c.logger.Info("Disconnected from OVN")
}

// CreateLogicalSwitch creates a logical switch in OVN
func (c *Client) CreateLogicalSwitch(name string, externalIDs map[string]string) error {
	// Check if switch already exists
	output, err := c.execNBCtl("ls-list")
	if err != nil {
		return fmt.Errorf("failed to list switches: %w", err)
	}

	if strings.Contains(output, name) {
		c.logger.Infof("Logical switch %s already exists", name)
		return nil
	}

	// Create the switch
	if _, err := c.execNBCtl("ls-add", name); err != nil {
		return fmt.Errorf("failed to create logical switch %s: %w", name, err)
	}

	// Set external IDs if provided
	for key, value := range externalIDs {
		if _, err := c.execNBCtl("set", "Logical_Switch", name,
			fmt.Sprintf("external_ids:%s=%s", key, value)); err != nil {
			c.logger.WithError(err).Warnf("Failed to set external_id %s=%s on switch %s", key, value, name)
		}
	}

	c.logger.Infof("Created logical switch %s", name)
	return nil
}

// DeleteLogicalSwitch deletes a logical switch
func (c *Client) DeleteLogicalSwitch(name string) error {
	if _, err := c.execNBCtl("ls-del", name); err != nil {
		// If the switch doesn't exist, that's okay
		if strings.Contains(err.Error(), "no row") {
			c.logger.Infof("Logical switch %s doesn't exist", name)
			return nil
		}
		return fmt.Errorf("failed to delete logical switch %s: %w", name, err)
	}

	c.logger.Infof("Deleted logical switch %s", name)
	return nil
}

// CreateLogicalPort creates a logical switch port
func (c *Client) CreateLogicalPort(lswitch, portName, macAddress, ipAddress string, options map[string]string) error {
	// Create the port
	if _, err := c.execNBCtl("lsp-add", lswitch, portName); err != nil {
		// If port already exists, update it
		if !strings.Contains(err.Error(), "already exists") {
			return fmt.Errorf("failed to create logical port %s: %w", portName, err)
		}
		c.logger.Infof("Logical port %s already exists, updating", portName)
	}

	// Check if this is a router-type port
	isRouterPort := false
	if portType, ok := options["type"]; ok && portType == "router" {
		isRouterPort = true
	}

	// Set addresses if provided (skip for router ports, they use "router" keyword)
	if !isRouterPort && macAddress != "" && ipAddress != "" {
		address := fmt.Sprintf("%s %s", macAddress, ipAddress)
		if _, err := c.execNBCtl("lsp-set-addresses", portName, address); err != nil {
			return fmt.Errorf("failed to set addresses on port %s: %w", portName, err)
		}

		// Also set port security to match addresses
		if _, err := c.execNBCtl("lsp-set-port-security", portName, address); err != nil {
			c.logger.WithError(err).Warnf("Failed to set port security on %s", portName)
		}
	}

	// Set options on the port
	for key, value := range options {
		if key == "type" && value == "router" {
			// Set port type to router
			if _, err := c.execNBCtl("lsp-set-type", portName, "router"); err != nil {
				return fmt.Errorf("failed to set port type to router: %w", err)
			}
			// Router ports use the special "router" keyword for addresses
			if _, err := c.execNBCtl("lsp-set-addresses", portName, "router"); err != nil {
				c.logger.WithError(err).Warnf("Failed to set router addresses on port %s", portName)
			}
		} else if key == "router-port" {
			// Link to router port
			if _, err := c.execNBCtl("lsp-set-options", portName, fmt.Sprintf("router-port=%s", value)); err != nil {
				return fmt.Errorf("failed to set router-port option: %w", err)
			}
		} else if key == "addresses" {
			// Already handled above, skip
			continue
		} else if strings.HasPrefix(key, "external_ids:") {
			idKey := strings.TrimPrefix(key, "external_ids:")
			if _, err := c.execNBCtl("set", "Logical_Switch_Port", portName,
				fmt.Sprintf("external_ids:%s=%s", idKey, value)); err != nil {
				c.logger.WithError(err).Warnf("Failed to set external_id %s=%s on port %s", idKey, value, portName)
			}
		}
	}

	c.logger.Infof("Created logical port %s on switch %s", portName, lswitch)
	return nil
}

// DeleteLogicalPort deletes a logical switch port
func (c *Client) DeleteLogicalPort(portName string) error {
	if _, err := c.execNBCtl("lsp-del", portName); err != nil {
		// If the port doesn't exist, that's okay
		if strings.Contains(err.Error(), "no row") {
			c.logger.Infof("Logical port %s doesn't exist", portName)
			return nil
		}
		return fmt.Errorf("failed to delete logical port %s: %w", portName, err)
	}

	c.logger.Infof("Deleted logical port %s", portName)
	return nil
}

// GetLogicalSwitch retrieves information about a logical switch
func (c *Client) GetLogicalSwitch(name string) (map[string]interface{}, error) {
	// Get switch details
	output, err := c.execNBCtl("--format=csv", "--data=bare", "--columns=_uuid,name,ports",
		"list", "Logical_Switch", name)
	if err != nil {
		return nil, fmt.Errorf("failed to get logical switch %s: %w", name, err)
	}

	if output == "" {
		return nil, fmt.Errorf("logical switch %s not found", name)
	}

	// Parse the CSV output
	fields := strings.Split(output, ",")
	if len(fields) < 2 {
		return nil, fmt.Errorf("unexpected output format")
	}

	result := map[string]interface{}{
		"uuid": fields[0],
		"name": fields[1],
	}

	if len(fields) > 2 {
		result["ports"] = fields[2]
	}

	return result, nil
}

// ListLogicalSwitches lists all logical switches
func (c *Client) ListLogicalSwitches() ([]string, error) {
	output, err := c.execNBCtl("ls-list")
	if err != nil {
		return nil, fmt.Errorf("failed to list logical switches: %w", err)
	}

	if output == "" {
		return []string{}, nil
	}

	// Parse the output - each line contains UUID and name
	var switches []string
	for _, line := range strings.Split(output, "\n") {
		if line == "" {
			continue
		}
		// Line format: "uuid (name)"
		if idx := strings.Index(line, "("); idx > 0 {
			name := strings.TrimSuffix(strings.TrimPrefix(line[idx:], "("), ")")
			switches = append(switches, name)
		}
	}

	return switches, nil
}

// CreateLogicalRouter creates a logical router
func (c *Client) CreateLogicalRouter(name string, externalIDs map[string]string) error {
	// Check if router already exists
	output, err := c.execNBCtl("lr-list")
	if err != nil {
		return fmt.Errorf("failed to list routers: %w", err)
	}

	if strings.Contains(output, name) {
		c.logger.Infof("Logical router %s already exists", name)
		return nil
	}

	// Create the router
	if _, err := c.execNBCtl("lr-add", name); err != nil {
		return fmt.Errorf("failed to create logical router %s: %w", name, err)
	}

	// Set external IDs if provided
	for key, value := range externalIDs {
		if _, err := c.execNBCtl("set", "Logical_Router", name,
			fmt.Sprintf("external_ids:%s=%s", key, value)); err != nil {
			c.logger.WithError(err).Warnf("Failed to set external_id %s=%s on router %s", key, value, name)
		}
	}

	c.logger.Infof("Created logical router %s", name)
	return nil
}

// DeleteLogicalRouter deletes a logical router
func (c *Client) DeleteLogicalRouter(name string) error {
	if _, err := c.execNBCtl("lr-del", name); err != nil {
		// If the router doesn't exist, that's okay
		if strings.Contains(err.Error(), "no row") {
			c.logger.Infof("Logical router %s doesn't exist", name)
			return nil
		}
		return fmt.Errorf("failed to delete logical router %s: %w", name, err)
	}

	c.logger.Infof("Deleted logical router %s", name)
	return nil
}

// CreateLogicalRouterPort creates a logical router port
func (c *Client) CreateLogicalRouterPort(router, portName, mac string, networks []string) error {
	// Create the router port
	networkStr := strings.Join(networks, " ")
	if _, err := c.execNBCtl("lrp-add", router, portName, mac, networkStr); err != nil {
		// If port already exists, that might be okay
		if !strings.Contains(err.Error(), "already exists") {
			return fmt.Errorf("failed to create logical router port %s: %w", portName, err)
		}
		c.logger.Infof("Logical router port %s already exists", portName)
	}

	c.logger.Infof("Created logical router port %s on router %s", portName, router)
	return nil
}

// DeleteLogicalRouterPort deletes a logical router port
func (c *Client) DeleteLogicalRouterPort(portName string) error {
	if _, err := c.execNBCtl("lrp-del", portName); err != nil {
		// If the port doesn't exist, that's okay
		if strings.Contains(err.Error(), "no row") {
			c.logger.Infof("Logical router port %s doesn't exist", portName)
			return nil
		}
		return fmt.Errorf("failed to delete logical router port %s: %w", portName, err)
	}

	c.logger.Infof("Deleted logical router port %s", portName)
	return nil
}

// AddStaticRoute adds a static route to a logical router
func (c *Client) AddStaticRoute(router, prefix, nexthop string) error {
	if _, err := c.execNBCtl("lr-route-add", router, prefix, nexthop); err != nil {
		// If route already exists, that might be okay
		// OVN can report this as either "already exists" or "duplicate prefix"
		if !strings.Contains(err.Error(), "already exists") && !strings.Contains(err.Error(), "duplicate prefix") {
			return fmt.Errorf("failed to add static route: %w", err)
		}
		c.logger.Infof("Static route %s via %s already exists on router %s", prefix, nexthop, router)
	}

	c.logger.Infof("Added static route %s via %s to router %s", prefix, nexthop, router)
	return nil
}

// DeleteStaticRoute removes a static route from a logical router
func (c *Client) DeleteStaticRoute(router, prefix string) error {
	if _, err := c.execNBCtl("lr-route-del", router, prefix); err != nil {
		// If route doesn't exist, that's okay
		if strings.Contains(err.Error(), "no row") {
			c.logger.Infof("Static route %s doesn't exist on router %s", prefix, router)
			return nil
		}
		return fmt.Errorf("failed to delete static route: %w", err)
	}

	c.logger.Infof("Deleted static route %s from router %s", prefix, router)
	return nil
}

// CreateDHCPOptions creates DHCP options for a subnet
func (c *Client) CreateDHCPOptions(cidr, serverMAC, serverIP string, options map[string]string) (string, error) {
	// Create DHCP options
	args := []string{"dhcp-options-create", cidr}

	output, err := c.execNBCtl(args...)
	if err != nil {
		return "", fmt.Errorf("failed to create DHCP options: %w", err)
	}

	// Output contains the UUID of the created DHCP options
	dhcpUUID := strings.TrimSpace(output)

	// Set DHCP options
	setArgs := []string{"dhcp-options-set-options", dhcpUUID,
		fmt.Sprintf("server_id=%s", serverIP),
		fmt.Sprintf("server_mac=%s", serverMAC),
		fmt.Sprintf("lease_time=%s", options["lease_time"]),
	}

	if router, ok := options["router"]; ok {
		setArgs = append(setArgs, fmt.Sprintf("router=%s", router))
	}

	if dns, ok := options["dns_server"]; ok {
		setArgs = append(setArgs, fmt.Sprintf("dns_server=%s", dns))
	}

	if _, err := c.execNBCtl(setArgs...); err != nil {
		// Try to clean up the created DHCP options
		c.execNBCtl("dhcp-options-del", dhcpUUID)
		return "", fmt.Errorf("failed to set DHCP options: %w", err)
	}

	c.logger.Infof("Created DHCP options for %s with UUID %s", cidr, dhcpUUID)
	return dhcpUUID, nil
}

// SetPortDHCP configures a port to use DHCP options
func (c *Client) SetPortDHCP(portName, dhcpOptionsUUID string) error {
	// Set DHCP options UUID on the port
	if _, err := c.execNBCtl("lsp-set-dhcpv4-options", portName, dhcpOptionsUUID); err != nil {
		return fmt.Errorf("failed to set DHCP options on port %s: %w", portName, err)
	}

	c.logger.Infof("Set DHCP options %s on port %s", dhcpOptionsUUID, portName)
	return nil
}

// DisablePortSecurity disables port security on a logical switch port
func (c *Client) DisablePortSecurity(portName string) error {
	// Clear port security to allow all traffic
	if _, err := c.execNBCtl("lsp-set-port-security", portName, ""); err != nil {
		return fmt.Errorf("failed to disable port security on port %s: %w", portName, err)
	}

	c.logger.Infof("Disabled port security on port %s", portName)
	return nil
}
