package store

import (
	"encoding/json"
	"fmt"
	"io/ioutil"
	"os"
	"path/filepath"
	"testing"
)

func TestNewStore(t *testing.T) {
	// Create temp directory
	tmpDir, err := ioutil.TempDir("", "store_test")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(tmpDir)

	// Test creating new store
	store, err := NewStore(tmpDir)
	if err != nil {
		t.Fatalf("Failed to create store: %v", err)
	}

	if store.dataDir != tmpDir {
		t.Errorf("Expected dataDir to be %s, got %s", tmpDir, store.dataDir)
	}

	// Verify directories exist
	if _, err := os.Stat(tmpDir); os.IsNotExist(err) {
		t.Error("Data directory was not created")
	}
}

func TestNetworkPersistence(t *testing.T) {
	tmpDir, err := ioutil.TempDir("", "store_test")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(tmpDir)

	store, err := NewStore(tmpDir)
	if err != nil {
		t.Fatal(err)
	}

	// Create test network
	network := &NetworkInfo{
		ID:        "test-net-123",
		Name:      "test-network",
		Bridge:    "br-test",
		VLAN:      100,
		TenantID:  "tenant-1",
		OVNSwitch: "ls-test",
		OVNRouter: "lr-test",
		Options: map[string]string{
			"foo": "bar",
		},
	}

	// Save network
	if err := store.SaveNetwork(network); err != nil {
		t.Fatalf("Failed to save network: %v", err)
	}

	// Verify file exists
	networkFile := filepath.Join(tmpDir, "networks.json")
	if _, err := os.Stat(networkFile); os.IsNotExist(err) {
		t.Error("Networks file was not created")
	}

	// Retrieve network
	retrieved, err := store.GetNetwork("test-net-123")
	if err != nil {
		t.Fatalf("Failed to retrieve network: %v", err)
	}

	// Verify fields match
	if retrieved.ID != network.ID {
		t.Errorf("ID mismatch: expected %s, got %s", network.ID, retrieved.ID)
	}
	if retrieved.VLAN != network.VLAN {
		t.Errorf("VLAN mismatch: expected %d, got %d", network.VLAN, retrieved.VLAN)
	}
	if retrieved.Options["foo"] != "bar" {
		t.Error("Options not preserved correctly")
	}

	// Test listing networks
	networks := store.ListNetworks()
	if len(networks) != 1 {
		t.Errorf("Expected 1 network, got %d", len(networks))
	}

	// Delete network
	if err := store.DeleteNetwork("test-net-123"); err != nil {
		t.Fatalf("Failed to delete network: %v", err)
	}

	// Verify it's gone
	_, err = store.GetNetwork("test-net-123")
	if err == nil {
		t.Error("Expected error when retrieving deleted network")
	}
}

func TestEndpointPersistence(t *testing.T) {
	tmpDir, err := ioutil.TempDir("", "store_test")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(tmpDir)

	store, err := NewStore(tmpDir)
	if err != nil {
		t.Fatal(err)
	}

	// Create test endpoint
	endpoint := &EndpointInfo{
		ID:          "net1:ep1",
		NetworkID:   "net1",
		EndpointID:  "ep1",
		ContainerID: "container1",
		VethName:    "veth123",
		IPAddress:   "10.0.0.5/24",
		MACAddress:  "02:00:00:00:00:05",
		Gateway:     "10.0.0.1",
		OVNPort:     "lsp-ep1",
	}

	// Save endpoint
	if err := store.SaveEndpoint(endpoint); err != nil {
		t.Fatalf("Failed to save endpoint: %v", err)
	}

	// Verify file exists
	endpointFile := filepath.Join(tmpDir, "endpoints.json")
	if _, err := os.Stat(endpointFile); os.IsNotExist(err) {
		t.Error("Endpoints file was not created")
	}

	// Retrieve endpoint
	retrieved, err := store.GetEndpoint("net1", "ep1")
	if err != nil {
		t.Fatalf("Failed to retrieve endpoint: %v", err)
	}

	// Verify fields match
	if retrieved.IPAddress != endpoint.IPAddress {
		t.Errorf("IP mismatch: expected %s, got %s", endpoint.IPAddress, retrieved.IPAddress)
	}
	if retrieved.VethName != endpoint.VethName {
		t.Errorf("Veth mismatch: expected %s, got %s", endpoint.VethName, retrieved.VethName)
	}

	// Test listing endpoints
	endpoints := store.ListEndpoints()
	if len(endpoints) != 1 {
		t.Errorf("Expected 1 endpoint, got %d", len(endpoints))
	}

	// Delete endpoint
	if err := store.DeleteEndpoint("net1", "ep1"); err != nil {
		t.Fatalf("Failed to delete endpoint: %v", err)
	}

	// Verify it's gone
	_, err = store.GetEndpoint("net1", "ep1")
	if err == nil {
		t.Error("Expected error when retrieving deleted endpoint")
	}
}

