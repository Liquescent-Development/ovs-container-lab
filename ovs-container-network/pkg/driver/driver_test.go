package driver

import (
	"testing"

	"github.com/docker/go-plugins-helpers/network"
	"github.com/ovs-container-lab/ovs-container-network/pkg/types"
	"github.com/sirupsen/logrus"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
)

func TestDriverCapabilities(t *testing.T) {
	// Note: This test doesn't require actual OVS to be running
	logger := logrus.New()
	d := &Driver{
		networks:  make(map[string]*types.Network),
		endpoints: make(map[string]*types.Endpoint),
		logger:    logger,
	}

	resp, err := d.GetCapabilities()
	require.NoError(t, err)
	assert.NotNil(t, resp)
	assert.Equal(t, network.LocalScope, resp.Scope)
	assert.Equal(t, network.LocalScope, resp.ConnectivityScope)
}

func TestCreateNetwork(t *testing.T) {
	t.Skip("Skipping test that requires OVS mock")
}

func TestDeleteNetwork(t *testing.T) {
	logger := logrus.New()
	d := &Driver{
		networks:  make(map[string]*types.Network),
		endpoints: make(map[string]*types.Endpoint),
		logger:    logger,
	}

	// Add a network
	networkID := "test-network-456"
	d.networks[networkID] = &types.Network{
		ID:     networkID,
		Bridge: "br-test",
	}

	// Delete it
	req := &network.DeleteNetworkRequest{
		NetworkID: networkID,
	}

	err := d.DeleteNetwork(req)
	require.NoError(t, err)

	// Verify it's gone
	_, exists := d.networks[networkID]
	assert.False(t, exists)
}

func TestDeleteNetworkWithActiveEndpoints(t *testing.T) {
	logger := logrus.New()
	d := &Driver{
		networks:  make(map[string]*types.Network),
		endpoints: make(map[string]*types.Endpoint),
		logger:    logger,
	}

	// Add a network and an endpoint
	networkID := "test-network-789"
	d.networks[networkID] = &types.Network{
		ID:     networkID,
		Bridge: "br-test",
	}
	d.endpoints["endpoint-1"] = &types.Endpoint{
		ID:        "endpoint-1",
		NetworkID: networkID,
	}

	// Try to delete network
	req := &network.DeleteNetworkRequest{
		NetworkID: networkID,
	}

	err := d.DeleteNetwork(req)
	assert.Error(t, err, "Should fail when endpoints are active")
	assert.Contains(t, err.Error(), "active endpoints")

	// Network should still exist
	_, exists := d.networks[networkID]
	assert.True(t, exists)
}
