#!/bin/sh
# NVMe SMART -> Home Assistant sensors + one log line in Loki, every interval_s seconds.
# Read-only: only `nvme smart-log` is run against the device.

OPTS=/data/options.json
DEV="$(jq -r '.device // "/dev/nvme0"' "$OPTS")"
INTERVAL="$(jq -r '.interval_s // 300' "$OPTS")"
LOKI="$(jq -r '.loki_url // ""' "$OPTS")"
HA_API="http://supervisor/core/api"
LAST_FILE=/data/last_counters

log() { echo "$(date -u '+%Y-%m-%d %H:%M:%S') $*"; }

# put <entity id without "sensor."> <state> <unit> <friendly name> <icon> <state_class>
put() {
  body="$(jq -n --arg s "$2" --arg u "$3" --arg n "$4" --arg i "$5" --arg c "$6" --arg t "$NOW" \
    '{state: $s, attributes: ({friendly_name: $n, icon: $i, updated: $t}
       + (if $u != "" then {unit_of_measurement: $u} else {} end)
       + (if $c != "" then {state_class: $c} else {} end))}')"
  code="$(curl -s -m 10 -o /dev/null -w '%{http_code}' -X POST \
    -H "Authorization: Bearer ${SUPERVISOR_TOKEN}" -H 'Content-Type: application/json' \
    -d "$body" "${HA_API}/states/sensor.$1")"
  case "$code" in 200|201) ;; *) log "ERROR: posting sensor.$1 returned HTTP $code" ;; esac
}

poll() {
  NOW="$(date -u '+%Y-%m-%dT%H:%M:%SZ')"
  RAW="$(nvme smart-log "$DEV" -o json 2>&1)" || { log "ERROR: nvme smart-log $DEV failed: $RAW"; return 1; }
  if ! echo "$RAW" | jq -e . >/dev/null 2>&1; then log "ERROR: nvme smart-log did not return JSON: $RAW"; return 1; fi
  get() { echo "$RAW" | jq -r ".$1 // 0"; }

  CW="$(get critical_warning)"
  TEMP_K="$(get temperature)"
  SPARE="$(get avail_spare)"
  USED="$(get percent_used)"
  DU_R="$(get data_units_read)"
  DU_W="$(get data_units_written)"
  HOST_R="$(get host_read_commands)"
  HOST_W="$(get host_write_commands)"
  BUSY="$(get controller_busy_time)"
  CYCLES="$(get power_cycles)"
  POH="$(get power_on_hours)"
  UNSAFE="$(get unsafe_shutdowns)"
  MEDIA="$(get media_errors)"
  ERRS="$(get num_err_log_entries)"
  TEMP_C="$(awk -v k="$TEMP_K" 'BEGIN{printf "%d", k-273.15}')"
  TB_R="$(awk -v n="$DU_R" 'BEGIN{printf "%.2f", n*512000/1e12}')"
  TB_W="$(awk -v n="$DU_W" 'BEGIN{printf "%.2f", n*512000/1e12}')"

  # a growth of the counters between two polls is the sign of a reset / power loss of the drive
  if [ -f "$LAST_FILE" ]; then
    read -r L_UNSAFE L_CYCLES L_ERRS < "$LAST_FILE"
    if [ "$UNSAFE" -gt "${L_UNSAFE:-$UNSAFE}" ] 2>/dev/null; then
      log "WARN: the drive lost power or was reset: unsafe_shutdowns $L_UNSAFE -> $UNSAFE, power_cycles $L_CYCLES -> $CYCLES"
    fi
    if [ "$ERRS" -gt "${L_ERRS:-$ERRS}" ] 2>/dev/null; then
      log "WARN: error log entries of the drive grew: $L_ERRS -> $ERRS"
    fi
  fi
  echo "$UNSAFE $CYCLES $ERRS" > "$LAST_FILE"

  put nvme_smart_unsafe_shutdowns "$UNSAFE" "" "NVMe SMART unsafe shutdowns" mdi:flash-alert total_increasing
  put nvme_smart_power_cycles "$CYCLES" "" "NVMe SMART power cycles" mdi:power-cycle total_increasing
  put nvme_smart_power_on_hours "$POH" "h" "NVMe SMART power-on hours" mdi:clock-outline total_increasing
  put nvme_smart_percentage_used "$USED" "%" "NVMe SMART percentage used" mdi:harddisk measurement
  put nvme_smart_available_spare "$SPARE" "%" "NVMe SMART available spare" mdi:harddisk measurement
  put nvme_smart_media_errors "$MEDIA" "" "NVMe SMART media errors" mdi:alert-circle-outline total_increasing
  put nvme_smart_error_log_entries "$ERRS" "" "NVMe SMART error log entries" mdi:alert-circle-outline total_increasing
  put nvme_smart_critical_warning "$CW" "" "NVMe SMART critical warning" mdi:alert measurement
  put nvme_smart_data_written "$TB_W" "TB" "NVMe SMART data written" mdi:database-arrow-down total_increasing
  put nvme_smart_data_read "$TB_R" "TB" "NVMe SMART data read" mdi:database-arrow-up total_increasing
  put nvme_smart_temperature "$TEMP_C" "°C" "NVMe SMART temperature" mdi:thermometer measurement

  LINE="unsafe_shutdowns=$UNSAFE power_cycles=$CYCLES power_on_hours=$POH percent_used=$USED avail_spare=$SPARE media_errors=$MEDIA err_log_entries=$ERRS critical_warning=$CW temp_c=$TEMP_C data_written_tb=$TB_W data_read_tb=$TB_R host_writes=$HOST_W host_reads=$HOST_R busy_min=$BUSY"
  log "OK $LINE"

  if [ -n "$LOKI" ]; then
    payload="$(jq -n --arg ts "$(date +%s)000000000" --arg l "$LINE" \
      '{streams: [{stream: {job: "nvme-smart", host: "homeassistant"}, values: [[$ts, $l]]}]}')"
    code="$(curl -s -m 10 -o /dev/null -w '%{http_code}' -H 'Content-Type: application/json' -d "$payload" "$LOKI")"
    [ "$code" = "204" ] || log "ERROR: Loki push returned HTTP $code"
  fi
}

log "NVMe SMART started: device=$DEV interval=${INTERVAL}s loki=${LOKI:-off}"
while true; do
  poll
  sleep "$INTERVAL"
done
