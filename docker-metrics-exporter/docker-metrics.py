#!/usr/bin/env python3
import docker
import time
from http.server import HTTPServer, BaseHTTPRequestHandler
import json
import logging

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class MetricsHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Suppress default HTTP logs
        pass
        
    def do_GET(self):
        if self.path == '/metrics':
            try:
                self.send_response(200)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                
                client = docker.from_env()
                metrics = []
                
                # Get container metrics
                for container in client.containers.list():
                    try:
                        stats = container.stats(stream=False)
                        container_name = container.name
                        
                        # Skip monitoring containers to avoid recursion
                        if container_name in ['prometheus', 'node_exporter', 'ovs_exporter', 'docker_metrics']:
                            continue
                        
                        # Network metrics
                        if 'networks' in stats:
                            for network_name, network_stats in stats['networks'].items():
                                metrics.append(f'docker_network_rx_bytes{{container="{container_name}",network="{network_name}"}} {network_stats.get("rx_bytes", 0)}')
                                metrics.append(f'docker_network_tx_bytes{{container="{container_name}",network="{network_name}"}} {network_stats.get("tx_bytes", 0)}')
                                metrics.append(f'docker_network_rx_packets{{container="{container_name}",network="{network_name}"}} {network_stats.get("rx_packets", 0)}')
                                metrics.append(f'docker_network_tx_packets{{container="{container_name}",network="{network_name}"}} {network_stats.get("tx_packets", 0)}')
                        
                        # CPU metrics
                        cpu_percent = 0
                        if 'cpu_stats' in stats and 'precpu_stats' in stats:
                            cpu_delta = stats['cpu_stats']['cpu_usage']['total_usage'] - stats['precpu_stats']['cpu_usage']['total_usage']
                            system_delta = stats['cpu_stats']['system_cpu_usage'] - stats['precpu_stats']['system_cpu_usage']
                            if system_delta > 0 and cpu_delta > 0:
                                cpu_percent = (cpu_delta / system_delta) * len(stats['cpu_stats']['cpu_usage']['percpu_usage']) * 100.0
                        
                        metrics.append(f'docker_cpu_usage_percent{{container="{container_name}"}} {cpu_percent:.2f}')
                        
                        # Memory metrics
                        if 'memory_stats' in stats:
                            memory_usage = stats['memory_stats'].get('usage', 0)
                            memory_limit = stats['memory_stats'].get('limit', 0)
                            metrics.append(f'docker_memory_usage_bytes{{container="{container_name}"}} {memory_usage}')
                            metrics.append(f'docker_memory_limit_bytes{{container="{container_name}"}} {memory_limit}')
                            
                            # Memory usage percentage
                            if memory_limit > 0:
                                memory_percent = (memory_usage / memory_limit) * 100.0
                                metrics.append(f'docker_memory_usage_percent{{container="{container_name}"}} {memory_percent:.2f}')
                        
                        # Container status
                        metrics.append(f'docker_container_running{{container="{container_name}"}} 1')
                            
                    except Exception as e:
                        logger.error(f"Error getting stats for container {container.name}: {e}")
                        continue
                
                # Add metrics about total containers
                total_containers = len(client.containers.list())
                metrics.append(f'docker_containers_total {total_containers}')
                
                response = '\n'.join(metrics) + '\n'
                self.wfile.write(response.encode())
                
            except Exception as e:
                logger.error(f"Error in metrics handler: {e}")
                self.send_response(500)
                self.end_headers()
        else:
            self.send_response(404)
            self.end_headers()

if __name__ == '__main__':
    server = HTTPServer(('0.0.0.0', 8080), MetricsHandler)
    logger.info("Starting Docker metrics server on port 8080...")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down metrics server...")
        server.shutdown()
