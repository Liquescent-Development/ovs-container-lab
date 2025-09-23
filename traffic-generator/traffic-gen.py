#!/usr/bin/env python3
"""
Traffic Generator for OVS/OVN Multi-VPC Testing using ntttcp
Generates high-performance network traffic between VPC-A and VPC-B containers
Supports multiple intensity modes: standard, high, and chaos
Uses Microsoft's ntttcp for better concurrency and throughput
"""

import sys
import time
import random
import threading
import subprocess
import json
import signal
from collections import defaultdict
from datetime import datetime

class TrafficGenerator:
    def __init__(self, mode='standard'):
        # VPC targets with their actual listening services
        self.targets = [
            # VPC-A Web
            {'ip': '10.0.1.10', 'name': 'vpc-a-web', 'tier': 'web',
             'ports': {'tcp': [80, 443], 'ntttcp': 5001}},
            # VPC-A App
            {'ip': '10.0.2.10', 'name': 'vpc-a-app', 'tier': 'app',
             'ports': {'tcp': [8080, 8443], 'ntttcp': 5001}},
            # VPC-A DB
            {'ip': '10.0.3.10', 'name': 'vpc-a-db', 'tier': 'db',
             'ports': {'tcp': [5432, 3306]}},
            # VPC-B Web
            {'ip': '10.1.1.10', 'name': 'vpc-b-web', 'tier': 'web',
             'ports': {'tcp': [80, 443], 'ntttcp': 5001}},
            # VPC-B App
            {'ip': '10.1.2.10', 'name': 'vpc-b-app', 'tier': 'app',
             'ports': {'tcp': [8080, 8443], 'ntttcp': 5001}},
            # VPC-B DB
            {'ip': '10.1.3.10', 'name': 'vpc-b-db', 'tier': 'db',
             'ports': {'tcp': [5432, 3306]}}
        ]

        self.mode = mode
        self.running = True
        self.stats = defaultdict(int)
        self.start_time = time.time()

        # Rate limiting and resource control
        self.config = self.get_config(mode)

        # Track ongoing processes to prevent resource exhaustion
        self.active_processes = []
        self.process_lock = threading.Lock()

    def get_config(self, mode):
        """Get configuration with proper rate limiting"""
        configs = {
            'standard': {
                'threads': 4,
                'max_processes': 3,  # ntttcp handles concurrency internally
                'packets_per_second': 1000,
                'bandwidth_mbps': 100,  # 100 Mbps for standard
                'burst_size': 100,
                'delay_between_bursts': 0.05,
                'connection_limit': 20,
                'cpu_limit': 50,
            },
            'high': {
                'threads': 6,
                'max_processes': 5,  # ntttcp handles concurrency internally
                'packets_per_second': 5000,
                'bandwidth_mbps': 500,  # 500 Mbps for high
                'burst_size': 200,
                'delay_between_bursts': 0.02,
                'connection_limit': 40,
                'cpu_limit': 70,
            },
            'chaos': {
                'threads': 16,  # More threads for chaos
                'max_processes': 10,  # ntttcp handles concurrency internally
                'packets_per_second': 20000,  # Double the packet rate
                'bandwidth_mbps': 1000,  # 1 Gbps for chaos
                'burst_size': 1000,  # Larger burst sizes
                'delay_between_bursts': 0.005,  # Faster bursts
                'connection_limit': 100,  # More connections
                'cpu_limit': 90,
            }
        }
        return configs.get(mode, configs['standard'])

    def cleanup_process(self, proc):
        """Clean up finished processes"""
        with self.process_lock:
            if proc in self.active_processes:
                self.active_processes.remove(proc)

    def wait_for_slot(self):
        """Wait until there's a slot for a new process"""
        while len(self.active_processes) >= self.config['max_processes']:
            # Clean up finished processes
            with self.process_lock:
                self.active_processes = [p for p in self.active_processes if p.poll() is None]
            time.sleep(0.01)

    def controlled_ping(self, target_ip):
        """Send controlled ICMP traffic"""
        # Calculate interval for rate limiting
        interval = 1.0 / (self.config['packets_per_second'] / 10)  # Divide by 10 for ping share

        cmd = [
            'ping',
            '-i', str(interval),  # Interval between packets
            '-s', '64',  # Small packet size
            '-c', '10',  # Only 10 packets
            '-W', '1',  # 1 second timeout
            target_ip
        ]

        self.wait_for_slot()

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self.process_lock:
                self.active_processes.append(proc)

            proc.wait(timeout=5)
            self.stats['icmp_packets'] += 10
            self.stats['total_packets'] += 10

        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception as e:
            print(f"[PING] Error: {e}")
        finally:
            self.cleanup_process(proc)

    def controlled_tcp_test(self, target_info):
        """Send TCP traffic to actual listening services"""
        if 'tcp' not in target_info['ports']:
            return

        # Pick a random listening port from this target
        port = random.choice(target_info['ports']['tcp'])

        # Generate realistic payload sizes based on tier
        if target_info['tier'] == 'web':
            # Web traffic: smaller payloads (HTTP requests)
            data_size = random.randint(100, 2000)
        elif target_info['tier'] == 'app':
            # App traffic: medium payloads (API calls)
            data_size = random.randint(500, 5000)
        else:  # db
            # DB traffic: larger payloads (query results)
            data_size = random.randint(1000, 10000)

        # Use nc to send data to the listening service
        cmd = f"timeout 2 sh -c 'dd if=/dev/zero bs={data_size} count=1 2>/dev/null | nc -w 1 {target_info['ip']} {port}'"

        self.wait_for_slot()

        try:
            proc = subprocess.Popen(cmd, shell=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self.process_lock:
                self.active_processes.append(proc)

            proc.wait(timeout=3)
            self.stats['tcp_connections'] += 1
            self.stats['bytes_sent'] += data_size
            self.stats[f"{target_info['tier']}_connections"] += 1

        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception:
            pass
        finally:
            self.cleanup_process(proc)

    def controlled_udp_test(self, target_ip):
        """Send controlled UDP traffic"""
        # Use hping3 with specific rate limiting
        packets = min(100, self.config['burst_size'])

        # Calculate interval in microseconds for desired rate
        interval_us = int(1000000 / self.config['packets_per_second'])

        # Target random high ports for UDP
        port = random.randint(10000, 20000)

        cmd = [
            'hping3',
            '--udp',
            '-p', str(port),
            '-c', str(packets),  # Limited packet count
            '-i', f'u{interval_us}',  # Rate limiting
            '--data', '100',  # Small payload
            target_ip
        ]

        self.wait_for_slot()

        try:
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self.process_lock:
                self.active_processes.append(proc)

            proc.wait(timeout=5)
            self.stats['udp_packets'] += packets
            self.stats['total_packets'] += packets

        except subprocess.TimeoutExpired:
            proc.kill()
        except Exception:
            pass
        finally:
            self.cleanup_process(proc)

    def controlled_http_test(self, target_info):
        """Send realistic HTTP-like traffic to listening web/app services"""
        # Only test web and app tiers that have HTTP-like ports
        if target_info['tier'] not in ['web', 'app']:
            return

        ports = target_info['ports']['tcp']

        # Use hping3 for more powerful TCP testing to the actual listeners
        for port in ports:
            # Send TCP SYN followed by data
            cmd = [
                'hping3',
                '--tcp',
                '-p', str(port),
                '-c', '10',  # 10 packets
                '-i', 'u10000',  # 10ms interval
                '--data', '500',  # 500 bytes payload
                '-S',  # SYN flag
                target_info['ip']
            ]

            self.wait_for_slot()

            try:
                proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                with self.process_lock:
                    self.active_processes.append(proc)

                proc.wait(timeout=2)
                self.stats['http_requests'] += 10
                self.stats[f"{target_info['tier']}_requests"] += 10

            except:
                pass
            finally:
                self.cleanup_process(proc)

    def controlled_ntttcp_test(self, target_info):
        """Use ntttcp for high-performance network testing"""
        # ntttcp receiver listens on ports 5001-5016 by default
        if 'ntttcp' not in target_info['ports']:
            return

        # Determine number of threads based on mode
        if self.mode == 'chaos':
            threads = 16  # Maximum threads for chaos mode
        elif self.mode == 'high':
            threads = 8
        else:
            threads = 4

        # Build ntttcp command
        cmd = [
            'ntttcp',
            '-s', target_info['ip'],  # sender mode to target IP
            '-P', str(threads),  # number of parallel connections
            '-t', '60',  # run for 60 seconds then restart
            '-N',  # no sync, start immediately
        ]

        # Add UDP flag for some chaos connections
        if self.mode == 'chaos' and random.random() < 0.3:
            cmd.append('-u')
            protocol = 'UDP'
        else:
            protocol = 'TCP'

        self.wait_for_slot()

        try:
            # Run ntttcp in background
            proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            with self.process_lock:
                self.active_processes.append(proc)

            print(f"Started ntttcp {protocol} to {target_info['name']} ({target_info['ip']}) with {threads} threads")
            self.stats['ntttcp_sessions'] = self.stats.get('ntttcp_sessions', 0) + 1

        except Exception as e:
            print(f"Failed to start ntttcp to {target_info['name']}: {e}")
            if 'proc' in locals():
                self.cleanup_process(proc)

    def traffic_pattern_normal(self, target_info):
        """Normal traffic pattern - tier-appropriate realistic traffic"""

        # Choose traffic type based on target tier
        if target_info['tier'] == 'web':
            # Web tier gets more HTTP-like traffic and ntttcp
            methods = [
                (self.controlled_ping, 0.1),
                (self.controlled_tcp_test, 0.3),
                (self.controlled_http_test, 0.3),
                (self.controlled_ntttcp_test, 0.2),
                (self.controlled_udp_test, 0.1),
            ]
        elif target_info['tier'] == 'app':
            # App tier gets balanced traffic
            methods = [
                (self.controlled_ping, 0.1),
                (self.controlled_tcp_test, 0.3),
                (self.controlled_http_test, 0.2),
                (self.controlled_ntttcp_test, 0.2),
                (self.controlled_udp_test, 0.2),
            ]
        else:  # db tier
            # DB tier gets more TCP connections (simulating queries)
            methods = [
                (self.controlled_ping, 0.1),
                (self.controlled_tcp_test, 0.6),
                (self.controlled_udp_test, 0.3),
            ]

        # Choose method based on weights
        rand = random.random()
        cumulative = 0

        for method, weight in methods:
            cumulative += weight
            if rand <= cumulative:
                # Pass target_info to methods that need it
                if method in [self.controlled_tcp_test, self.controlled_http_test, self.controlled_ntttcp_test]:
                    method(target_info)
                else:
                    method(target_info['ip'])
                break

    def traffic_pattern_burst(self, targets):
        """Burst pattern - sudden spike targeting actual services"""
        print(f"[BURST] Generating traffic burst to {len(targets)} targets")

        threads = []
        for _ in range(min(self.config['burst_size'], 10)):  # Limit burst threads
            target = random.choice(targets)

            # For bursts, use the service most appropriate for the tier
            if 'ntttcp' in target['ports']:
                # Use ntttcp for bandwidth burst on web/app tiers
                t = threading.Thread(target=self.controlled_ntttcp_test, args=(target,))
            elif target['tier'] in ['web', 'app']:
                # Use HTTP-like traffic for web/app
                t = threading.Thread(target=self.controlled_http_test, args=(target,))
            else:
                # Use TCP for DB tier
                t = threading.Thread(target=self.controlled_tcp_test, args=(target,))

            t.start()
            threads.append(t)

        # Wait for burst to complete
        for t in threads:
            t.join(timeout=3)

        self.stats['bursts'] += 1

    def worker_thread(self, thread_id):
        """Worker thread for generating traffic"""
        print(f"[Thread-{thread_id}] Started")

        burst_counter = 0

        while self.running:
            try:
                # Normal traffic most of the time
                if burst_counter % 100 == 0 and self.mode in ['high', 'chaos']:
                    # Occasional burst
                    self.traffic_pattern_burst(self.targets)
                else:
                    # Normal traffic - pick a random target
                    target = random.choice(self.targets)
                    self.traffic_pattern_normal(target)

                burst_counter += 1

                # Rate limiting delay
                time.sleep(self.config['delay_between_bursts'])

            except Exception as e:
                print(f"[Thread-{thread_id}] Error: {e}")
                time.sleep(1)

    def print_stats(self):
        """Print statistics periodically"""
        while self.running:
            time.sleep(5)

            runtime = int(time.time() - self.start_time)

            print(f"\n{'='*60}")
            print(f"[STATS] Mode: {self.mode.upper()} | Runtime: {runtime}s")
            print(f"  Total Packets: {self.stats['total_packets']:,}")
            print(f"  ICMP: {self.stats['icmp_packets']:,} | UDP: {self.stats['udp_packets']:,}")
            print(f"  TCP Connections: {self.stats['tcp_connections']:,}")
            print(f"  HTTP-like Requests: {self.stats['http_requests']:,}")
            print(f"  Bytes Sent: {self.stats['bytes_sent']:,}")
            print(f"  ntttcp Sessions: {self.stats.get('ntttcp_sessions', 0):,}")
            print(f"  Web Tier Connections: {self.stats.get('web_connections', 0):,}")
            print(f"  App Tier Connections: {self.stats.get('app_connections', 0):,}")
            print(f"  DB Tier Connections: {self.stats.get('db_connections', 0):,}")
            print(f"  Bursts: {self.stats['bursts']:,}")
            print(f"  Active Processes: {len(self.active_processes)}/{self.config['max_processes']}")
            print('='*60)

    def signal_handler(self, signum, frame):
        """Handle shutdown gracefully"""
        print("\n[*] Shutting down gracefully...")
        self.running = False

        # Kill all active processes
        with self.process_lock:
            for proc in self.active_processes:
                try:
                    proc.kill()
                except:
                    pass

        sys.exit(0)

    def start(self):
        """Start the controlled traffic generator"""
        print(f"""
╔══════════════════════════════════════════════════════════╗
║          VPC TRAFFIC GENERATOR - {self.mode.upper():^10}           ║
╠══════════════════════════════════════════════════════════╣
║  Mode: {self.mode:^20}                      ║
║  Targets: 6 VPC containers with real services           ║
║  Threads: {self.config['threads']:^3} | Max Processes: {self.config['max_processes']:^3}           ║
║  Rate: {self.config['packets_per_second']:^5} pps | Bandwidth: {self.config['bandwidth_mbps']:^3} Mbps      ║
║  CPU Limit: {self.config['cpu_limit']:^3}%                              ║
╚══════════════════════════════════════════════════════════╝
        """)

        # Set up signal handlers
        signal.signal(signal.SIGINT, self.signal_handler)
        signal.signal(signal.SIGTERM, self.signal_handler)

        # Start stats printer
        stats_thread = threading.Thread(target=self.print_stats, daemon=True)
        stats_thread.start()

        # Start worker threads
        threads = []
        for i in range(self.config['threads']):
            t = threading.Thread(target=self.worker_thread, args=(i,))
            t.daemon = True
            t.start()
            threads.append(t)

        # Keep main thread alive
        try:
            while self.running:
                time.sleep(1)
        except KeyboardInterrupt:
            self.signal_handler(None, None)

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description='VPC Traffic Generator')
    parser.add_argument('mode', choices=['standard', 'high', 'chaos'],
                       default='standard', nargs='?',
                       help='Traffic generation mode')

    args = parser.parse_args()

    generator = TrafficGenerator(mode=args.mode)
    generator.start()