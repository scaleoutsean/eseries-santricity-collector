# Getting Started with E-Series Performance Analyzer

- [Getting Started with E-Series Performance Analyzer](#getting-started-with-e-series-performance-analyzer)
  - [CLI](#cli)
  - [Docker](#docker)
    - [Step 1: Clone the repository and install requirements](#step-1-clone-the-repository-and-install-requirements)
    - [Step 2: Generate or get TLS certificates](#step-2-generate-or-get-tls-certificates)
    - [Step 3: Set Up Configuration Files](#step-3-set-up-configuration-files)
    - [Step 4: Build and Launch the Application](#step-4-build-and-launch-the-application)
      - [How to use the override file for `docker-compose.yml`](#how-to-use-the-override-file-for-docker-composeyml)
    - [Step 5: Verify the setup](#step-5-verify-the-setup)
    - [Step 6: Explore data](#step-6-explore-data)
    - [Troubleshooting](#troubleshooting)

This guide will walk you through setting up and using the E-Series Performance Analyzer.

## CLI

```sh
git clone https://github.com/scaleoutsean/eseries-santricity-collector
cd eseries-santricity-collector
pyhon3 -m venv .venv
source .venv/bin/activate # use "deactivate" to GTHO
pip install -r collector/requirements.txt
```

If you plan on saving your data to InfluxDB, you'll need a server URL and API token to access it. The InfluxDB service packaged in the container requires a valid TLS certificate and can't use HTTP.

From the top directory, run Collector:

```sh
$ python3 -m collector -h
usage: __main__.py [-h] (--api API [API ...] | --fromJson FROMJSON) [--username USERNAME] [--password PASSWORD]
    [--tlsCa TLSCA] [--tlsValidation {strict,normal,none}] [--systemId SYSTEMID]
    [--output {influxdb,prometheus,both}] [--influxdbUrl INFLUXDBURL] [--influxdbDatabase INFLUXDBDATABASE] 
    [--influxdbToken INFLUXDBTOKEN] [--prometheus-port PROMETHEUS_PORT] [--intervalTime INTERVALTIME]
    [--no-events] [--no-environmental] [--debug] [--log-level {DEBUG,INFO,WARNING,ERROR}] [--logfile LOGFILE] [--maxIterations MAXITERATIONS]

NetApp E-Series Performance Analyzer

options:
  -h, --help            show this help message and exit
  --api API [API ...]   List of E-Series API endpoints (IPv4 or IPv6 addresses or hostnames) to collect from
  --fromJson FROMJSON   Directory to replay previously collected JSON metrics instead of live collection
  --username USERNAME, -u USERNAME
                        Username for SANtricity API authentication
  --password PASSWORD, -p PASSWORD
                        Password for SANtricity API authentication
  --tlsCa TLSCA         Path to CA certificate for verifying API/InfluxDB TLS connections (if not in system trust store).
  --tlsValidation {strict,normal,none}
                        TLS validation mode for SANtricity API: strict (require valid CA and SKI/AKI), normal (default Python validation), none (disable all TLS validation, INSECURE, for testing only). Default: strict.
  --systemId SYSTEMID   Filter JSON replay to specific system ID (WWN). Only used with --fromJson

Output Configuration:
  --output {influxdb,prometheus,both}
                        Output format (default: influxdb)

InfluxDB Configuration:
  --influxdbUrl INFLUXDBURL
                        InfluxDB server URL. Example: https://proxy.example.com:18181
  --influxdbDatabase INFLUXDBDATABASE
                        InfluxDB database name
  --influxdbToken INFLUXDBTOKEN
                        InfluxDB authentication token

Prometheus Configuration:
  --prometheus-port PROMETHEUS_PORT
                        Prometheus metrics server port (default: 8000)

Collection Behavior:
  --intervalTime INTERVALTIME
                        Collection interval in seconds. Allowed values: [60, 128, 180, 300] (default: 60)
  --no-events           Disable event data collection
  --no-environmental    Disable environmental monitoring collection

Debugging:
  --debug               Enable debug logging
  --log-level {DEBUG,INFO,WARNING,ERROR}
                        Set logging level (default: INFO)
  --logfile LOGFILE     Path to log file (default: stdout only)
  --maxIterations MAXITERATIONS
                        Maximum collection iterations (0=unlimited, >0=exit after N iterations)

Examples:
  # Live API collection to InfluxDB
  python -m collector --api 192.168.1.101 192.168.1.102 --username monitor --password secret \
                      --influxdbUrl https://db.org.co:8181 --influxdbToken mytoken --influxDatabase epa \\
                      --intevalTime 60

  # JSON replay mode collection to InfluxDB
  python -m collector --fromJson ./data/samples/e4012 --systemId 6D039EA0004D00AA000000006652A086 \
                      --influxdbUrl https://proxy.org.co:18181 --influxdbToken mytoken --influxDatabase epa \\
                      --maxIterations 2

```

If you hate the thought of dealing with TLS troubles, check out EPA 3 which is much more forgiving.

## Docker

The main difference between running CLI and Docker Compose is Docker Compose has most of the stack ready for you.  

Use `.env` or `docker-compose.yml`  to configure Collector in Docker.

Note that you *can* run some Docker Compose services on one VM (or host) and others on another. For example, you could run Collector on one VM and InfluxDB on another. But in that case you would have to tell containers to use FQDN or external IP to connect to the remote service.

### Step 1: Clone the repository and install requirements

```sh
git clone https://github.com/scaleoutsean/eseries-santricity-collector
cd eseries-santricity-collector
```

### Step 2: Generate or get TLS certificates

**NOTE:** If you have own Certificate Authority (CA) you should just use your own to generate all certificates - both in-Docker, and "external" (the latter for the `proxy` container). Or, you could run this step to see what certificates are required and where to put them, and later replace them with your own.

This certificate generation script won't create certificates for SANtricity, as this uses self-signed CA which is unlikely better than what you already have.

```sh
$ ./certs/_master/gen_ca_tls_certs.py -h
usage: gen_ca_tls_certs.py [-h] [--service {all,proxy,s3,influxdb,grafana,explorer,influx-mcp,utils,ca}]

Generate CA and per-service TLS certificates.

options:
  -h, --help            show this help message and exit
  --service {all,proxy,s3,influxdb,grafana,explorer,influx-mcp,utils,ca}
                        Which certs to generate

```

This script will:

- Create a self-signed CA
- Generate certificates for all (specified) services
- Prepare the containers for secure communication 

Note that you can ignore the generated TLS certificates for E-Series controller(s) and you should probably do that if your have the proper CA in your environment. But if you use low-quality snake-oil TLS certificates, EPA containers won't trust those certificates without additional work on your side.

The other kind of TLS certificate you should get is "external" TSL (signed by your corporate CA, for example) your proxy service's LAN-facing address. Place a copy of CA, intermedia CA (if any), TLS and key in `./certs/proxy/external/` if you need it. This enables several scenarios, such as:

- Valid TLS on LAN-facing `proxy` for InfluxDB, InfluxDB Explorer and other proxied services
- Use of Docker-based InfluxDb from the host (by way of valid TLS proxy available to local host clients)
- Secure proxying of API requests to SANtricity (would require customization of `proxy` configuration)

### Step 3: Set Up Configuration Files

Create and edit `.env` and/or `docker-compose.yml`:

```sh
cp env.example .env
vim .env
vim docker-compose.yml
```

If you plan to use external proxy (this is the recommended production approach, but an override file is provided for convenience):

- Make sure `.env` has `PROXY_HOST`, `PROXY_INFLUXDB_PORT`, `PROXY_EXPLORER_PORT`, `PROXY_GRAFANA_PORT`, `PROXY_PROMETHEUS_PORT` and other externally-available services, so that Proxy knows which FQDN/hostname and ports to use
- Make a copy of **external** CA and certificate files in `./certs/proxy/external`:
  - `pub_ca.crt` (or `ca.crt` or `root_ca.crt`, just don't mix it up with in-Docker CA's certificate) - organization's CA (i.e. internal company CA used to issue LAN TLS certificate for the proxy)
  - `server.crt` - your external TLS certificate issued by `pub_ca.crt`
  - `private.key` - private key for `server.crt` (set this file's ownership or permissions as needed)
  - Additionally, we'll use existing in-docker CA generated earlier with `gen_ca_tls_certs.py`
- Create a simple "home page" for your proxy, and well as `nginx.conf` by running `./scripts/proxy_configuration.py`
  - This script also copies TLS certificates to the right places for an end-to-end HTTPS setup. See the script content for the details
- If you have host firewall set up, open `PROXY_*` ports to desired visitor IP addresses. You can also change `nginx.conf` to add basic authentication and whatnot (and then rebuild the `proxy` container)

If, for whatever reason, `proxy` won't be used, the simplest approach is to remove the `#`'s from `docker-compose.yml` and expose InfluxDB Explorer and/or Grafana to LAN (don't forget to unblock these ports on host firewall). You may need to directly expose InfluxDB as well, if you have Collector services running on LAN.

**NOTE**: TLS keys and InfluxDB tokens should be closely guarded. You can move them to a Vault, etc. ESC doesn't perform this step because many users who care about that need to do it in their own, very prescriptive way, while what ESC does do is common to almost everyone. Also, in the unlikely case that this isn't how you do things, you can send Collector container data to own InfluxDB infrastructure or just scrape it (for Prometheus) through a secure proxy.

### Step 4: Build and Launch the Application

There are two Docker Compose files:

- Production-targeting docker-compose.yml
- Testing-targeting dev-docker-compose.override.yml

The latter (override file) enables host (and LAN, if firewall allows) access to `influxdb` and `explorer` without `proxy`. 

The following steps assume `proxy` is used. If you want to use the override, see further below. 

First, note that InfluxDB and Grafana require specific UID:GID. You can do this manually or with this script. Do **not** run this script from VS Code terminal window because `sudo` access is likely disabled. Do **not** use `sudo` to run: the script will use it when/if necessary.

```sh
./scripts/fix_directory_ownership.sh
```

The other thing we need to ensure is that our `proxy` service not only has complete and correct configuration in `.env` and `docker-compose.yml`, but that service configuration files reflect these settings.

```sh
./scripts/proxy_configuration.py
```

The script will tell you what it did and you can examine that output to learn what it does and how.

**NOTE:** if above two steps are missed, you'll have various problems. Examples: container services can't start, proxy not working. Generally the fix is to start from scratch (delete modified files from `./certs/` and `./data`) or debug issues on your own one by one.

Now we can build and start containers by specifying containers we want to build. Because all services either write to, or query, InfluxDB, it is always best to start that service first (especially the first time, as that's where database credentials required by other services are generated).

```sh
docker compose build influxdb collector grafana explorer proxy utils
docker compose up -d influxdb
docker compose logs influxdb
```

The main outcome of this step is this: two InfluxDB bearer tokens.

```sh
$ ll ./data/influxdb_tokens/
-rw-r--r--  1 sean sean   92 Oct  6 10:10 admin.token
-rw-r--r--  1 sean sean   92 Oct  6 10:10 epa.token
```

If InfluxDB works okay and you can see API tokens in `./certs/influxdb_tokens/`, you should be able to continue with Collector and other services. Use the `admin.token` for InfluxDB admin tasks. Collector will use the second token, `epa.token`.

Note that `influx-mcp` won't build without the source. You get get it with `./scripts/fetch-external.sh` and then `docker compose build influx-mcp` can build it for you. That may be useful for development, but normally we'd run MCP server elsewhere, so there's no automated download, build or proxying for `influx-mcp`.

```sh
docker compose up -d collector # run without -d for easier troubleshooting until you get .env and docker-compose.yml right
```

**NOTE:** For many users Collector will fail due to snake-oil TLS certificates on their SANtricity controllers. Fix those by getting and deploying valid TLS certificates from your org CA, but you can loosen validation for those if you want to.

Now you can start Grafana and/or Explorer, or skip this step and enable `proxy` and use own Grafana and Proxy on LAN.

```sh
docker compose up -d explorer  # won't be externally reachable without an override or functioning proxy service
docker compose pull grafana    # to avoid annoying "Warning pull access denied for epa4/grafana, repository does not exist.."
docker compose up -d grafana   # Grafana with built-in in-Docker CA
```

Assuming you want to use `proxy` and have prepared the TLS files and other configuration in previous step (Step 3), run this service and check if you can connect to InfluxDB Explorer or Grafana using external ports you configured.

```sh
docker compose up -d proxy
```

Proxy can't work if you haven't run the proxy configuration script or have missing or wrong data in `.env`.

If you need the utilities container as a zero-setup client for InfluxDB:

```sh
docker compose up -d utils
docker exec -it utils bash
```

To view network ports consumed by container services:

```sh
docker compose ps
```

Any ports you wouldn't want to expose should be blocked by your host's firewall, or modified in `docker-compose.yml` (especially in `proxy` service) to hide them. The `proxy` service exists for the purpose of shielding and securing Docker services from LAN clients. If you don't use `proxy`, consider using own proxy for that purpose rather than docker compose override.

#### How to use the override file for `docker-compose.yml`

The override file need to be named the same as main file (`docker-compose` + `.override` + `.yml`) file, so move or copy it to shadow the main file. 

```sh
cp dev-docker-compose.override.yml docker-compose.override.yml
docker compose stop 
docker compose up -d
```

Even then you may explicitly start without the override with `-f`:

```sh
docker compose -f docker-compose.yml up -d
```

Delete `docker-compose.override.yml` if you no longer need it and then `docker compose up` will pick the main `docker-compose.yml` without explicit naming.

### Step 5: Verify the setup

Check that all services are running properly:

```bash
docker compose ps
```

Note that, if you use `proxy` as expected, you may see that some containers have services "exposed" but they're actually not available to LAN users. They're exposed in containers and to `proxy` service, but not on Docker public networks because `ports` are disabled. You can confirm this by checking the reachability from LAN.

How to validate InfluxDB from the `utils` container: you can run some queries from the `utils` container or explore from UI clients (next step).

```sh
docker exec -it proxy utils
```

### Step 6: Explore data

Once the system has collected data for a few minutes, you can run queries in the utils container, InfluxDB Explorer or start dashboarding in Grafana.

From **InfluxDB Explorer**:

- with Explorer and InfluxDB in same Docker Compose stack, add InfluxDB connection using http**s**://influxdb:8181 (that is, use the Docker-internal name, whether you're using Proxy or not)
- select your database (`epa` or what you set configured) from the database drop-down list in Explorer and if Collector has worked, you can run a query such as `SELECT * FROM CONFIG_HOSTS` or simply select a table and fields in the UI
- InfluxDB Explorer runs in admin mode, which you can override in `docker-compose.yml`. Admin mode enables - assuming your API token has such authorization - database administration as well as regular DB client use. Non-admin mode (`mode=query`) only allows authorized users to use the DB. See the Explorer documentation [here](https://docs.influxdata.com/influxdb3/explorer/install/#choose-operational-mode).

From **the CLI**:

- download and use InfluxDB CLI with environment variables or arguments to query InfluxDB and show tables with `SHOW MEASUREMENTS`, but you'll need to have `proxy` enabled to expose InfluxDB on `https://PROXY_HOST:18181` and an API token ready
- locally within Docker Compose environment you may use the pre-configured `utils` container for this. Simply start it and then enter it with `docker exec -it utils bash`. Inside the container, run `cat README.md` or work by prompt instructions
- extenal InfluxDB 3 clients accessing through the proxy may need to specify organizational CA with `--tls-ca` even if client system has that certificate in OS trust store (as of 3.5.0, InfluxDB3 client doesn't use that automatically)

From **Grafana**: 

- add InfluxDB Data Source: 
  - if both Grafana and InfluxDB run in same Docker Compose, use https://influxdb:8181, if not, use host's FQDN, such as https://proxy.corp.internal:18181 (assuming your Proxy service is up and running)
  - use `SQL` language dialect for InfluxDB 3  
  - paste your in-Docker CA certificate so that Grafana can validate InfluxDB's TLS certificate was issued by in-Docker CA
  - if Grafana cannot connect to InfluxDB via HTTPS, see [DOCUMENTATION](./DOCUMENTATION.md) for additional details about this
- you will need InfluxDB API token to access the DB. Paste the token near the bottom, just below database name (default: `epa`)

### Troubleshooting

- Check container logs: `docker compose logs collector` (or other EPA service name from `docker ps`). If you are in `DEBUG` logging mode, you can log to a file on the host and use the `tail` command. Also InfluxDB and Prometheus data will be dumped to the same directory
- Ensure in-Docker certificates were generated correctly in `./certs/` before containers were built
- Ensure proxy service has certificates valid for LAN clients in `./certs/proxy/external/` before you build `proxy`
- If permissions on docker data directories are making containers unable to start, fix them with `sudo chown -R` - see `scripts/fix_data_dir_ownership.sh`
- If the `proxy` doesn't work, you've probably missed to provide complete details in `.env`, or did not run `./scripts/proxy_configuration.py` before building and starting `proxy`

How to debug containerized Collector:

- Make sure the container has a volume mount for "out" data (your debug logs)
- Set Collector's log level to `DEBUG` in `docker-compose.yaml`
- Also in Collector service, set log path to your "out" directory inside of the container
- Change `controller` service's restart setting to `no` and set `MAX_ITERATIONS` to `1`
- Now run with `docker compose up -d collector` and seconds later you should be able to view logs from Collector, as well as debug dumps from InfluxDB and Prometheus Exporter in your "out" directory
- To return to production, revert these changes and restart Collector
