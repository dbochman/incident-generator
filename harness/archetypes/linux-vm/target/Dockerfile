FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
      bash \
      ca-certificates \
      coreutils \
      curl \
      iproute2 \
      lsof \
      procps \
      prometheus-node-exporter \
      sysstat \
      stress-ng \
      util-linux \
    && rm -rf /var/lib/apt/lists/*

COPY harness/archetypes/linux-vm/target/entrypoint.sh /usr/local/bin/sre-agent-linux-target-entrypoint.sh
COPY harness/shared/linux-faults.sh /sre-agent/harness/shared/linux-faults.sh
COPY scenarios/linux /sre-agent/scenarios/linux
RUN chmod +x /usr/local/bin/sre-agent-linux-target-entrypoint.sh
RUN find /sre-agent -name '*.sh' -exec chmod +x {} +

EXPOSE 9100
ENTRYPOINT ["/usr/local/bin/sre-agent-linux-target-entrypoint.sh"]
