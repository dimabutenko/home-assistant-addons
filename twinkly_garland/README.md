# Twinkly Garland

Local control of Twinkly Gen2 light strings through the device HTTP API (no cloud).
Effects are stored as movies on the devices themselves, so they keep playing without Home Assistant.

## Options

- `devices`: list of `name` + `host` (IP or hostname) of each garland.
- `auto_ensure` (default off): periodically reconcile the devices with the saved effects.
- `ensure_interval_min` (default 60): reconcile period in minutes.

Open the web UI from the "Garland" sidebar entry (ingress).

## How it works

- An **effect** is 1-4 **layers** (generator + palette + parameters + mix mode + opacity + mask) saved in the library
  (`/data/instances.json`). Palettes are shared gradients (`/data/palettes.json`).
- Each effect marked **On the garland** is rendered against the device's real LED layout and stored on the device as a movie.
  The movie's `unique_id` is derived from the effect name and a hash of the rendered content, so the device itself tells
  which version it holds.
- **Sync (ensure)** compares the stored movies with the wanted set. On any difference it switches the LEDs off, wipes and
  re-uploads everything (the firmware can only delete all movies at once, and only while the LEDs are off). This repairs a
  device after a firmware update wiped its movies.
- **Play** resolves the effect name to the right movie on each device (selection is by index, which shifts, so it is always
  re-resolved) and syncs first if the device drifted. Re-selecting the already playing effect is a no-op.
- **In rotation** effects (with a weight 1-5) are the pool for `effect: "random"`.
- The editor previews an effect in the browser against the real layout before anything is sent.

## Scanning LED positions

Tab **Scan**: open it on a phone through the https address of Home Assistant (browsers give the camera only to https
pages), darken the room, hold the phone steady with the whole garland in view, press "Open camera", then "Start scan".
The garland switches to real-time mode and shows patterns while the page takes photos; playback is restored afterwards.
Check the result (green = recognised, blue = found separately, orange = estimated from neighbours), rotate/mirror if
needed and press "Apply to the garland". The previous layout is saved in `/data/layouts/<name>.backup-<time>.json`.

## HTTP API (also usable from HA `rest_command`)

- `POST api/play` with `{"effect": "<key>", "devices": ["<name>", ...]}` (empty list = all devices). `effect` may be `"random"`: one effect that is on every target device and in the rotation is picked (weighted). Returns 502 if no device could play it.
- `POST api/ensure`, `POST api/devices/<name>/ensure`, `GET api/devices/<name>/plan`
- `GET|PUT api/instances`, `GET|PUT api/palettes`, `POST api/preview`, `GET api/gallery`, `GET api/status`, `POST api/scan/start|pattern|stop|apply`, `GET api/devices`, `GET api/effects`
