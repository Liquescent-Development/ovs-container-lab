FROM ubuntu:22.04

RUN apt-get update && apt-get install -y \
    iperf3 \
    netperf \
    hping3 \
    nmap \
    tcpreplay \
    python3-scapy \
    curl \
    wget \
    net-tools \
    iputils-ping \
    && rm -rf /var/lib/apt/lists/*

# Add traffic generation script
COPY traffic-gen.py /traffic-gen.py
RUN chmod +x /traffic-gen.py

CMD ["/bin/bash"]