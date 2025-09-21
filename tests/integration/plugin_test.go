package integration

import (
	"context"
	"fmt"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"

	"github.com/docker/docker/api/types"
	"github.com/docker/docker/api/types/container"
	"github.com/docker/docker/api/types/network"
	"github.com/docker/docker/client"
)

const (
	pluginName      = "ovs-container-network:latest"
	testNetPrefix   = "itest-net"
	testContPrefix  = "itest-cont"
	testTimeout     = 30 * time.Second
)

var dockerClient *client.Client

func TestMain(m *testing.M) {
	// Setup
	var err error
	dockerClient, err = client.NewClientWithOpts(client.FromEnv)
	if err != nil {
		fmt.Printf("Failed to create Docker client: %v\n", err)
		os.Exit(1)
	}

	// Cleanup before tests
	cleanup()

	// Run tests
	code := m.Run()

	// Cleanup after tests
	cleanup()

	os.Exit(code)
}

func cleanup() {
	ctx := context.Background()

	// Remove test containers
	containers, _ := dockerClient.ContainerList(ctx, types.ContainerListOptions{All: true})
	for _, cont := range containers {
		for _, name := range cont.Names {
			if strings.Contains(name, testContPrefix) {
				dockerClient.ContainerStop(ctx, cont.ID, container.StopOptions{})
				dockerClient.ContainerRemove(ctx, cont.ID, types.ContainerRemoveOptions{Force: true})
			}
		}
	}

	// Remove test networks
	networks, _ := dockerClient.NetworkList(ctx, types.NetworkListOptions{})
	for _, net := range networks {
		if strings.HasPrefix(net.Name, testNetPrefix) {
			dockerClient.NetworkRemove(ctx, net.ID)
		}
	}
}

func TestPluginEnabled(t *testing.T) {
	cmd := exec.Command("docker", "plugin", "ls")
	output, err := cmd.Output()
	if err != nil {
		t.Fatalf("Failed to list plugins: %v", err)
	}

	if !strings.Contains(string(output), pluginName) {
		t.Fatalf("Plugin %s not found", pluginName)
	}

	if !strings.Contains(string(output), "true") {
		t.Fatalf("Plugin %s not enabled", pluginName)
	}
}

func TestBasicNetworkLifecycle(t *testing.T) {
	ctx := context.Background()
	networkName := fmt.Sprintf("%s-basic", testNetPrefix)

	// Create network
	netConfig := types.NetworkCreate{
		Driver: pluginName,
		IPAM: &network.IPAM{
			Config: []network.IPAMConfig{
				{
					Subnet: "10.200.0.0/24",
				},
			},
		},
	}

	resp, err := dockerClient.NetworkCreate(ctx, networkName, netConfig)
	if err != nil {
		t.Fatalf("Failed to create network: %v", err)
	}

	// Verify network exists
	net, err := dockerClient.NetworkInspect(ctx, resp.ID, types.NetworkInspectOptions{})
	if err != nil {
		t.Fatalf("Failed to inspect network: %v", err)
	}

	if net.Name != networkName {
		t.Errorf("Network name mismatch: expected %s, got %s", networkName, net.Name)
	}

	if net.Driver != pluginName {
		t.Errorf("Driver mismatch: expected %s, got %s", pluginName, net.Driver)
	}

	// Delete network
	err = dockerClient.NetworkRemove(ctx, resp.ID)
	if err != nil {
		t.Fatalf("Failed to delete network: %v", err)
	}

	// Verify network is gone
	_, err = dockerClient.NetworkInspect(ctx, resp.ID, types.NetworkInspectOptions{})
	if err == nil {
		t.Error("Network still exists after deletion")
	}
}

