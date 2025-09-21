# IMPORTANT: Must use Ubuntu 24.04 to match Lima VM for OVS/OVN version compatibility
FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Install OVS, OVN, and Python dependencies for Docker driver
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y \
    openvswitch-switch \
    openvswitch-common \
    ovn-central \
    ovn-host \
    ovn-common \
    python3 \
    python3-pip \
    python3-flask \
    python3-openvswitch \
    iproute2 \
    net-tools \
    util-linux \
    procps \
    iptables \
    tcpdump \
    curl \
    vim \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install OVN exporter v2.2.0 (includes logical router metrics)
# Download the appropriate binary for the architecture
# dpkg returns: amd64 or arm64, but release uses: x86_64 or arm64
RUN ARCH=$(dpkg --print-architecture | sed 's/amd64/x86_64/g') && \
    wget -O /tmp/ovn_exporter.tar.gz \
    https://github.com/Liquescent-Development/ovn_exporter/releases/download/v2.2.0/ovn-exporter_2.2.0_linux_${ARCH}.tar.gz && \
    tar -xzf /tmp/ovn_exporter.tar.gz -C /usr/local/bin/ && \
    rm /tmp/ovn_exporter.tar.gz && \
    chmod +x /usr/local/bin/ovn-exporter

# Copy startup script
COPY start-ovn.sh /start-ovn.sh
COPY healthcheck.sh /healthcheck.sh
RUN chmod +x /start-ovn.sh /healthcheck.sh

# Expose OVN ports
# 6641 - OVN Northbound DB
# 6642 - OVN Southbound DB
# 6081 - OVS DB
# 9476 - OVN Exporter metrics
EXPOSE 6641 6642 6081 9476

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD /healthcheck.sh

CMD ["/start-ovn.sh"]