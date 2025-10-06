<!-- data/nginx/html/index.html -->
<!doctype html>
<html>
<head><title>E-Series SANtricity Collector Stack Services</title></head>
<body>
  <h1>Service Directory</h1>
  <ul>
    <li><a href="https://$PROXY_HOST:$PROXY_EXPLORER_PORT">InfluxDB Explorer</a> (InfluxDB Bearer Token required; use https://$INFLUXDB_HOST:$INFLUXDB_PORT to connect)</li>
    <li><a href="https://$PROXY_HOST:$PROXY_GRAFANA_PORT">Grafana 12</a> (configured Grafana credentials or API Key required)</li>
    <li>https://$PROXY_HOST:$PROXY_INFLUXDB_PORT - InfluxDB 3 API endpoint (InfluxDB Bearer Token required)</li>
    <li>https://$PROXY_HOST:$PROXY_PROMETHEUS_PORT - Prometheus exporter (if enabled in nginx.conf and Collector) - no authentication</li>
  </ul>
</body>
</html>
