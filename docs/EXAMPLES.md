# Examples of SQL and Grafana queries for EPA 4 database

- [Examples of SQL and Grafana queries for EPA 4 database](#examples-of-sql-and-grafana-queries-for-epa-4-database)
  - [SQL](#sql)
  - [InfluxQL](#influxql)
    - [Performance](#performance)
    - [Configuration (Capacity, Firmware, Configuration)](#configuration-capacity-firmware-configuration)
    - [Events](#events)
    - [Environmental](#environmental)
  - [Grafana tips](#grafana-tips)

This file contains example InfluxQL (InfluxDB 3 `--language influxql`) and SQL queries and Grafana tips for common operational tasks.

## SQL

TODO

## InfluxQL

### Performance

- Per-drive throughput time series (chart)

```sql
SELECT mean("combined_throughput") AS mean_tp
FROM "performance_drive_statistics"
WHERE "storage_system_name" = 'sean' AND time >= now() - 1h
GROUP BY time(1m), "drive_id" fill(null)
```

Explanation: group by time and drive_id so each drive is a separate series in Grafana. Use smaller time buckets (1m) for high-frequency visuals.

- Read response time percentiles across drives

```sql
SELECT percentile("read_response_time", 95) AS p95_read_rt
FROM "performance_drive_statistics"
WHERE time >= now() - 6h
GROUP BY time(5m) fill(null)
```

Explanation: useful to spot tail latency spikes across the system.

- Drive queue depth heatmap (per-drive stacked series)

```sql
SELECT mean("average_queue_depth")
FROM "performance_drive_statistics"
WHERE time >= now() - 24h
GROUP BY time(5m), "drive_slot" fill(0)
```

Explanation: group by `drive_slot` (or `drive_id`) to compare activity across physical drives.

### Configuration (Capacity, Firmware, Configuration)

- Latest firmware version per drive (table-like; group by `slot` tag)

```sql
SELECT LAST("firmware_version") AS firmware, LAST("serialNumber") AS serial
FROM "config_drives"
WHERE "storage_system_name" = 'sean'
GROUP BY "slot"
```

Explanation: config_drives stores `firmware_version` as a field and `slot` as a tag; grouping by the tag gives one row per slot which is useful for tables in Grafana.

- Storage pools free space (capacity overview)

```sql
SELECT LAST("free_space") AS free_bytes, LAST("totalRaidedSpace") AS raided_bytes
FROM "config_storage_pools"
GROUP BY "pool_name", "raid_level"
```

Explanation: last() returns the most recent known values; grouping by pool_name yields one row per pool.

- Volumes with non-optimal status (quick filter)

```sql
SELECT LAST("status") AS status, LAST("totalSizeInBytes") AS size
FROM "config_volumes"
WHERE "status" != 'optimal'
GROUP BY "volumeRef"
```

Explanation: filter to find volumes under maintenance or with errors. `volumeRef` may be a field; if not available as a tag, group by a tag such as `volume_id` if present in your environment.

### Events

- Recent system failures (table, latest 100)

```sql
SELECT * FROM "events_system_failures"
WHERE time >= now() - 7d
ORDER BY time DESC
LIMIT 100
```

Explanation: events are usually sparse; return recent rows and examine `failure_type`, `object_type`, and `object_ref` tags.

- Failure counts by type (chart)

```sql
SELECT COUNT("failure_occurred") AS failures
FROM "events_system_failures"
WHERE time >= now() - 30d
GROUP BY time(1d), "failure_type" fill(0)
```

### Environmental

- Max temperature per tray over last 24h (heat map)

```sql
SELECT MAX("temperature") AS max_temp
FROM "env_temperature"
WHERE time >= now() - 24h
GROUP BY time(30m), "tray_id" fill(null)
```

- Power draw per system (hourly)

```sql
SELECT MEAN("power_watts") AS avg_watts
FROM "env_power"
WHERE time >= now() - 7d
GROUP BY time(1h), "storage_system_name" fill(null)
```

## Grafana tips

- Grouping and charts vs tables
  - Charts: use aggregation functions (`mean()`, `max()`, `percentile()`) and `GROUP BY time(...)` plus one or more tags to create distinct series. Example: group by time(1m), "drive_id".
  - Tables: use `LAST(field)` and `GROUP BY` a tag that uniquely identifies the object (slot, pool_name, drive_slot). Grafana table panels will display one row per `GROUP BY` series.

- Show the latest config for each entity in a table
  - InfluxQL: `SELECT LAST(...) FROM measurement GROUP BY "some_tag"` where `some_tag` is e.g., `slot`, `pool_name`, or another identity tag. 

- Time range handling
  - For charts pick a bucket size appropriate to your data density (1m, 5m, 1h). For long-range overviews, use larger buckets to avoid overplotting.

- Grafana transformations & table tricks
  - Use a single query returning `LAST()` grouped by an identifying tag, then use Grafana Transform → Organize fields to rename columns and sort. Use the Sort transformation to show most recently-updated items first.
  - If you need to display a single latest row per object and the id is a field (not a tag), use a subquery pattern where available or enrich the dataset during ingestion/enrichment so the id is a tag.

- Aliasing
  - Use aliasing functions (e.g. `AS`) so Grafana legends and table column headers are readable: `SELECT MEAN("combined_throughput") AS "throughput.B/s"`.

- Tagging
  - Basic tags are in place, but more could be added. It's a performance vs. usability trade-off that can impact performance, so if you encounter situations where additional tags may be helpful, leave feedback in Github Issues
