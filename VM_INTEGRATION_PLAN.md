# Libvirt VM Integration Implementation Plan

## Overview
Add KVM/QEMU virtual machines to the OVS Container Lab, with one VM in each VPC (VPC-A and VPC-B). VMs will connect to OVS via tap interfaces and be managed through libvirt, demonstrating hybrid container/VM SDN environments.

## Requirements
- [ ] Lima VM with KVM support enabled
- [ ] Libvirt/QEMU installed in Lima VM
- [ ] Lightweight VM images (Alpine/Cirros)
- [ ] OVS/OVN integration for VM networking
- [ ] `make vpc-vms` command for easy deployment

## Architecture

### VM Specifications
- **vpc-a-vm**: 10.0.5.10/24 (VPC-A VM subnet)
- **vpc-b-vm**: 10.1.5.10/24 (VPC-B VM subnet)
- **Resources**: 512MB RAM, 1 vCPU per VM
- **Networking**: TAP interfaces connected to br-int
- **Base OS**: Alpine Linux or Cirros

### Network Topology Addition
```
VPC-A (10.0.0.0/16)
└── ls-vpc-a-vm (10.0.5.0/24) - VMs [NEW]

VPC-B (10.1.0.0/16)
└── ls-vpc-b-vm (10.1.5.0/24) - VMs [NEW]
```

## Implementation Steps

### Phase 1: Environment Preparation
- [x] Install KVM/QEMU/libvirt packages in Lima VM setup
- [x] Enable nested virtualization in Lima config
- [x] Create vm-manager directory structure
- [x] Update Lima VM configuration for KVM

**Files modified:**
- `lima.yaml` - Added KVM/libvirt packages and nestedVirtualization flag

### Phase 2: VM Image Preparation
- [ ] Download or create minimal Alpine Linux image
- [ ] Prepare cloud-init configuration templates
- [ ] Install required packages (ntttcp, network tools)
- [ ] Create base image with proper configuration

**Files to create:**
- `vm-manager/images/alpine-base.qcow2`
- `vm-manager/cloud-init/user-data.yaml`
- `vm-manager/cloud-init/network-config.yaml`

### Phase 3: VM Manager Implementation
- [x] Create VMManager class in Python
- [x] Implement create_vm() method
- [x] Implement destroy_vm() method
- [x] Add OVS/OVN integration for TAP interfaces
- [x] Handle VM lifecycle (start/stop/status)

**Files created:**
- `vm-manager/vm_manager.py` - Full VM management implementation
- `vm-manager/__init__.py` - Module initialization

### Phase 4: OVS/OVN Network Integration
- [x] Create TAP interfaces for VMs (handled in vm_manager.py)
- [x] Add TAP interfaces to br-int with VLAN tags (handled in vm_manager.py)
- [x] Register VM ports with OVN (handled in vm_manager.py)
- [x] Configure port security and MAC bindings (handled in vm_manager.py)
- [x] Add new logical switches (ls-vpc-a-vm, ls-vpc-b-vm)

**Files modified:**
- `docker-compose.yml` - Added vpc-a-vm-net and vpc-b-vm-net networks
- `orchestrator.py` - Added VM management commands

### Phase 5: Orchestrator Integration
- [x] Add create-vms command
- [x] Add destroy-vms command
- [x] Add vm-status command
- [x] Add vm-console command for debugging
- [x] Integrate with existing network setup flow

**Files modified:**
- `orchestrator.py` - Added all VM management commands

### Phase 6: Makefile Commands
- [x] Add `make vpc-vms` target
- [x] Add `make vpc-vms-status` target
- [x] Add `make vpc-vms-destroy` target
- [x] Add `make vpc-vms-console` target
- [x] Update `make help` documentation

**Files modified:**
- `Makefile` - Added all VM management targets

### Phase 7: Testing & Validation
- [ ] Test VM creation and startup
- [ ] Verify network connectivity (VM to container)
- [ ] Test cross-VPC routing (VM to VM)
- [ ] Validate OVN flow rules for VMs
- [ ] Performance testing with ntttcp
- [ ] Document troubleshooting steps

**Files to create:**
- `vm-manager/tests/test_connectivity.sh`

### Phase 8: Documentation
- [ ] Update README.md with VM features
- [ ] Add VM troubleshooting guide
- [ ] Document VM networking architecture
- [ ] Add examples of VM usage

**Files to modify:**
- `README.md`
- `docs/VM_NETWORKING.md` (create)

## Current Status

### Active Phase: Phase 7 - Testing & Validation
**Current Task**: Ready to test VM creation with `make vpc-vms`

### Completed Tasks:
- [x] Created implementation plan
- [x] Phase 1: Environment Preparation (Lima VM with libvirt)
- [x] Phase 3: VM Manager Implementation (complete Python module)
- [x] Phase 4: OVS/OVN Network Integration (TAP interfaces and OVN config)
- [x] Phase 5: Orchestrator Integration (all commands added)
- [x] Phase 6: Makefile Commands (all targets added)

### Next Steps:
1. Recreate Lima VM with libvirt support: `make clean && make up`
2. Test VM creation: `make vpc-vms`
3. Verify connectivity between VMs and containers
4. Document any issues and fixes

## Testing Checklist

### Basic Connectivity Tests
- [ ] VM boots successfully
- [ ] VM gets correct IP address
- [ ] VM can ping gateway
- [ ] VM can ping containers in same VPC
- [ ] VM can ping VM in other VPC
- [ ] VM can reach internet via NAT

### SDN Integration Tests
- [ ] TAP interface appears in OVS
- [ ] Correct VLAN tag applied
- [ ] OVN logical port created
- [ ] Port security enforced
- [ ] Traffic flows visible in OVN

### Performance Tests
- [ ] ntttcp between VMs
- [ ] ntttcp VM to container
- [ ] Compare with container-to-container baseline

## Known Issues & Considerations

1. **Nested Virtualization**: Must be enabled in Lima VM
2. **Resource Constraints**: Keep VMs minimal to avoid resource exhaustion
3. **Storage**: Use thin-provisioned qcow2 images
4. **Networking**: TAP interfaces need proper MTU settings
5. **Security**: VMs need proper isolation via OVN ACLs

## Commands Reference

```bash
# Create VMs
make vpc-vms

# Check VM status
make vpc-vms-status

# Connect to VM console
make vpc-vms-console VM=vpc-a-vm

# Destroy VMs
make vpc-vms-destroy
```

## Architecture Diagram

```
┌─────────────────────────────────────────────────────┐
│                    Lima VM Host                      │
├─────────────────────────────────────────────────────┤
│                                                      │
│  ┌──────────────┐        ┌──────────────┐          │
│  │   vpc-a-vm   │        │   vpc-b-vm   │          │
│  │  10.0.5.10   │        │  10.1.5.10   │          │
│  └──────┬───────┘        └──────┬───────┘          │
│         │ TAP                   │ TAP              │
│         │                       │                  │
│  ┌──────┴───────────────────────┴────────┐        │
│  │          OVS br-int                    │        │
│  │      VLAN 105          VLAN 205        │        │
│  └────────────────┬────────────────────────┘        │
│                   │                                 │
│  ┌────────────────┴────────────────────────┐       │
│  │            OVN Control Plane            │       │
│  │   ls-vpc-a-vm       ls-vpc-b-vm        │       │
│  └──────────────────────────────────────────┘       │
└──────────────────────────────────────────────────────┘
```