func TestContainerConnectivity(t *testing.T) {
	ctx := context.Background()
	networkName := fmt.Sprintf("%s-connectivity", testNetPrefix)

	// Create network
	netConfig := types.NetworkCreate{
		Driver: pluginName,
		IPAM: &network.IPAM{
			Config: []network.IPAMConfig{
				{
					Subnet: "10.201.0.0/24",
				},
			},
		},
		Options: map[string]string{
			"bridge": "br-int",
			"vlan":   "50",
		},
	}

	netResp, err := dockerClient.NetworkCreate(ctx, networkName, netConfig)
	if err != nil {
		t.Fatalf("Failed to create network: %v", err)
	}
	defer dockerClient.NetworkRemove(ctx, netResp.ID)

	// Create two containers
	container1Name := fmt.Sprintf("%s-conn1", testContPrefix)
	container2Name := fmt.Sprintf("%s-conn2", testContPrefix)

	cont1, err := createTestContainer(ctx, container1Name, networkName)
	if err != nil {
		t.Fatalf("Failed to create container 1: %v", err)
	}
	defer dockerClient.ContainerRemove(ctx, cont1, types.ContainerRemoveOptions{Force: true})

	cont2, err := createTestContainer(ctx, container2Name, networkName)
	if err != nil {
		t.Fatalf("Failed to create container 2: %v", err)
	}
	defer dockerClient.ContainerRemove(ctx, cont2, types.ContainerRemoveOptions{Force: true})

	// Start containers
	if err := dockerClient.ContainerStart(ctx, cont1, types.ContainerStartOptions{}); err != nil {
		t.Fatalf("Failed to start container 1: %v", err)
	}
	if err := dockerClient.ContainerStart(ctx, cont2, types.ContainerStartOptions{}); err != nil {
		t.Fatalf("Failed to start container 2: %v", err)
	}

	// Wait for containers to be ready
	time.Sleep(3 * time.Second)

	// Get container IPs
	cont1Info, err := dockerClient.ContainerInspect(ctx, cont1)
	if err != nil {
		t.Fatalf("Failed to inspect container 1: %v", err)
	}

	cont2Info, err := dockerClient.ContainerInspect(ctx, cont2)
	if err != nil {
		t.Fatalf("Failed to inspect container 2: %v", err)
	}

	cont1IP := cont1Info.NetworkSettings.Networks[networkName].IPAddress
	cont2IP := cont2Info.NetworkSettings.Networks[networkName].IPAddress

	if cont1IP == "" || cont2IP == "" {
		t.Fatalf("Containers did not get IP addresses: cont1=%s, cont2=%s", cont1IP, cont2IP)
	}

	// Test ping from container1 to container2
	execConfig := types.ExecConfig{
		Cmd:          []string{"ping", "-c", "2", "-W", "2", cont2IP},
		AttachStdout: true,
		AttachStderr: true,
	}

	execResp, err := dockerClient.ContainerExecCreate(ctx, cont1, execConfig)
	if err != nil {
		t.Fatalf("Failed to create exec: %v", err)
	}

	execStartCheck := types.ExecStartCheck{}
	if err := dockerClient.ContainerExecStart(ctx, execResp.ID, execStartCheck); err != nil {
		t.Fatalf("Failed to start exec: %v", err)
	}

	// Wait for exec to complete
	time.Sleep(3 * time.Second)

	execInspect, err := dockerClient.ContainerExecInspect(ctx, execResp.ID)
	if err != nil {
		t.Fatalf("Failed to inspect exec: %v", err)
	}

	if execInspect.ExitCode != 0 {
		t.Errorf("Ping failed with exit code %d", execInspect.ExitCode)
	}
}

func TestVLANIsolation(t *testing.T) {
	ctx := context.Background()

	// Create two networks with different VLANs
	network1Name := fmt.Sprintf("%s-vlan100", testNetPrefix)
	network2Name := fmt.Sprintf("%s-vlan200", testNetPrefix)

	netConfig1 := types.NetworkCreate{
		Driver: pluginName,
		IPAM: &network.IPAM{
			Config: []network.IPAMConfig{{Subnet: "10.202.0.0/24"}},
		},
		Options: map[string]string{"vlan": "100"},
	}

	netConfig2 := types.NetworkCreate{
		Driver: pluginName,
		IPAM: &network.IPAM{
			Config: []network.IPAMConfig{{Subnet: "10.203.0.0/24"}},
		},
		Options: map[string]string{"vlan": "200"},
	}

	net1Resp, err := dockerClient.NetworkCreate(ctx, network1Name, netConfig1)
	if err != nil {
		t.Fatalf("Failed to create network 1: %v", err)
	}
	defer dockerClient.NetworkRemove(ctx, net1Resp.ID)

	net2Resp, err := dockerClient.NetworkCreate(ctx, network2Name, netConfig2)
	if err != nil {
		t.Fatalf("Failed to create network 2: %v", err)
	}
	defer dockerClient.NetworkRemove(ctx, net2Resp.ID)

	// Create containers on different VLANs
	cont1, err := createTestContainer(ctx, fmt.Sprintf("%s-vlan1", testContPrefix), network1Name)
	if err != nil {
		t.Fatalf("Failed to create container on VLAN 100: %v", err)
	}
	defer dockerClient.ContainerRemove(ctx, cont1, types.ContainerRemoveOptions{Force: true})

	cont2, err := createTestContainer(ctx, fmt.Sprintf("%s-vlan2", testContPrefix), network2Name)
	if err != nil {
		t.Fatalf("Failed to create container on VLAN 200: %v", err)
	}
	defer dockerClient.ContainerRemove(ctx, cont2, types.ContainerRemoveOptions{Force: true})

	// Start containers
	dockerClient.ContainerStart(ctx, cont1, types.ContainerStartOptions{})
	dockerClient.ContainerStart(ctx, cont2, types.ContainerStartOptions{})

	time.Sleep(3 * time.Second)

	// Get container 2 IP
	cont2Info, _ := dockerClient.ContainerInspect(ctx, cont2)
	cont2IP := cont2Info.NetworkSettings.Networks[network2Name].IPAddress

	// Try to ping from container 1 to container 2 (should fail due to VLAN isolation)
	execConfig := types.ExecConfig{
		Cmd:          []string{"ping", "-c", "1", "-W", "1", cont2IP},
		AttachStdout: true,
		AttachStderr: true,
	}

	execResp, _ := dockerClient.ContainerExecCreate(ctx, cont1, execConfig)
	dockerClient.ContainerExecStart(ctx, execResp.ID, types.ExecStartCheck{})

	time.Sleep(2 * time.Second)

	execInspect, _ := dockerClient.ContainerExecInspect(ctx, execResp.ID)

	// Ping should fail (exit code != 0) due to VLAN isolation
	if execInspect.ExitCode == 0 {
		t.Error("VLAN isolation failed: containers on different VLANs can communicate")
	}
}

