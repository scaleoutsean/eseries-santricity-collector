## Change log

- 4.0.0 (October 2, 2025)
  - Full re-write of version 3
  - NEW: Major database back-end upgrade to InfluxDB 3 Core. Data migration from EPA 3 (InfluxDB v1) is not supported  
  - NEW: Add collection of controller information for each controller
  - NEW: Add collection of physical drive information (configuration, rather than performance, which is already collected) 
  - NEW: Add collection of all other components used for data enrichment (volumes, system, interfaces, etc.)
  - NEW: improvements in security-related aspects (defaults: HTTPS only, HTTPS everywhere, TLS v1.3 only, strict TLS certificate validation)
  - IMPROVED: temperature sensors, PSU (power supply unit) readings and flash disk wear level all collected and should handle multiple shelves
  - IMPROVED: many smaller improvements, updates of external Python modules
  - IMPROVED: significant code overhaul with most of v3 complexity gone (and some has been added to accommodate new high-value features)
  - REMOVED: dropped MEL (Major Event Log) collection that EPA 3 has. The reason is that shouldn't be gathered in a TSDB but in SIEM. System failure events continue to be gathered
  - REMOVED: ARM64 support (due to lack of interest/feedback). EPA Collector 4 likely works on ARM64, but no testing or bug fixes will be done

Changelog for EPA version 3 is in Releases or README.md of the EPA 3 fork repository [here](https://github.com/scaleoutsean/eseries-perf-analyzer).