FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Update and upgrade to get the latest packages, then install Open vSwitch and networking tools
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    openvswitch-switch \
    openvswitch-common \
    iproute2 \
    net-tools \
    util-linux \
    procps \
    kmod \
    iptables \
    && rm -rf /var/lib/apt/lists/*

# Create startup script and health check
COPY start-ovs.sh /start-ovs.sh
COPY healthcheck.sh /healthcheck.sh
RUN chmod +x /start-ovs.sh /healthcheck.sh

# OVS needs these directories
VOLUME ["/var/run/openvswitch", "/var/lib/openvswitch", "/etc/openvswitch"]

# Health check that works on all platforms
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD /healthcheck.sh || exit 1

CMD ["/start-ovs.sh"]