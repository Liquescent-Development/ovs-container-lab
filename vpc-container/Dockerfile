FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install all necessary network tools
RUN apt-get update && apt-get install -y \
    # Basic networking
    iproute2 \
    iputils-ping \
    net-tools \
    # Traffic testing
    netcat-openbsd \
    curl \
    wget \
    tcpdump \
    # DNS tools
    dnsutils \
    # Process management
    htop \
    procps \
    # Debugging
    strace \
    # Build tools for ntttcp
    git \
    gcc \
    make \
    && rm -rf /var/lib/apt/lists/*

# Build and install ntttcp
RUN cd /tmp && \
    git clone https://github.com/microsoft/ntttcp-for-linux.git && \
    cd ntttcp-for-linux/src && \
    make && \
    cp ntttcp /usr/local/bin/ && \
    cd / && \
    rm -rf /tmp/ntttcp-for-linux

# Create entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]