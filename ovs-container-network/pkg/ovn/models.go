package ovn

// LogicalSwitch represents an OVN Logical Switch
type LogicalSwitch struct {
	UUID        string            `ovsdb:"_uuid"`
	Name        string            `ovsdb:"name"`
	Ports       []string          `ovsdb:"ports"`
	ExternalIDs map[string]string `ovsdb:"external_ids"`
	OtherConfig map[string]string `ovsdb:"other_config"`
}

// TableName returns the OVN database table name
func (LogicalSwitch) TableName() string {
	return "Logical_Switch"
}

// LogicalSwitchPort represents an OVN Logical Switch Port
type LogicalSwitchPort struct {
	UUID             string            `ovsdb:"_uuid"`
	Name             string            `ovsdb:"name"`
	Addresses        []string          `ovsdb:"addresses"`
	PortSecurity     []string          `ovsdb:"port_security"`
	Up               *bool             `ovsdb:"up"`
	Enabled          *bool             `ovsdb:"enabled"`
	Type             string            `ovsdb:"type"`
	Options          map[string]string `ovsdb:"options"`
	ExternalIDs      map[string]string `ovsdb:"external_ids"`
	DHCPv4Options    *string           `ovsdb:"dhcpv4_options"`
	DHCPv6Options    *string           `ovsdb:"dhcpv6_options"`
	DynamicAddresses *string           `ovsdb:"dynamic_addresses"`
	ParentName       *string           `ovsdb:"parent_name"`
	Tag              *int              `ovsdb:"tag"`
	TagRequest       *int              `ovsdb:"tag_request"`
	HaChassisGroup   *string           `ovsdb:"ha_chassis_group"`
	MirrorRules      []string          `ovsdb:"mirror_rules"`
}

// TableName returns the OVN database table name
func (LogicalSwitchPort) TableName() string {
	return "Logical_Switch_Port"
}

// DHCPOptions represents OVN DHCP Options
type DHCPOptions struct {
	UUID        string            `ovsdb:"_uuid"`
	CIDR        string            `ovsdb:"cidr"`
	Options     map[string]string `ovsdb:"options"`
	ExternalIDs map[string]string `ovsdb:"external_ids"`
}

// LogicalRouter represents an OVN Logical Router
type LogicalRouter struct {
	UUID         string            `ovsdb:"_uuid"`
	Name         string            `ovsdb:"name"`
	Ports        []string          `ovsdb:"ports"`
	StaticRoutes []string          `ovsdb:"static_routes"`
	Policies     []string          `ovsdb:"policies"`
	Enabled      *bool             `ovsdb:"enabled"`
	ExternalIDs  map[string]string `ovsdb:"external_ids"`
	Options      map[string]string `ovsdb:"options"`
}

// TableName returns the OVN database table name
func (LogicalRouter) TableName() string {
	return "Logical_Router"
}

// LogicalRouterPort represents an OVN Logical Router Port
type LogicalRouterPort struct {
	UUID        string            `ovsdb:"_uuid"`
	Name        string            `ovsdb:"name"`
	MAC         string            `ovsdb:"mac"`
	Networks    []string          `ovsdb:"networks"`
	Enabled     *bool             `ovsdb:"enabled"`
	ExternalIDs map[string]string `ovsdb:"external_ids"`
	Options     map[string]string `ovsdb:"options"`
	Peer        *string           `ovsdb:"peer"`
}

// TableName returns the OVN database table name
func (LogicalRouterPort) TableName() string {
	return "Logical_Router_Port"
}

// LogicalRouterStaticRoute represents a static route in OVN
type LogicalRouterStaticRoute struct {
	UUID        string            `ovsdb:"_uuid"`
	IPPrefix    string            `ovsdb:"ip_prefix"`
	Nexthop     string            `ovsdb:"nexthop"`
	OutputPort  *string           `ovsdb:"output_port"`
	Policy      *string           `ovsdb:"policy"`
	ExternalIDs map[string]string `ovsdb:"external_ids"`
}

// ACL represents an OVN Access Control List entry
type ACL struct {
	UUID        string            `ovsdb:"_uuid"`
	Action      string            `ovsdb:"action"`
	Direction   string            `ovsdb:"direction"`
	Match       string            `ovsdb:"match"`
	Priority    int               `ovsdb:"priority"`
	ExternalIDs map[string]string `ovsdb:"external_ids"`
	Log         bool              `ovsdb:"log"`
	Name        *string           `ovsdb:"name"`
	Severity    *string           `ovsdb:"severity"`
}

// LoadBalancer represents an OVN Load Balancer
type LoadBalancer struct {
	UUID        string            `ovsdb:"_uuid"`
	Name        string            `ovsdb:"name"`
	Vips        map[string]string `ovsdb:"vips"`
	Protocol    *string           `ovsdb:"protocol"`
	ExternalIDs map[string]string `ovsdb:"external_ids"`
	Options     map[string]string `ovsdb:"options"`
}

// AddressSet represents an OVN Address Set
type AddressSet struct {
	UUID        string            `ovsdb:"_uuid"`
	Name        string            `ovsdb:"name"`
	Addresses   []string          `ovsdb:"addresses"`
	ExternalIDs map[string]string `ovsdb:"external_ids"`
}

// PortGroup represents an OVN Port Group
type PortGroup struct {
	UUID        string            `ovsdb:"_uuid"`
	Name        string            `ovsdb:"name"`
	Ports       []string          `ovsdb:"ports"`
	ACLs        []string          `ovsdb:"acls"`
	ExternalIDs map[string]string `ovsdb:"external_ids"`
}
