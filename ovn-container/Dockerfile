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

# Download the driver from OVN v25.09.0
# The .in file is a template, we need to:
# 1. Replace @PYTHON3@ with the actual path
# 2. Fix the Python 3 bytes/string compatibility issue that exists in upstream
RUN wget -O /usr/local/bin/ovn-docker-overlay-driver \
    https://raw.githubusercontent.com/ovn-org/ovn/v25.09.0/utilities/ovn-docker-overlay-driver.in \
    && sed -i 's|#! @PYTHON3@|#!/usr/bin/python3|' /usr/local/bin/ovn-docker-overlay-driver \
    && sed -i 's/output = output\[0\]\.strip()/output = output[0].decode("utf-8").strip() if isinstance(output[0], bytes) else output[0].strip()/' /usr/local/bin/ovn-docker-overlay-driver \
    && chmod +x /usr/local/bin/ovn-docker-overlay-driver

# Copy startup script
COPY start-ovn.sh /start-ovn.sh
COPY healthcheck.sh /healthcheck.sh
RUN chmod +x /start-ovn.sh /healthcheck.sh

# Expose OVN ports
# 6641 - OVN Northbound DB
# 6642 - OVN Southbound DB
# 6081 - OVS DB
EXPOSE 6641 6642 6081

# Health check
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD /healthcheck.sh

CMD ["/start-ovn.sh"]