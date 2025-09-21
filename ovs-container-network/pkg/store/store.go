package store

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"os"
	"path/filepath"
	"sync"
)

// NetworkInfo stores persistent network configuration
type NetworkInfo struct {
	ID        string            `json:"id"`
	Name      string            `json:"name"`
	Bridge    string            `json:"bridge"`
	VLAN      int               `json:"vlan,omitempty"`
	TenantID  string            `json:"tenant_id,omitempty"`
	OVNSwitch string            `json:"ovn_switch,omitempty"`
	OVNRouter string            `json:"ovn_router,omitempty"`
	Options   map[string]string `json:"options"`
	IPAMData  json.RawMessage   `json:"ipam_data"`
}

// EndpointInfo stores persistent endpoint configuration
type EndpointInfo struct {
	ID          string `json:"id"`
	NetworkID   string `json:"network_id"`
	EndpointID  string `json:"endpoint_id"`
	ContainerID string `json:"container_id"`
	VethName    string `json:"veth_name"`
	IPAddress   string `json:"ip_address"`
	MACAddress  string `json:"mac_address"`
	Gateway     string `json:"gateway"`
	OVNPort     string `json:"ovn_port,omitempty"`
}

// Store manages persistent plugin state
type Store struct {
	dataDir   string
	mu        sync.RWMutex
	networks  map[string]*NetworkInfo
	endpoints map[string]*EndpointInfo
}

// NewStore creates a new persistent store
func NewStore(dataDir string) (*Store, error) {
	if dataDir == "" {
		dataDir = "/data"
	}

	// Create data directory if it doesn't exist
	if err := os.MkdirAll(dataDir, 0755); err != nil {
		return nil, fmt.Errorf("failed to create data directory: %w", err)
	}

	s := &Store{
		dataDir:   dataDir,
		networks:  make(map[string]*NetworkInfo),
		endpoints: make(map[string]*EndpointInfo),
	}

	// Load existing state
	if err := s.load(); err != nil {
		return nil, fmt.Errorf("failed to load state: %w", err)
	}

	return s, nil
}

// SaveNetwork persists network configuration
func (s *Store) SaveNetwork(network *NetworkInfo) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	s.networks[network.ID] = network
	return s.persist()
}

// GetNetwork retrieves network configuration
func (s *Store) GetNetwork(networkID string) (*NetworkInfo, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	network, ok := s.networks[networkID]
	if !ok {
		return nil, fmt.Errorf("network %s not found", networkID)
	}
	return network, nil
}

// DeleteNetwork removes network configuration
func (s *Store) DeleteNetwork(networkID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	delete(s.networks, networkID)
	return s.persist()
}

// SaveEndpoint persists endpoint configuration
func (s *Store) SaveEndpoint(endpoint *EndpointInfo) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	key := fmt.Sprintf("%s:%s", endpoint.NetworkID, endpoint.EndpointID)
	s.endpoints[key] = endpoint
	return s.persist()
}

// GetEndpoint retrieves endpoint configuration
func (s *Store) GetEndpoint(networkID, endpointID string) (*EndpointInfo, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()

	key := fmt.Sprintf("%s:%s", networkID, endpointID)
	endpoint, ok := s.endpoints[key]
	if !ok {
		return nil, fmt.Errorf("endpoint %s not found", key)
	}
	return endpoint, nil
}

// DeleteEndpoint removes endpoint configuration
func (s *Store) DeleteEndpoint(networkID, endpointID string) error {
	s.mu.Lock()
	defer s.mu.Unlock()

	key := fmt.Sprintf("%s:%s", networkID, endpointID)
	delete(s.endpoints, key)
	return s.persist()
}

// ListNetworks returns all networks
func (s *Store) ListNetworks() []*NetworkInfo {
	s.mu.RLock()
	defer s.mu.RUnlock()

	networks := make([]*NetworkInfo, 0, len(s.networks))
	for _, network := range s.networks {
		networks = append(networks, network)
	}
	return networks
}

// ListEndpoints returns all endpoints
func (s *Store) ListEndpoints() []*EndpointInfo {
	s.mu.RLock()
	defer s.mu.RUnlock()

	endpoints := make([]*EndpointInfo, 0, len(s.endpoints))
	for _, endpoint := range s.endpoints {
		endpoints = append(endpoints, endpoint)
	}
	return endpoints
}

// persist saves state to disk
func (s *Store) persist() error {
	// Save networks
	networksFile := filepath.Join(s.dataDir, "networks.json")
	data, err := json.MarshalIndent(s.networks, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal networks: %w", err)
	}
	if err := ioutil.WriteFile(networksFile, data, 0644); err != nil {
		return fmt.Errorf("failed to write networks file: %w", err)
	}

	// Save endpoints
	endpointsFile := filepath.Join(s.dataDir, "endpoints.json")
	data, err = json.MarshalIndent(s.endpoints, "", "  ")
	if err != nil {
		return fmt.Errorf("failed to marshal endpoints: %w", err)
	}
	if err := ioutil.WriteFile(endpointsFile, data, 0644); err != nil {
		return fmt.Errorf("failed to write endpoints file: %w", err)
	}

	return nil
}

// load reads state from disk
func (s *Store) load() error {
	// Load networks
	networksFile := filepath.Join(s.dataDir, "networks.json")
	if data, err := ioutil.ReadFile(networksFile); err == nil {
		if err := json.Unmarshal(data, &s.networks); err != nil {
			return fmt.Errorf("failed to unmarshal networks: %w", err)
		}
	}

	// Load endpoints
	endpointsFile := filepath.Join(s.dataDir, "endpoints.json")
	if data, err := ioutil.ReadFile(endpointsFile); err == nil {
		if err := json.Unmarshal(data, &s.endpoints); err != nil {
			return fmt.Errorf("failed to unmarshal endpoints: %w", err)
		}
	}

	return nil
}

// Recover attempts to recover network state on plugin restart
func (s *Store) Recover() error {
	s.mu.RLock()
	defer s.mu.RUnlock()

	// Log what we're recovering
	fmt.Printf("Recovering plugin state: %d networks, %d endpoints\n",
		len(s.networks), len(s.endpoints))

	// Here you would:
	// 1. Verify OVS bridges still exist
	// 2. Check OVN logical switches/routers still exist
	// 3. Verify veth pairs are still connected
	// 4. Re-establish any missing connections
	// 5. Clean up orphaned resources

	return nil
}
