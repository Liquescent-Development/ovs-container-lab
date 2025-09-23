FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

# Install all the heavy-duty network testing tools
RUN apt-get update && apt-get install -y \
    # Basic utilities
    iproute2 \
    iputils-ping \
    netcat \
    curl \
    wget \
    tcpdump \
    net-tools \
    dnsutils \
    # Traffic generators
    netperf \
    hping3 \
    nmap \
    tcpreplay \
    # Stress testing
    stress-ng \
    # Python and libraries
    python3 \
    python3-pip \
    python3-scapy \
    # Additional tools
    masscan \
    arping \
    fping \
    mtr \
    traceroute \
    socat \
    # Build tools for Python packages and ntttcp
    build-essential \
    libpcap-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Build and install ntttcp
RUN cd /tmp && \
    git clone https://github.com/microsoft/ntttcp-for-linux.git && \
    cd ntttcp-for-linux/src && \
    make && \
    cp ntttcp /usr/local/bin/ && \
    cd / && \
    rm -rf /tmp/ntttcp-for-linux

# Install Python packages for advanced packet crafting
RUN pip3 install \
    impacket \
    netaddr \
    faker

WORKDIR /workspace
COPY . /workspace/

# Make scripts executable
RUN chmod +x /workspace/*.py

CMD ["sleep", "infinity"]