    # Custom access log for all servers
    access_log  /nginx-logs/access.log;
    # Docker embedded DNS resolver for runtime hostname resolution
    resolver 127.0.0.11 valid=30s;

    # InfluxDB Explorer over HTTPS
    server {
        listen ${PROXY_EXPLORER_PORT} ssl default_server;
        server_name explorer_proxy; 
        ssl_protocols     TLSv1.3 TLSv1.2;
        ssl_prefer_server_ciphers on;
        ssl_ciphers       ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
        # ssl_ecdh_curve    X25519MLKEM768;
        ssl_certificate   /etc/nginx/ssl/tls.crt;
        ssl_certificate_key  /etc/nginx/ssl/tls.key;
        ssl_trusted_certificate /etc/nginx/ssl/combined_ca.crt;
        

        location / {
            # Use variable-based proxy_pass so nginx uses the resolver at
            # request time (useful in Docker where containers may start later)
            set $explorer_api "https://explorer:${EXPLORER_PORT}";
            proxy_pass $explorer_api;
            proxy_ssl_server_name   on;
            proxy_ssl_verify        on;
            proxy_ssl_trusted_certificate /etc/nginx/ssl/combined_ca.crt;
                # Preserve original Host header so upstream sees the external hostname
                proxy_set_header Host $$host;
                    proxy_set_header X-Forwarded-Host $$host;
            proxy_set_header X-Real-IP $$remote_addr;
               proxy_set_header X-Forwarded-For $$proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $$scheme;            
            # WebSocket support
            proxy_http_version 1.1;
            proxy_set_header Upgrade $$http_upgrade;
            proxy_set_header Connection "upgrade";
            
            # Timeouts and resiliency
            proxy_connect_timeout 5s;
            proxy_read_timeout 120s;
            proxy_next_upstream error timeout http_502 http_503 http_504;
        }
    }

    # Direct InfluxDB Proxy over HTTPS
    server {
        listen ${PROXY_INFLUXDB_PORT} ssl default_server;
        server_name influxdb_proxy;
        ssl_protocols     TLSv1.3 TLSv1.2;
        ssl_prefer_server_ciphers on;
        ssl_ciphers       ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
        # ssl_ecdh_curve    X25519MLKEM768;
        ssl_certificate      /etc/nginx/ssl/tls.crt;
        ssl_certificate_key  /etc/nginx/ssl/tls.key;
        ssl_trusted_certificate /etc/nginx/ssl/combined_ca.crt;

        location / {
            # Use a variable-based upstream so Docker DNS is consulted at request time
            # (keeps nginx tolerant to backend restarts). We still set proxy_ssl_name
            # to control SNI for certificate verification.
            set $influx_api "https://influxdb:${INFLUXDB_PORT}";
            proxy_pass $influx_api;
            proxy_ssl_server_name   on;
            # Explicitly set the upstream name used for SNI and certificate verification
            proxy_ssl_name "influxdb";
            proxy_ssl_verify        on;
            proxy_ssl_trusted_certificate /etc/nginx/ssl/combined_ca.crt;
            proxy_set_header        Host influxdb;
               proxy_set_header        X-Real-IP $$remote_addr;
            proxy_set_header        X-Forwarded-For $$proxy_add_x_forwarded_for;
               proxy_set_header        X-Forwarded-Proto $$scheme;

            # Timeouts
            proxy_connect_timeout   5s;
            proxy_read_timeout      120s;
            proxy_next_upstream error timeout http_502 http_503 http_504;
        }
    }

    # Reverse proxy for Grafana over HTTPS
    server {
        listen ${PROXY_GRAFANA_PORT} ssl;
        server_name grafana_proxy;
        ssl_protocols     TLSv1.3 TLSv1.2;
        ssl_prefer_server_ciphers on;
        ssl_ciphers       ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
        # ssl_ecdh_curve    X25519MLKEM768;
        ssl_certificate      /etc/nginx/ssl/tls.crt;
        ssl_certificate_key  /etc/nginx/ssl/tls.key;
        ssl_trusted_certificate /etc/nginx/ssl/combined_ca.crt;

        location / {
            # Proxy to Grafana container over HTTPS (Grafana serves HTTPS internally).
            # Use a variable so DNS is resolved at request time when Grafana starts later.
            set $grafana_api "https://grafana:${GRAFANA_PORT}";
            proxy_pass $grafana_api;
            proxy_ssl_server_name on;
            proxy_ssl_name "grafana";
            proxy_ssl_trusted_certificate /etc/nginx/ssl/combined_ca.crt;
            proxy_ssl_verify on;
            # Preserve original Host header so Grafana receives the external hostname
            proxy_set_header        Host $$host;
               proxy_set_header        X-Real-IP $$remote_addr;
            proxy_set_header        X-Forwarded-For $$proxy_add_x_forwarded_for;
            proxy_set_header        X-Forwarded-Proto $$scheme;

            # Support WebSocket (Grafana live / plugins) and keep HTTP/1.1
            proxy_http_version 1.1;
            proxy_set_header Upgrade $$http_upgrade;
            proxy_set_header Connection "upgrade";

            # Allow larger payloads (dashboard JSON uploads, etc.)
            client_max_body_size 50m;

            # Timeouts
            proxy_connect_timeout   5s;
            proxy_read_timeout      120s;
            proxy_next_upstream error timeout http_502 http_503 http_504;
        }
    } 
    # Prometheus metrics proxy (uncomment if external access needed for monitoring)
    # server {
    #     listen ${PROXY_PROMETHEUS_PORT} ssl;
    #     server_name collector_prom_proxy;
    #     ssl_protocols     TLSv1.3 TLSv1.2;
    #     ssl_prefer_server_ciphers on;
    #     ssl_ciphers       ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
    #     ssl_certificate      /etc/nginx/ssl/tls.crt;
    #     ssl_certificate_key  /etc/nginx/ssl/tls.key;
    #     ssl_trusted_certificate /etc/nginx/ssl/combined_ca.crt;
    #
    #     location / {
    #         # Proxy to collector container Prometheus metrics
    #         proxy_pass http://collector:${PROMETHEUS_PORT};
    #         proxy_set_header        Host $host;
    #         proxy_set_header        X-Real-IP $remote_addr;
    #         proxy_set_header        X-Forwarded-For $proxy_add_x_forwarded_for;
    #         proxy_set_header        X-Forwarded-Proto $scheme;
    #         # Timeouts
    #         proxy_connect_timeout   60s;
    #         proxy_read_timeout      300s;
    #     }
    # }

    server {
        listen ${PROXY_HTTP_PORT};
        server_name proxy;
        return 301 https://$host:${PROXY_HTTPS_PORT}$request_uri;

    }
    server {
        listen ${PROXY_HTTPS_PORT} ssl;
        # May need proper external name i.e. variable replacement for server name to match external TSL cert SAN; {{ proxy_host }}
        server_name _;
        ssl_protocols     TLSv1.3 TLSv1.2;
        ssl_prefer_server_ciphers on;
        ssl_ciphers       ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:ECDHE-ECDSA-CHACHA20-POLY1305:ECDHE-RSA-CHACHA20-POLY1305;
        # ssl_ecdh_curve    X25519MLKEM768;
        ssl_certificate     /etc/nginx/ssl/tls.crt;
        ssl_certificate_key /etc/nginx/ssl/tls.key;
        ssl_trusted_certificate /etc/nginx/ssl/combined_ca.crt;

        root /usr/share/nginx/html;
        index index.html;

        location / {
            try_files $uri $uri/ =404;
        }

    }
