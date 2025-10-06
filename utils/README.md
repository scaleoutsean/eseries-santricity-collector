# InfluxDB CLI and API

## CLI

From within the `utils` container where host (and token) should be pre-configured:

```sh
influxdb3 show databases
influxdb3 query --database "epa" "SHOW TABLES"
influxdb3 query --database "epa" "SHOW COLUMNS IN config_volumes"
influxdb3 query --database "epa" "SELECT * FROM config_interfaces LIMIT 1"
# select volumes with 'ddp' in their name
influxdb3 query --language influxql --database 'epa'  "SELECT * FROM config_volumes WHERE label =~ /ddp/ LIMIT 1"
# show tags names from volume configuration table
docker compose exec -it utils bash -c '/home/influx/.influxdb/influxdb3 query -H https://influxdb:8181 --token `cat /home/influx/epa.token` --language sql --database epa "SELECT key, data_type FROM system.influxdb_schema WHERE measurement = '\''config_volumes'\'' AND data_type = '\''tag'\''"'
# show not tags from volume configuration table
docker compose exec -it utils bash -c '/home/influx/.influxdb/influxdb3 query -H https://influxdb:8181 --token `cat /home/influx/epa.token` --language sql --database epa "SELECT key, data_type FROM system.influxdb_schema WHERE measurement = '\''config_volumes'\'' AND data_type != '\''tag'\''"'
docker compose exec -it utils bash -c '/home/influx/.influxdb/influxdb3 query -H https://influxdb:8181 --token `cat /home/influx/epa.token` --language sql --database epa "SHOW COLUMNS FROM config_volumes"'
```

InfluxQL can be used to get fields and tags. Within the `utils` container, `--token` and `--host` shouldn't be necessary as they're set in environment variables.

```sh
AUTH_TOKEN=`cat /home/influx/epa.token`
DATABASE_NAME="epa"
influxdb3 query --language influxql --database $DATABASE_NAME --token $AUTH_TOKEN "SHOW MEASUREMENTS"
influxdb3 query --language influxql --database $DATABASE_NAME --token $AUTH_TOKEN "SHOW FIELD KEYS FROM config_volumes"
influxdb3 query --language influxql --database $DATABASE_NAME --token $AUTH_TOKEN "SHOW TAG KEYS FROM config_volumes"
influxdb3 query --language influxql --database $DATABASE_NAME --token $AUTH_TOKEN "SHOW TAG KEYS WHERE pool_id = 'ZFS'"
```

From the host, using the `utils` container, InfluxQL and database `epa`:

```sh
docker compose exec -it utils bash -c \
'/home/influx/.influxdb/influxdb3 query -H https://influxdb:8181 --token `cat /home/influx/epa.token` --language influxql --database epa "SHOW MEASUREMENTS"'
```

Or:

```sh
docker compose exec -it utils bash -c '/home/influx/.influxdb/influxdb3 query -H https://influxdb:8181 --token `cat /home/influx/epa.token` --language influxql  --database epa "SHOW MEASUREMENTS"'
```

Delete `epa` database from the host using the `utils` container:

```sh
docker compose exec -it influxdb bash -c '/home/influx/.influxdb/influxdb3 delete database epa -H https://influxdb:8181 --token `cat /home/influx/tokens/epa.token`'
```

## HTTP API

This won't work verbatim if the InfluxDB TLS certificate used by InfluxDB wasn't issued for `influxdb` (host name mismatch).

```sh
HEADER="Authorization: Bearer `cat /home/influx/epa.token`"
curl --cacert /home/influx/certs/ca.crt --get https://influxdb:8181/api/v3/query_sql  --header "${HEADER}" --data-urlencode "db=epa" --data-urlencode "q=SELECT * FROM config_volumes LIMIT 2"
```

## Documentation

- [Query InfluxDB 3 data in SQL](https://docs.influxdata.com/influxdb3/core/query-data/sql/)
