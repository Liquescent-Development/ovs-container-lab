#!/usr/bin/env python3
"""
High-performance traffic generator using Scapy
Generates various types of traffic to stress test OVS
"""

import sys
import time
import random
import threading
from scapy.all import *

class TrafficGenerator:
    def __init__(self, targets, interface='eth1'):
        self.targets = targets
        self.interface = interface
        self.running = True
        
    def generate_tcp_flood(self):
        """Generate TCP SYN flood traffic"""
        while self.running:
            for target in self.targets:
                # Random source port, multiple destination ports
                for dport in [80, 443, 8080, 22, 3306, 5432]:
                    pkt = IP(dst=target)/TCP(sport=RandShort(), dport=dport, flags="S")
                    send(pkt, verbose=0, iface=self.interface)
    
    def generate_udp_flood(self):
        """Generate UDP flood traffic"""
        while self.running:
            for target in self.targets:
                # Various packet sizes
                for size in [64, 256, 512, 1024, 1400]:
                    payload = Raw(RandString(size))
                    pkt = IP(dst=target)/UDP(sport=RandShort(), dport=RandShort())/payload
                    send(pkt, verbose=0, iface=self.interface)
    
    def generate_icmp_flood(self):
        """Generate ICMP flood traffic"""
        while self.running:
            for target in self.targets:
                # Various ICMP types
                pkt = IP(dst=target)/ICMP()
                send(pkt, verbose=0, iface=self.interface)
                
                # Large ICMP packet
                pkt = IP(dst=target)/ICMP()/Raw(RandString(1400))
                send(pkt, verbose=0, iface=self.interface)
    
    def generate_arp_flood(self):
        """Generate ARP requests"""
        while self.running:
            for target in self.targets:
                pkt = ARP(pdst=target)
                send(pkt, verbose=0, iface=self.interface)
                time.sleep(0.1)  # ARP less frequently
    
    def generate_fragmented_packets(self):
        """Generate fragmented packets"""
        while self.running:
            for target in self.targets:
                # Create large packet that will be fragmented
                payload = Raw(RandString(8000))
                pkt = IP(dst=target)/UDP(dport=9999)/payload
                send(pkt, verbose=0, iface=self.interface)
                time.sleep(0.5)  # Less frequent for fragments
    
    def generate_burst_traffic(self):
        """Generate traffic bursts"""
        while self.running:
            # Burst of 1000 packets
            target = random.choice(self.targets)
            pkts = []
            for _ in range(1000):
                pkt = IP(dst=target)/UDP(sport=RandShort(), dport=RandShort())
                pkts.append(pkt)
            sendp(pkts, verbose=0, iface=self.interface)
            time.sleep(2)  # Pause between bursts
    
    def start(self, threads=5):
        """Start traffic generation with multiple threads"""
        generators = [
            self.generate_tcp_flood,
            self.generate_udp_flood,
            self.generate_icmp_flood,
            self.generate_arp_flood,
            self.generate_fragmented_packets,
            self.generate_burst_traffic
        ]
        
        threads_list = []
        for i in range(threads):
            for gen_func in generators:
                t = threading.Thread(target=gen_func)
                t.daemon = True
                t.start()
                threads_list.append(t)
        
        print(f"Started {len(threads_list)} traffic generation threads")
        print("Generating traffic to:", self.targets)
        print("Press Ctrl+C to stop...")
        
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            print("\nStopping traffic generation...")
            self.running = False
            time.sleep(1)

if __name__ == "__main__":
    # Target IPs (other containers in OVS network)
    targets = ["172.18.0.10", "172.18.0.11", "172.18.0.12"]
    
    if len(sys.argv) > 1:
        targets = sys.argv[1:]
    
    gen = TrafficGenerator(targets)
    gen.start(threads=3)  # 3 threads per generator function = 18 total threads