FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# Install OVS, OVN, and Python dependencies
RUN apt-get update && apt-get upgrade -y && \
    apt-get install -y \
    openvswitch-switch \
    openvswitch-common \
    ovn-host \
    python3 \
    python3-flask \
    python3-openvswitch \
    iproute2 \
    net-tools \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Download the fixed OVN Docker driver
RUN wget -O /usr/local/bin/ovn-docker-overlay-driver \
    https://raw.githubusercontent.com/ovn-org/ovn/v25.09.0/utilities/ovn-docker-overlay-driver.in \
    && sed -i 's|#! @PYTHON3@|#!/usr/bin/python3|' /usr/local/bin/ovn-docker-overlay-driver \
    && sed -i 's/output = output\[0\]\.strip()/output = output[0].decode("utf-8").strip() if isinstance(output[0], bytes) else output[0].strip()/' /usr/local/bin/ovn-docker-overlay-driver \
    && chmod +x /usr/local/bin/ovn-docker-overlay-driver

# Create plugin wrapper script
RUN echo '#!/bin/bash\n\
# Start OVS\n\
service openvswitch-switch start\n\
sleep 5\n\
\n\
# Configure OVS for OVN\n\
ovs-vsctl set open_vswitch . external_ids:ovn-bridge="br-int"\n\
ovs-vsctl set open_vswitch . external_ids:ovn-remote="$OVN_SB"\n\
ovs-vsctl set open_vswitch . external_ids:ovn-encap-type="geneve"\n\
ovs-vsctl set open_vswitch . external_ids:ovn-encap-ip="127.0.0.1"\n\
ovs-vsctl set open_vswitch . external_ids:ovn-nb="$OVN_NB"\n\
\n\
# Create integration bridge\n\
ovs-vsctl --may-exist add-br br-int -- set bridge br-int fail-mode=secure\n\
\n\
# Start the driver\n\
exec /usr/local/bin/ovn-docker-overlay-driver\n\
' > /entrypoint.sh && chmod +x /entrypoint.sh

CMD ["/entrypoint.sh"]