# Twinkly Garland

Local control of Twinkly Gen2 light strings through the device HTTP API (no cloud).
Effects are stored as movies on the devices themselves, so they keep playing without Home Assistant.

## Options

- `devices`: list of `name` + `host` (IP or hostname) of each garland.
- `auto_ensure` (default off): periodically reconcile the devices with the saved effects.
- `ensure_interval_min` (default 60): reconcile period in minutes.

Open the web UI from the "Garland" sidebar entry (ingress).

## How it works

- Effects are code (generators in `app/effects.py`), saved as named instances in `/data/instances.json`.
- Each instance is rendered against the device's real LED layout and stored on the device as a movie.
  The movie's `unique_id` is derived from the instance key and a hash of the rendered content,
  so the device itself tells which version it holds.
- **Ensure** compares the stored movies with the desired set. On any difference it wipes and re-uploads
  everything (the firmware cannot delete a single movie). This repairs a device after a firmware update
  wiped its movies.
- **Play** resolves the instance key to the right movie on each device (selection is by index, which shifts,
  so it is always re-resolved) and reconciles first if the device drifted.
- The editor previews an effect in the browser against the real layout before anything is sent.

## HTTP API (also usable from HA `rest_command`)

- `POST api/play` with `{"effect": "<key>", "devices": ["<name>", ...]}` (empty list = all devices). `effect` may be `"random"`: one key common to all target devices is picked. Returns 502 if no device could play it.
- `POST api/ensure`, `POST api/devices/<name>/ensure`, `GET api/devices/<name>/plan`
- `GET|PUT api/instances`, `POST api/preview`, `GET api/devices`, `GET api/effects`
