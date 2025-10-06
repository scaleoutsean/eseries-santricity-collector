FROM grafana/grafana:12.2

# Copy internal CA into system trust store and update
COPY certs/_master/ca.crt /usr/local/share/ca-certificates/epa_ca.crt
RUN update-ca-certificates || true

# Keep using the upstream entrypoint
ENTRYPOINT ["/run.sh"]
