#!/usr/bin/env python3
"""
Multi-VPC Traffic Generator for OVS/OVN Testing
Generates realistic inter-VPC and intra-VPC traffic patterns
"""

import sys
import time
import random
import threading
from scapy.all import *

class MultiVPCTrafficGenerator:
    def __init__(self, mode='standard'):
        # VPC-A workloads
        self.vpc_a_targets = {
            'web': '10.0.1.10',
            'app': '10.0.2.10',
            'db': '10.0.3.10'
        }
        
        # VPC-B workloads
        self.vpc_b_targets = {
            'web': '10.1.1.10',
            'app': '10.1.2.10',
            'db': '10.1.3.10'
        }
        
        self.all_targets = list(self.vpc_a_targets.values()) + list(self.vpc_b_targets.values())
        self.interface = 'eth1'
        self.running = True
        self.mode = mode
        self.stats = {'packets_sent': 0, 'bytes_sent': 0}
        
    def generate_intra_vpc_traffic(self, vpc='a'):
        """Generate realistic traffic within a VPC"""
        targets = self.vpc_a_targets if vpc == 'a' else self.vpc_b_targets
        
        while self.running:
            # Web tier to App tier (HTTP/HTTPS)
            pkt = IP(dst=targets['app'])/TCP(sport=RandShort(), dport=8080, flags="S")
            send(pkt, verbose=0, iface=self.interface)
            self.stats['packets_sent'] += 1
            
            # App tier to DB tier (Database traffic)
            for port in [3306, 5432]:  # MySQL, PostgreSQL
                pkt = IP(dst=targets['db'])/TCP(sport=RandShort(), dport=port, flags="S")
                send(pkt, verbose=0, iface=self.interface)
                self.stats['packets_sent'] += 1
            
            # Web tier responses
            pkt = IP(dst=targets['web'])/TCP(sport=80, dport=RandShort(), flags="A")
            send(pkt, verbose=0, iface=self.interface)
            self.stats['packets_sent'] += 1
            
            time.sleep(0.01 if self.mode == 'high' else 0.1)
    
    def generate_inter_vpc_traffic(self):
        """Generate traffic between VPCs"""
        while self.running:
            # VPC-A to VPC-B API calls
            pkt = IP(src=self.vpc_a_targets['app'], dst=self.vpc_b_targets['app'])/TCP(sport=RandShort(), dport=8080, flags="S")
            send(pkt, verbose=0, iface=self.interface)
            self.stats['packets_sent'] += 1
            
            # VPC-B to VPC-A responses
            pkt = IP(src=self.vpc_b_targets['app'], dst=self.vpc_a_targets['app'])/TCP(sport=8080, dport=RandShort(), flags="A")
            send(pkt, verbose=0, iface=self.interface)
            self.stats['packets_sent'] += 1
            
            # Cross-VPC web traffic
            pkt = IP(src=self.vpc_a_targets['web'], dst=self.vpc_b_targets['web'])/TCP(sport=RandShort(), dport=443, flags="S")
            send(pkt, verbose=0, iface=self.interface)
            self.stats['packets_sent'] += 1
            
            time.sleep(0.05 if self.mode == 'high' else 0.2)
    
    def generate_external_traffic(self):
        """Generate traffic to external destinations"""
        external_targets = ['8.8.8.8', '1.1.1.1', '208.67.222.222']
        
        while self.running:
            for vpc_targets in [self.vpc_a_targets, self.vpc_b_targets]:
                src = random.choice(list(vpc_targets.values()))
                dst = random.choice(external_targets)
                
                # DNS queries
                pkt = IP(src=src, dst=dst)/UDP(sport=RandShort(), dport=53)/DNS()
                send(pkt, verbose=0, iface=self.interface)
                self.stats['packets_sent'] += 1
                
                # HTTPS traffic
                pkt = IP(src=src, dst=dst)/TCP(sport=RandShort(), dport=443, flags="S")
                send(pkt, verbose=0, iface=self.interface)
                self.stats['packets_sent'] += 1
            
            time.sleep(0.1 if self.mode == 'high' else 0.5)
    
    def generate_load_test_traffic(self):
        """Generate high-volume traffic for load testing"""
        while self.running and self.mode in ['high', 'overload']:
            target = random.choice(self.all_targets)
            
            # Burst of packets
            burst_size = 100 if self.mode == 'high' else 500
            for _ in range(burst_size):
                pkt = IP(dst=target)/UDP(sport=RandShort(), dport=RandShort())/Raw(RandString(random.randint(64, 1400)))
                send(pkt, verbose=0, iface=self.interface)
                self.stats['packets_sent'] += 1
                self.stats['bytes_sent'] += len(pkt)
            
            time.sleep(0.1 if self.mode == 'high' else 0.01)
    
    def generate_malformed_traffic(self):
        """Generate malformed packets for testing error handling"""
        while self.running and self.mode == 'overload':
            target = random.choice(self.all_targets)
            
            # Fragmented packets
            payload = Raw(RandString(8000))
            pkt = IP(dst=target, flags="MF")/UDP(dport=9999)/payload
            send(pkt, verbose=0, iface=self.interface)
            
            # Invalid checksums
            pkt = IP(dst=target)/TCP(sport=RandShort(), dport=80, chksum=0xffff)
            send(pkt, verbose=0, iface=self.interface)
            
            # Tiny fragments
            pkt = IP(dst=target, flags="MF", frag=0)/Raw(RandString(8))
            send(pkt, verbose=0, iface=self.interface)
            
            time.sleep(0.5)
    
    def print_stats(self):
        """Print traffic generation statistics"""
        while self.running:
            time.sleep(5)
            print(f"Stats: {self.stats['packets_sent']} packets, {self.stats['bytes_sent']/1024/1024:.2f} MB sent")
    
    def start(self):
        """Start traffic generation based on mode"""
        print(f"Starting Multi-VPC Traffic Generator in {self.mode} mode")
        print(f"VPC-A targets: {list(self.vpc_a_targets.values())}")
        print(f"VPC-B targets: {list(self.vpc_b_targets.values())}")
        print("Press Ctrl+C to stop...")
        
        # Start generator threads
        threads = []
        
        # Intra-VPC traffic
        for vpc in ['a', 'b']:
            t = threading.Thread(target=lambda v=vpc: self.generate_intra_vpc_traffic(v))
            t.daemon = True
            t.start()
            threads.append(t)
        
        # Inter-VPC traffic
        t = threading.Thread(target=self.generate_inter_vpc_traffic)
        t.daemon = True
        t.start()
        threads.append(t)
        
        # External traffic
        t = threading.Thread(target=self.generate_external_traffic)
        t.daemon = True
        t.start()
        threads.append(t)
        
        # Load test traffic (if enabled)
        if self.mode in ['high', 'overload']:
            for _ in range(3):  # Multiple threads for load
                t = threading.Thread(target=self.generate_load_test_traffic)
                t.daemon = True
                t.start()
                threads.append(t)
        
        # Malformed traffic (if in overload mode)
        if self.mode == 'overload':
            t = threading.Thread(target=self.generate_malformed_traffic)
            t.daemon = True
            t.start()
            threads.append(t)
        
        # Stats printer
        t = threading.Thread(target=self.print_stats)
        t.daemon = True
        t.start()
        
        print(f"Started {len(threads)} traffic generation threads")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping traffic generation...")
            self.running = False
            time.sleep(1)
            print(f"Final stats: {self.stats['packets_sent']} packets, {self.stats['bytes_sent']/1024/1024:.2f} MB sent")

if __name__ == "__main__":
    mode = 'standard'
    if len(sys.argv) > 1:
        mode = sys.argv[1]
        if mode not in ['standard', 'high', 'overload']:
            print("Usage: python3 multi-vpc-traffic-gen.py [standard|high|overload]")
            sys.exit(1)
    
    gen = MultiVPCTrafficGenerator(mode=mode)
    gen.start()