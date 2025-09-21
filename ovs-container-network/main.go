package main

import (
	"flag"
	"fmt"
	"os"

	"github.com/docker/go-plugins-helpers/network"
	"github.com/ovs-container-lab/ovs-container-network/pkg/driver"
	"github.com/sirupsen/logrus"
)

const (
	defaultSocketPath = "/run/docker/plugins/ovs-net.sock"
	pluginName        = "ovs-container-network"
	pluginVersion     = "0.1.0"
)

func main() {
	var (
		socketPath = flag.String("socket", defaultSocketPath, "Plugin socket path")
		debugMode  = flag.Bool("debug", false, "Enable debug logging")
		version    = flag.Bool("version", false, "Print version and exit")
	)
	flag.Parse()

	if *version {
		fmt.Printf("%s version %s\n", pluginName, pluginVersion)
		os.Exit(0)
	}

	// Configure logging
	if *debugMode {
		logrus.SetLevel(logrus.DebugLevel)
	} else {
		logrus.SetLevel(logrus.InfoLevel)
	}
	logrus.SetFormatter(&logrus.TextFormatter{
		FullTimestamp: true,
	})

	logrus.Infof("Starting %s version %s", pluginName, pluginVersion)
	logrus.Debugf("Socket path: %s", *socketPath)

	// Create the driver
	d, err := driver.New()
	if err != nil {
		logrus.Fatalf("Failed to create driver: %v", err)
	}

	// Create the plugin handler
	h := network.NewHandler(d)

	// Ensure the socket directory exists
	if err := os.MkdirAll("/run/docker/plugins", 0755); err != nil {
		logrus.Fatalf("Failed to create plugin directory: %v", err)
	}

	// Remove any existing socket
	os.Remove(*socketPath)

	// Start serving
	logrus.Infof("Listening on %s", *socketPath)
	if err := h.ServeUnix(*socketPath, 0); err != nil {
		logrus.Fatalf("Failed to serve: %v", err)
	}
}
