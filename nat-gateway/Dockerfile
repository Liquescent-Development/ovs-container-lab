FROM ubuntu:22.04

# Install FRR and networking tools
RUN apt-get update && apt-get install -y \
    frr \
    frr-pythontools \
    iptables \
    iproute2 \
    tcpdump \
    net-tools \
    iputils-ping \
    curl \
    vim \
    && rm -rf /var/lib/apt/lists/*

# Copy entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Enable all FRR daemons by default
RUN sed -i 's/=no/=yes/g' /etc/frr/daemons

ENTRYPOINT ["/entrypoint.sh"]