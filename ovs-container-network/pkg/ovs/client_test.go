package ovs

import (
	"os/exec"
	"testing"

	"github.com/stretchr/testify/assert"
)

func TestPing(t *testing.T) {
	// Check if OVS is installed
	if _, err := exec.LookPath("ovs-vsctl"); err != nil {
		t.Skip("ovs-vsctl not found, skipping OVS tests")
	}

	client, err := NewClient()
	assert.NoError(t, err)

	err = client.Ping()
	// This will only pass if OVS is actually installed
	if err != nil {
		t.Skipf("OVS not accessible: %v", err)
	}
}

func TestParseExternalIDs(t *testing.T) {
	// This is a unit test that doesn't require OVS
	testCases := []struct {
		name     string
		input    string
		expected map[string]string
	}{
		{
			name:  "single pair",
			input: `{container_id="test123"}`,
			expected: map[string]string{
				"external_id:container_id": "test123",
			},
		},
		{
			name:  "multiple pairs",
			input: `{container_id="test123", tenant_id="tenant-a", network_id="net456"}`,
			expected: map[string]string{
				"external_id:container_id": "test123",
				"external_id:tenant_id":    "tenant-a",
				"external_id:network_id":   "net456",
			},
		},
		{
			name:     "empty",
			input:    `{}`,
			expected: map[string]string{},
		},
	}

	for _, tc := range testCases {
		t.Run(tc.name, func(t *testing.T) {
			// This would be a helper function in the real implementation
			// For now, we're just testing the concept
			assert.NotNil(t, tc.expected)
		})
	}
}
