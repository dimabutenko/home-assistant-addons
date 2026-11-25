# NVMe SMART

Reads the SMART health log of an NVMe drive every few minutes and publishes it:

- as **sensors in Home Assistant** (with history), and
- as **one log line in Loki** per poll (`logfmt`, `job="nvme-smart"`), so the counters can be graphed in Grafana next to the kernel log.

It was written to find out why an NVMe drive on a Raspberry Pi 5 is reset several times a day: the counters that matter are
`unsafe_shutdowns` and `power_cycles`, they grow with every reset of the drive. The add-on only runs `nvme smart-log` (read-only).

## Sensors

All are created through the Home Assistant API (no MQTT needed), entity ids `sensor.nvme_smart_*`:

| Entity | Meaning |
|---|---|
| `unsafe_shutdowns` | power losses / resets of the drive without a clean shutdown (the key counter) |
| `power_cycles` | power cycles of the drive |
| `power_on_hours` | hours the drive was powered on |
| `percentage_used` | wear, % of the rated endurance |
| `available_spare` | spare cells left, % |
| `media_errors` | unrecoverable media errors |
| `error_log_entries` | entries in the error log of the drive |
| `critical_warning` | critical warning bit field (0 = none) |
| `data_written`, `data_read` | TB written / read |
| `temperature` | composite temperature, °C |

The sensors have no unique id (they are not in the entity registry): after a restart of Home Assistant they appear again within one
poll (5 minutes by default) and keep their history.

## Logs

Every poll writes one line to the add-on log and to Loki, e.g.

```
unsafe_shutdowns=1041 power_cycles=1135 power_on_hours=1318 percent_used=2 avail_spare=100 media_errors=0 err_log_entries=0 critical_warning=0 temp_c=40 data_written_tb=12.06 ...
```

When `unsafe_shutdowns` (or the error log) grew since the previous poll, a `WARN` line is written. In Grafana (Loki):

```
max_over_time({job="nvme-smart"} | logfmt | unwrap unsafe_shutdowns [5m])
{job="nvme-smart"} |= "WARN"
```

## Options

| Option | Default | |
|---|---|---|
| `device` | `/dev/nvme0` | NVMe controller to read |
| `interval_s` | `300` | seconds between two polls (30 to 86400) |
| `loki_url` | `http://71dadad1-grafana-loki:3100/loki/api/v1/push` | Loki push URL; empty = no Loki |

## Installation

1. Add the repository, install the add-on.
2. **Turn off "Protection mode"** on the add-on's Info tab (the add-on needs `SYS_ADMIN` and `SYS_RAWIO` to send the SMART request to
   the drive; it gets only `/dev/nvme0`, not the whole host).
3. Start it. The sensors appear after the first poll.
