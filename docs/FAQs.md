# FAQs

- [FAQs](#faqs)
  - [E-Series SANtricity Collector](#e-series-santricity-collector)
    - [Why is this separate from E-Series Performance Analyzer?](#why-is-this-separate-from-e-series-performance-analyzer)
    - [Can I use this Collector without the rest of ESC stack?](#can-i-use-this-collector-without-the-rest-of-esc-stack)
  - [Databases and consolidation](#databases-and-consolidation)
    - [Why can't we have one EPA Collector all monitored arrays?](#why-cant-we-have-one-epa-collector-all-monitored-arrays)
    - [What kind of consolidation is possible or advisable?](#what-kind-of-consolidation-is-possible-or-advisable)
    - [Can the E-Series' system WWN and/or Name change?](#can-the-e-series-system-wwn-andor-name-change)
    - [Where's my InfluxDB data?](#wheres-my-influxdb-data)
    - [Why do I get `error mounting "/certs/influxdb/influxdb.crt" to rootfs` when I start `influxdb`](#why-do-i-get-error-mounting-certsinfluxdbinfluxdbcrt-to-rootfs-when-i-start-influxdb)
  - [Metrics, configurations, sensors and events](#metrics-configurations-sensors-and-events)
    - [What do temperature sensors measure?](#what-do-temperature-sensors-measure)
    - [Why are MEL (Major Event Log) records no longer collected?](#why-are-mel-major-event-log-records-no-longer-collected)
  - [Visualization and analytics](#visualization-and-analytics)
    - [Can ECS (EPA 4) use EPA 3 dashboards?](#can-ecs-epa-4-use-epa-3-dashboards)
    - [How do I customize Prometheus?](#how-do-i-customize-prometheus)
  - [Resources](#resources)
    - [How much memory does each collector container need?](#how-much-memory-does-each-collector-container-need)
    - [InfluxDB capacity and performance requirements](#influxdb-capacity-and-performance-requirements)

## E-Series SANtricity Collector

### Why is this separate from E-Series Performance Analyzer?

- Because even after years of actively maintaining my EPA 3 fork, it still does not show in Github (not Google!) search results for "E-Series performance monitoring". Notice I am not complaining about search ranking, although it's the only actively maintained fork of NetApp's EPA. The problem is it can't be found at all, right here on Github! (It's a well known, years-long Github problem all forked projects face.)
- Since EPA 3 hasn't been discoverable anywhere (Github, traditional search engines, AI search engines, you name it), it has zero visibility so folks who stumble across my blog find it, but no one else can. I've had "users" introduced to me by email because it wasn't easy to find it in seconds, so they assumed it must be a private repository
- Because of that ESC is starting from scratch in a new repository that will hopefully be findable (is that too much to ask for?). Recently I disconnected EPA as "fork" of NetApp's EPA. If that helps with discoverability, I may move this code back later
- ESC is not "simple" and definitively not "for everyone". EPA 3, on the other hand, is lightweight, simple to understand, simple to use. EPA 3 is good enough for specific production use and much easier to customize without understanding how everything works together, so I decided to maintain EPA 3 and try to develop its very different successor (ESC) in a separate repository for time being

### Can I use this Collector without the rest of ESC stack?

Yes, from the CLI or packaged as stand-alone container you may send data to own InfluxDB or scrape Collector exports with a Prometheus client.

## Databases and consolidation

### Why can't we have one EPA Collector all monitored arrays?

That's what NetApp's EPA used to do. This EPA refuses to do that. Each EPA instance requires minimal resources and it's extremely easy to deploy. There's no need for consolidation.

InfluxDB can be consolidated, but doesn't have to be.

### What kind of consolidation is possible or advisable?

No consolidation means 1 E-Series, 1 EPA Collector, 1 Influx DB, and optionally 1 Container with S3 service.

Some consolidation can be realized by creating multiple databases on InfluxDB, so that only one DB service is used and each EPA Collector uses its own instance. The trouble with this is InfluxDB 3 Core offers no segregation or encryption, so in this setup any user can access and delete any other user's data.

Other than that, you can send multiple Collectors' data to the same InfluxDB instance - as long as tagging (which should work by default) works, you'll be able to filter (`GROUP BY`) any source system.

### Can the E-Series' system WWN and/or Name change?

WWN can't without you (the admin) knowing it. It is theoretically [possible](https://kb.netapp.com/Advice_and_Troubleshooting/Data_Storage_Software/E-Series_SANtricity_Software_Suite/WWNs_changed_after_offline_replacement_of_tray_0), though. Should that happen, restart Collector.

System Name can be changed at will, but that will obviously mess up your groupings done by system name and you may need to restart Collector to to have it pick up the new name.

### Where's my InfluxDB data?

`docker-compose.yaml` has it in `./data/influxdb/` by default. The tokens are in `./data/influxdb_tokens/` - make sure to backup `admin.token` if you want to have a backup of it.

### Why do I get `error mounting "/certs/influxdb/influxdb.crt" to rootfs` when I start `influxdb`

It's likely because you first started InfluxDB container before your TLS certificates were ready, and InfluxDB crated directories in place of missing TLS certificates and stalled.

You then removed those with TLS certificate files and restarted, but then InfluxDB container became confused. If that's what happened, run `docker compose rm influxdb` and start it again. If it's something else, then it's likely an InfluxDB thing.

## Metrics, configurations, sensors and events

### What do temperature sensors measure?

The ones we've seen represent the following:

- CPU temperature in degrees C - usually > 50C
- Controller shelf's inlet temperature in degrees C - usually in 20C - 30C range
- "Overall" temperature status as a hex status indicator - 128 if OK, and not 128 if not OK, so this one probably doesn't need a chart but some indicator that alerts if the value is not 128

SANtricity uses "temp" for the 128 figure, although it's really a "status" indicator.

### Why are MEL (Major Event Log) records no longer collected?

Because they're not supposed to be stored in a TSDB. They're more suitable for a SIEM system.

Among related events, ESC stores system failures which are active (unresolved) issues with the system, and those can be used for alerting. 

For historical analysis of various system events, consider using syslog forwarding or MEL with SIEM.

## Visualization and analytics

### Can ECS (EPA 4) use EPA 3 dashboards?

No, ECS is vastly different. A reference dashboard may be provided at a later time.

### How do I customize Prometheus?

It can't be done without hacking the source. Prometheus gets the same data as InfluxDB, drops configuration (unsuitable for Prometheus) and exports the rest.

## Resources

### How much memory does each collector container need?

It should be less than 100 MB RAM and 0.25 vCPU.

### InfluxDB capacity and performance requirements

Performance requirements should be insignificant even for up to half a dozen arrays. If InfluxDB is on flash disks, any E-Series model will do. Use InfluxDB Explorer to customize cache if you serve InfluxDB off NL-SAS.

Capacity requirements depend on the number of arrays, disks and volumes (LUNs). Without tiering to S3, InfluxDB should use less than 10 GB/month.