func TestStoreRecovery(t *testing.T) {
	tmpDir, err := ioutil.TempDir("", "store_test")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(tmpDir)

	// Create initial store and save data
	store1, err := NewStore(tmpDir)
	if err != nil {
		t.Fatal(err)
	}

	network := &NetworkInfo{
		ID:       "persist-net",
		Name:     "persistent",
		Bridge:   "br-persist",
		VLAN:     200,
		TenantID: "tenant-2",
	}

	endpoint := &EndpointInfo{
		ID:         "persist-net:persist-ep",
		NetworkID:  "persist-net",
		EndpointID: "persist-ep",
		IPAddress:  "192.168.1.10/24",
		VethName:   "veth999",
	}

	store1.SaveNetwork(network)
	store1.SaveEndpoint(endpoint)

	// Simulate plugin restart by creating new store instance
	store2, err := NewStore(tmpDir)
	if err != nil {
		t.Fatal(err)
	}

	// Verify data was recovered
	recoveredNet, err := store2.GetNetwork("persist-net")
	if err != nil {
		t.Fatalf("Failed to recover network: %v", err)
	}
	if recoveredNet.VLAN != 200 {
		t.Errorf("Network not recovered correctly, VLAN expected 200, got %d", recoveredNet.VLAN)
	}

	recoveredEp, err := store2.GetEndpoint("persist-net", "persist-ep")
	if err != nil {
		t.Fatalf("Failed to recover endpoint: %v", err)
	}
	if recoveredEp.IPAddress != "192.168.1.10/24" {
		t.Errorf("Endpoint not recovered correctly, IP expected 192.168.1.10/24, got %s", recoveredEp.IPAddress)
	}

	// Verify recovery populated the lists
	if len(store2.ListNetworks()) != 1 {
		t.Error("Network list not populated on recovery")
	}
	if len(store2.ListEndpoints()) != 1 {
		t.Error("Endpoint list not populated on recovery")
	}
}

func TestCorruptedStateHandling(t *testing.T) {
	tmpDir, err := ioutil.TempDir("", "store_test")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(tmpDir)

	// Write corrupted JSON to networks file
	networkFile := filepath.Join(tmpDir, "networks.json")
	corruptedData := []byte(`{"invalid json": "}`)
	if err := ioutil.WriteFile(networkFile, corruptedData, 0644); err != nil {
		t.Fatal(err)
	}

	// Store should handle corrupted file gracefully
	store, err := NewStore(tmpDir)
	if err == nil {
		t.Log("Store handled corrupted file gracefully")
	} else {
		// Depending on implementation, might want to continue with empty state
		t.Logf("Store returned error for corrupted file: %v", err)
	}

	// Should still be able to save new data
	if store != nil {
		network := &NetworkInfo{
			ID:   "new-net",
			Name: "new",
		}
		if err := store.SaveNetwork(network); err != nil {
			t.Errorf("Failed to save after corruption: %v", err)
		}
	}
}

func TestConcurrentAccess(t *testing.T) {
	tmpDir, err := ioutil.TempDir("", "store_test")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(tmpDir)

	store, err := NewStore(tmpDir)
	if err != nil {
		t.Fatal(err)
	}

	// Test concurrent writes
	done := make(chan bool, 10)
	for i := 0; i < 10; i++ {
		go func(id int) {
			network := &NetworkInfo{
				ID:   fmt.Sprintf("net-%d", id),
				Name: fmt.Sprintf("network-%d", id),
				VLAN: id,
			}
			if err := store.SaveNetwork(network); err != nil {
				t.Errorf("Concurrent save failed: %v", err)
			}
			done <- true
		}(i)
	}

	// Wait for all goroutines
	for i := 0; i < 10; i++ {
		<-done
	}

	// Verify all networks were saved
	networks := store.ListNetworks()
	if len(networks) != 10 {
		t.Errorf("Expected 10 networks after concurrent saves, got %d", len(networks))
	}
}

func TestIPAMDataPersistence(t *testing.T) {
	tmpDir, err := ioutil.TempDir("", "store_test")
	if err != nil {
		t.Fatal(err)
	}
	defer os.RemoveAll(tmpDir)

	store, err := NewStore(tmpDir)
	if err != nil {
		t.Fatal(err)
	}

	// Create network with IPAM data
	ipamData := map[string]interface{}{
		"Pool":    "10.0.0.0/24",
		"Gateway": "10.0.0.1",
		"Range":   "10.0.0.10-10.0.0.100",
	}
	ipamBytes, _ := json.Marshal(ipamData)

	network := &NetworkInfo{
		ID:       "ipam-net",
		Name:     "ipam-network",
		IPAMData: ipamBytes,
	}

	if err := store.SaveNetwork(network); err != nil {
		t.Fatal(err)
	}

	// Retrieve and verify IPAM data
	retrieved, err := store.GetNetwork("ipam-net")
	if err != nil {
		t.Fatal(err)
	}

	var recoveredIPAM map[string]interface{}
	if err := json.Unmarshal(retrieved.IPAMData, &recoveredIPAM); err != nil {
		t.Fatalf("Failed to unmarshal IPAM data: %v", err)
	}

	if recoveredIPAM["Pool"] != "10.0.0.0/24" {
		t.Error("IPAM data not preserved correctly")
	}
}
