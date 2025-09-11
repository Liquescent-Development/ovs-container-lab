FROM ubuntu:24.04

# Avoid interactive prompts during package installation
ENV DEBIAN_FRONTEND=noninteractive

# Update, upgrade and install required packages including OVS client tools
RUN apt-get update && apt-get upgrade -y && apt-get install -y \
    ca-certificates \
    wget \
    tar \
    openvswitch-common \
    && rm -rf /var/lib/apt/lists/*

# Download and install OVS exporter
RUN wget https://github.com/greenpau/ovs_exporter/releases/download/v1.0.7/ovs-exporter_1.0.7_linux_amd64.tar.gz \
    && tar -xzf ovs-exporter_1.0.7_linux_amd64.tar.gz \
    && mv ovs-exporter /usr/local/bin/ \
    && chmod +x /usr/local/bin/ovs-exporter \
    && rm ovs-exporter_1.0.7_linux_amd64.tar.gz

# Create a non-root user (though we'll run as root for OVS access)
RUN useradd -r -s /bin/false ovs

EXPOSE 9475

USER root

# Run OVS exporter with correct flag syntax (using single dash and dots)
CMD ["/usr/local/bin/ovs-exporter", \
     "-web.listen-address=:9475", \
     "-web.telemetry-path=/metrics", \
     "-system.run.dir=/var/run/openvswitch", \
     "-database.vswitch.name=Open_vSwitch", \
     "-database.vswitch.socket.remote=unix:/var/run/openvswitch/db.sock", \
     "-database.vswitch.file.data.path=/etc/openvswitch/conf.db", \
     "-log.level=info"]