func TestPersistentState(t *testing.T) {
	ctx := context.Background()
	networkName := fmt.Sprintf("%s-persistent", testNetPrefix)

	// Create network
	netConfig := types.NetworkCreate{
		Driver: pluginName,
		IPAM: &network.IPAM{
			Config: []network.IPAMConfig{{Subnet: "10.204.0.0/24"}},
		},
	}

	netResp, err := dockerClient.NetworkCreate(ctx, networkName, netConfig)
	if err != nil {
		t.Fatalf("Failed to create network: %v", err)
	}
	defer dockerClient.NetworkRemove(ctx, netResp.ID)

	// Create and start container
	contName := fmt.Sprintf("%s-persist", testContPrefix)
	contID, err := createTestContainer(ctx, contName, networkName)
	if err != nil {
		t.Fatalf("Failed to create container: %v", err)
	}
	defer dockerClient.ContainerRemove(ctx, contID, types.ContainerRemoveOptions{Force: true})

	dockerClient.ContainerStart(ctx, contID, types.ContainerStartOptions{})
	time.Sleep(2 * time.Second)

	// Get initial IP
	contInfo, _ := dockerClient.ContainerInspect(ctx, contID)
	ipBefore := contInfo.NetworkSettings.Networks[networkName].IPAddress

	// Simulate plugin restart
	cmd := exec.Command("docker", "plugin", "disable", pluginName)
	cmd.Run()
	time.Sleep(2 * time.Second)

	cmd = exec.Command("docker", "plugin", "enable", pluginName)
	cmd.Run()
	time.Sleep(3 * time.Second)

	// Restart container
	dockerClient.ContainerRestart(ctx, contID, container.StopOptions{})
	time.Sleep(2 * time.Second)

	// Get IP after restart
	contInfo, _ = dockerClient.ContainerInspect(ctx, contID)
	ipAfter := contInfo.NetworkSettings.Networks[networkName].IPAddress

	// IP should be preserved
	if ipBefore != ipAfter {
		t.Errorf("IP address not preserved after plugin restart: before=%s, after=%s", ipBefore, ipAfter)
	}
}

func TestOVNIntegration(t *testing.T) {
	ctx := context.Background()
	networkName := fmt.Sprintf("%s-ovn", testNetPrefix)

	// Create network with OVN options
	netConfig := types.NetworkCreate{
		Driver: pluginName,
		IPAM: &network.IPAM{
			Config: []network.IPAMConfig{{Subnet: "10.205.0.0/24"}},
		},
		Options: map[string]string{
			"ovn.switch":        "ls-test",
			"ovn.auto_create":   "true",
			"ovn.nb_connection": "tcp:172.30.0.5:6641",
			"ovn.sb_connection": "tcp:172.30.0.5:6642",
		},
	}

	resp, err := dockerClient.NetworkCreate(ctx, networkName, netConfig)
	if err != nil {
		t.Fatalf("Failed to create OVN network: %v", err)
	}
	defer dockerClient.NetworkRemove(ctx, resp.ID)

	// Verify OVN central is running
	containers, _ := dockerClient.ContainerList(ctx, types.ContainerListOptions{})
	ovnCentralFound := false
	for _, cont := range containers {
		for _, name := range cont.Names {
			if strings.Contains(name, "ovn-central") {
				ovnCentralFound = true
				break
			}
		}
	}

	if !ovnCentralFound {
		t.Error("OVN central container not found after auto-create")
	}

	// Verify logical switch was created
	cmd := exec.Command("docker", "exec", "ovn-central", "ovn-nbctl", "ls-list")
	output, err := cmd.Output()
	if err == nil && strings.Contains(string(output), "ls-test") {
		t.Log("OVN logical switch created successfully")
	} else {
		t.Error("OVN logical switch not found")
	}
}

// Helper function to create a test container
func createTestContainer(ctx context.Context, name, networkName string) (string, error) {
	config := &container.Config{
		Image: "alpine:latest",
		Cmd:   []string{"sleep", "3600"},
	}

	hostConfig := &container.HostConfig{}

	netConfig := &network.NetworkingConfig{
		EndpointsConfig: map[string]*network.EndpointSettings{
			networkName: {},
		},
	}

	resp, err := dockerClient.ContainerCreate(ctx, config, hostConfig, netConfig, nil, name)
	if err != nil {
		return "", err
	}

	return resp.ID, nil
}