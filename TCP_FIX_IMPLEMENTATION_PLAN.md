# TCP Fix Implementation Plan

## Problem Statement
TCP traffic is not working between containers connected via OVN/OVS, while ICMP and UDP work fine. Investigation showed:
- TCP SYN packets ARE being sent from containers
- Packets flow through OVN logical pipeline correctly
- Packets reach the OVS output action
- But packets never arrive at destination container

## Root Cause Analysis

### CRITICAL ISSUE: OVN Controller Not Running
- **Evidence**: ovn-controller.service is stopped on host
- **Evidence**: No chassis registered for host in OVN
- **Evidence**: OVS system-id is "chassis-host" but no matching chassis in OVN
- **Impact**: Ports cannot bind, flows cannot be programmed, TCP cannot work
- **This is likely THE root cause**

### Potential Issue 1: Port Binding Misconfiguration
- **Evidence**: Flows showed traffic-gen-a on port 9, but some flows expected port 10
- **Evidence**: External IDs (iface-id) might not match between OVS and OVN
- **Impact**: Packets routed to wrong port or dropped

### Potential Issue 2: Checksum Offloading
- **Evidence**: OVS statistics show tx_packets but tcpdump sees nothing
- **Evidence**: Common issue with userspace datapath and veth pairs
- **Impact**: Packets dropped silently by kernel

### Potential Issue 3: Container Network Stack
- **Evidence**: Containers with `network_mode: none` may have incomplete network stack
- **Evidence**: TCP needs more kernel modules than ICMP/UDP
- **Impact**: TCP state machine not functioning

## Implementation Plan

### Phase 0: FIX OVN CONTROLLER (CRITICAL)
1. **Start and Configure ovn-controller on Host**
   ```bash
   # Set OVN remote to point to ovn-central container
   sudo ovs-vsctl set open_vswitch . external_ids:ovn-remote="tcp:192.168.100.5:6642"
   sudo ovs-vsctl set open_vswitch . external_ids:ovn-encap-type="geneve"
   sudo ovs-vsctl set open_vswitch . external_ids:ovn-encap-ip="192.168.100.1"

   # Start ovn-controller
   sudo systemctl start ovn-controller
   sudo systemctl enable ovn-controller

   # Verify chassis registration
   docker exec ovn-central ovn-sbctl show
   # Should show chassis with system-id matching host
   ```

2. **Verify Port Binding Works**
   ```bash
   # Check that ports can bind to chassis
   docker exec ovn-central ovn-sbctl list Port_Binding
   # chassis column should not be empty
   ```

### Phase 1: Revert to Manual Approach (Known Working Base)
1. **Revert orchestrator.py**
   - Remove Docker network creation code
   - Restore `bind_container_to_ovn()` function
   - Keep improved ACL configuration (stateless)

2. **Revert docker-compose.yml** (CRITICAL)
   - Change ALL containers back to `network_mode: none`
   - This ensures containers have NO network except through OVS
   - Remove external network definitions
   - Containers will ONLY have connectivity via OVN/OVS
   - Example:
   ```yaml
   vpc-a-web:
     network_mode: none  # Forces all traffic through OVS
   ```

3. **Revert Makefile**
   - Restore container binding steps
   - Containers start with no network, then get connected to OVN

### Phase 2: Fix Port Binding Configuration
1. **Ensure Consistent Port Assignment**
   ```python
   def bind_container_to_ovn(self, container_name, ...):
       # Store port number mapping
       port_num = self.allocate_port_number(container_name)

       # Set external-ids with iface-id
       ovs_vsctl(["set", "Interface", veth_name,
                 f"external_ids:iface-id=lsp-{container_name}"])

       # Verify OVN binding
       ovn-sbctl(["wait-until", "Port_Binding",
                 f"lsp-{container_name}", "chassis!=[]"])
   ```

2. **Add Port Verification**
   ```python
   def verify_port_binding(self, container_name):
       # Check OVS port number
       ovs_port = get_ovs_port_number(container_name)

       # Check OVN logical port
       ovn_port = get_ovn_logical_port(container_name)

       # Verify they match
       assert ovs_port == expected_port
   ```

### Phase 3: Fix Checksum Offloading
1. **Disable Checksum Offload on All veth Interfaces**
   ```python
   def configure_veth_interface(self, veth_name):
       # Disable all checksum offloading
       subprocess.run(["ethtool", "-K", veth_name,
                      "tx", "off", "rx", "off",
                      "tso", "off", "gso", "off"])

       # Also disable on container side
       subprocess.run(["docker", "exec", container_name,
                      "ethtool", "-K", "eth1",
                      "tx", "off", "rx", "off"])
   ```

2. **Configure OVS for Userspace Datapath**
   ```bash
   # Global OVS configuration
   ovs-vsctl set Open_vSwitch . other_config:userspace-tso-enable=false
   ovs-vsctl set Open_vSwitch . other_config:tx-flush-interval=0
   ```

### Phase 4: Ensure Complete Network Stack
1. **Initialize Network Stack Properly**
   ```python
   def setup_container_network(self, container_name):
       # Start with lo interface up
       docker_exec(container_name, ["ip", "link", "set", "lo", "up"])

       # Load necessary kernel modules (if needed)
       docker_exec(container_name, ["modprobe", "tcp_cubic"])

       # Set proper sysctls
       docker_exec(container_name, ["sysctl", "-w",
                                   "net.ipv4.tcp_timestamps=1"])
   ```

### Phase 5: Testing Protocol
1. **Test After Each Fix**
   - Test 1: After reverting (baseline)
   - Test 2: After fixing port binding
   - Test 3: After disabling checksums
   - Test 4: After network stack init

2. **Test Commands**
   ```bash
   # Simple TCP test
   docker exec traffic-gen-a nc -zv 10.0.1.10 80

   # With packet capture
   docker exec vpc-a-web tcpdump -i eth1 -nn tcp &
   docker exec traffic-gen-a curl http://10.0.1.10
   ```

3. **Diagnostic Commands**
   ```bash
   # Check port binding
   ovs-vsctl show | grep -A2 veth-tg-a
   ovn-sbctl show | grep traffic-gen-a

   # Check checksums
   ethtool -k veth-tg-a | grep checksum

   # Check OVS flows with packets
   ovs-ofctl dump-flows br-int | grep n_packets=[1-9]
   ```

## Success Criteria
- [ ] TCP connection succeeds: `nc -zv 10.0.1.10 80` returns success
- [ ] HTTP request works: `curl http://10.0.1.10` returns response
- [ ] Packet captures show TCP 3-way handshake completing
- [ ] No checksum errors in interface statistics
- [ ] Consistent port numbers in OVS and OVN

## Risk Mitigation
1. **Backup Current State**: Save working ICMP/UDP configuration
2. **Incremental Testing**: Test after each change
3. **Fallback Option**: Switch to kernel datapath if userspace can't be fixed

## Timeline
- Phase 1: 15 minutes (revert to known state)
- Phase 2: 20 minutes (fix port binding)
- Phase 3: 10 minutes (fix checksums)
- Phase 4: 10 minutes (network stack)
- Phase 5: 15 minutes (testing)
- **Total**: ~1 hour

## Alternative Quick Fix
If the above doesn't work, switch to kernel datapath:
```bash
ovs-vsctl set bridge br-int datapath_type=system
```
This bypasses all userspace datapath issues but may have different performance characteristics.