# Change log

- 4.0.0 (October 7, 2025)
  - Full re-write of E-Series Performance Analyzer version 3
  - Major database back-end upgrade to InfluxDB 3 Core. Data migration from EPA 3 (InfluxDB v1) is not supported  
  - Add collection of controller perfromance for each controller
  - Add collection of physical drive information (configuration, in addition to performance, which was collected in EPA 3) 
  - Add collection of all other components used for data enrichment (volumes, system, interfaces, etc.)
  - Improvements in security-related aspects (defaults: HTTPS only, HTTPS everywhere, TLS v1.3, mandatory strict TLS certificate validation for InfluxDB, Post-Quantum ready reverse HTTPS proxy)
  - Database UI (InfluxDB Explorer) included
  - Reverse proxy (NGINX) included for better security posture and end-to-end TLS encryption
  - Temperature sensors, PSU (power supply unit) readings and flash disk wear level all collected and should handle multiple shelves (although due to lack of hardware access this hasn't been validated)
  - Many small improvements in code and updates of 3rd party Python modules
  - Most of the v3 complexity gone (and some added to accommodate new high-value features)
  - REMOVED: dropped MEL (Major Event Log) collection that EPA 3 has. The reason is that shouldn't be gathered in a TSDB, but in a SIEM sytem. System failure events continue to be gathered
  - REMOVED: ARM64 support (due to lack of interest/feedback). EPA Collector 4 likely works on ARM64, but no testing or bug fixes will be done. Other containers only download x86_64 binaries

Changelog for EPA version 3 are in my EPA 3 fork repository [here](https://github.com/scaleoutsean/eseries-perf-analyzer).
