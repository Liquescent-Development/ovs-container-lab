FROM alpine:latest

# Install all necessary network tools
RUN apk add --no-cache \
    # Basic networking
    iproute2 \
    iputils \
    net-tools \
    # Traffic testing
    iperf3 \
    netcat-openbsd \
    curl \
    wget \
    tcpdump \
    # DNS tools
    bind-tools \
    # Process management
    bash \
    htop \
    # Debugging
    strace \
    busybox-extras

# Create entrypoint script
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]