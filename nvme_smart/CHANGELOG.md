# Changelog

## 0.1.0
- First version: reads the NVMe SMART log every `interval_s` seconds (default 300), creates `sensor.nvme_smart_*` in Home Assistant and writes
  one logfmt line per poll to Loki (`job="nvme-smart"`); logs a `WARN` when the unsafe-shutdown counter or the error log of the drive grew.
