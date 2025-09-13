FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Update and upgrade to get the latest packages, then install Open vSwitch, OVN, and networking tools
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    openvswitch-switch \
    openvswitch-common \
    ovn-host \
    ovn-common \
    iproute2 \
    net-tools \
    util-linux \
    procps \
    kmod \
    iptables \
    iputils-ping \
    lsb-release \
    ca-certificates \
    wget \
    tar \
    && rm -rf /var/lib/apt/lists/*

# Download and install OVS exporter
RUN wget https://github.com/Liquescent-Development/ovs_exporter/releases/download/v2.2.0/ovs-exporter-2.2.0.linux-arm64.tar.gz \
      && tar -xzf ovs-exporter-2.2.0.linux-arm64.tar.gz \
      && mv ovs-exporter-2.2.0.linux-arm64/ovs-exporter /usr/local/bin/ \
      && chmod +x /usr/local/bin/ovs-exporter \
      && rm -rf ovs-exporter-2.2.0.linux-arm64*

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