FROM ubuntu:24.04
ENV HOME=/home/influx
ENV PATH="/home/influx/.influxdb:${PATH}"
ENV INFLUXDB3_BUILD_VERSION=${INFLUXDB3_BUILD_VERSION:-3.4.0}
LABEL maintainer="@scaleoutSean"

# Install python and awscli
RUN apt-get update && \
    apt-get install -y curl python3 python3-pip ca-certificates wget build-essential git nginx-dev && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# create influx system user and group, and fix permissions
RUN groupadd --system influx || true && \
    useradd --system --home-dir /home/influx --shell /bin/bash --create-home --gid influx influx || true && \
    chown -R influx:influx /home/influx
# set home environment to ensure Bash uses correct .bashrc
ENV HOME=/home/influx

# Copy CLI and API command examples for online reference
# COPY README.md /home/influx/README.md

# copy entrypoint and set executable permissions as root
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Ensure any interactive bash shell loads InfluxDB env and alias
RUN git clone https://github.com/nginx/nginx nginx && cd nginx && \
    mkdir openssl && git clone -b openssl-3.6.0-beta1 https://github.com/openssl/openssl/ openssl && \
    cd openssl && ./Configure no-ssl3 enable-ktls enable-fips no-http && make -j 24 && cd .. && \
    ./auto/configure --with-openssl=./openssl/ --with-openssl-opt=enable-ktls --with-http_ssl_module && make -j 24 && ./objs/nginx -v && \
    echo "nginx version: $(./objs/nginx -v)" && cp ./objs/nginx /usr/sbin/nginx 

# Expose ports for HTTP and HTTPS
EXPOSE 443 8181 3000
RUN mkdir -p /usr/local/nginx/logs/ && touch /usr/local/nginx/logs/access.log && touch /usr/local/nginx/logs/error.log
# Switch to non-root and start entrypoint
USER influx
WORKDIR /home/influx
# ENTRYPOINT ["/entrypoint.sh"]
ENTRYPOINT ["/usr/sbin/nginx", "-g", "daemon off;"]

