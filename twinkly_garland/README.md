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
- **Sync (ensure)** compares the stored movies with the wanted set, deletes the stale ones one by one
  (`DELETE movies/<id>`, undocumented but works, also while playing; ids above a deleted movie shift down, so it goes
  from the highest id) and uploads only the missing ones. The LEDs keep playing, a device that is off stays off, and the
  playing movie is selected again afterwards (the "current movie" is stored as an index). Each movie costs about 4
  frames besides its own, which is counted before anything is deleted. If the firmware ever refuses a single delete, it
  falls back to switching the LEDs off, wiping everything (`DELETE movies`, allowed only while off) and re-uploading.
  This also repairs a device after a firmware update wiped its movies.
- **Play** resolves the effect name to the right movie on each device (selection is by index, which shifts, so it is always
  re-resolved) and syncs first if the device drifted. Re-selecting the already playing effect is a no-op.
- **In rotation** effects (with a weight 1-5) are the pool for `effect: "random"`.
- The editor previews an effect in the browser against the real layout before anything is sent.

## Formula effects

Tab **Formulas**: an effect is a few lines, one `name = expression` per line, the last line is the colour. It is evaluated for
every LED and every frame, so it is a function of the position and the loop time:

    q = rise(x*5, y*3, t, cells)                 # noise drifting upward, loops exactly
    heat = (q - (1 - max(1 - y/height, 0)) * 0.85) * contrast
    palette("fire", heat)

- Variables: `x y` (y = 0 bottom .. 1 top, x in the real proportions), `u v` (0..1 across the area), `r a` (distance and angle
  from the centre), `i n` (LED index and count), `t` (0..1 loop phase), `w h`, `seed`, `tau pi`, your own parameters (they become
  sliders) and any name you assign.
- Functions: `sin cos atan2 abs sqrt exp floor fract sign min max clamp step smoothstep mix tri dist noise noise3 tnoise rise
  hash palette cpalette hsv rgb gray` (the editor lists them with descriptions). Colours (`palette`, `hsv`, `rgb`, `gray`) can be
  added and multiplied. Use whole numbers of cycles of `t` or `tnoise` / `rise` and the loop is seamless; the editor shows a warning
  when there is a jump.
- Safety: the code is parsed with `ast` and only whitelisted nodes are accepted (numbers, arithmetic, comparisons, conditions,
  calls of the listed functions, assignments); no attributes, indexing, loops, imports or text except palette names. `/`, `%` and `**`
  are made safe, size and render time are limited.
- Saved formulas live in `/data/formulas.json` and appear as generators in the effect editor ("<name> (formula)"), so they can be
  layered, masked and given a palette-free colour of their own. A formula that is used by an effect cannot be deleted.

### Inputs from Home Assistant and live preview

A formula can have **inputs**: a name, an entity (and optionally an attribute, e.g. `sun.sun` / `elevation`), the value that maps to
0 and to 1, a smoothing time in seconds and a default. The input is then an ordinary variable 0..1 in the formula, for example

    glow = smoothstep(valve * 0.9, 0, y) * valve      # a warm glow as high as the radiator valve is open

Non-numeric states count as 1 when they are "on", "home", "playing", "cleaning", "heat", "heating", "open", "detected", else 0.
Unavailable values keep the last one. "Live preview" computes frames on the server from the current values of Home Assistant; a
stored effect (movie on the garland) uses the default values, so it stays deterministic and keeps working without Home Assistant.
Access to Home Assistant uses the Supervisor (`homeassistant_api: true`). For development without the Supervisor set
`TWINKLY_HA_BASE` and `TWINKLY_HA_TOKEN` to a Home Assistant URL and a long-lived token.

## Scanning LED positions

Tab **Scan**: open it on a phone through the https address of Home Assistant (browsers give the camera only to https
pages), darken the room, hold the phone steady with the whole garland in view, press "Open camera", then "Start scan".
The garland switches to real-time mode and shows patterns while the page takes photos; playback is restored afterwards.
Press "Light test" first to see by eye that the garland follows the patterns (no camera needed).
Check the result (green = recognised, blue = found separately, orange = estimated from neighbours), rotate/mirror if
needed and press "Apply to the garland". The previous layout is saved in `/data/layouts/<name>.backup-<time>.json`.

## HTTP API (also usable from HA `rest_command`)

- `POST api/play` with `{"effect": "<key>", "devices": ["<name>", ...]}` (empty list = all devices). `effect` may be `"random"`: one effect that is on every target device and in the rotation is picked (weighted). Returns 502 if no device could play it.
- `POST api/ensure`, `POST api/devices/<name>/ensure`, `GET api/devices/<name>/plan`
- `GET|PUT api/instances`, `GET|PUT api/formulas`, `GET api/ha/status|entities`, `POST api/ha/read`, `POST api/live/preview/start|<id>/stop`, `GET api/live/preview/<id>/frame`, `POST api/formulas/check`, `GET|PUT api/palettes`, `POST api/preview`, `GET api/gallery`, `GET api/status`, `POST api/scan/start|pattern|stop|apply`, `GET api/devices`, `GET api/effects`

## Known issues / tech debt

- **Scan has not been tried with a real phone camera yet.** Tested only on a synthetic camera and on the garland itself
  ("Light test", confirmed by eye). Open points: exposure lock works only on some phones, the camera permission inside the
  Home Assistant ingress iframe is unverified, thresholds may need tuning on real photos.
- **A steady phone (tripod) is required.** Hand shake above ~1.5 px between photos breaks the decoding; the scan now
  detects this and says so. Remaining weak spot at ~1.5 px shake: the single-LED search can pick the edge of a bright
  static light inside the garland area (4 wrong LEDs in the synthetic test). Ideas: mask saturated static sources found in the
  "off" photos, pick the blob nearest to the position predicted from the neighbours instead of the brightest one, confirm
  single-LED results with a second shot.
- **Scan is flat (2D, one viewpoint).** The tree needs several angles (3D); the data model keeps results per view but the UI
  does not do it yet. Syncing two garlands is also open (the tree is not online; group/sync API of the firmware is unexplored).
- **The device keeps one login token.** Any other client that logs in (the Home Assistant Twinkly integration polls every
  30 s) invalidates ours; xled re-logins, which shows up as `401` / `verify failed` warnings and rare 502 on play. Fix
  options: move on/off of the garland into the add-on and disable the integration, or accept the noise.
- **Single-movie delete (`DELETE movies/<id>`) is undocumented firmware behaviour.** There is a wipe-and-rebuild fallback,
  but a future firmware could change it. The device refuses new movies with HTTP 406 when full (each movie costs ~4 frames
  on top of its own); the capacity check runs before anything is deleted.
- **Library UX:** effects that are not "On the garland" are just dimmed. Wanted: an explicit "not on the garland" label with
  an "Add" button, a hint how many more effects fit, and a "shorten all effects" shortcut (e.g. 6 s x 8 fps).
- **Proportions are entered by hand** ("Real size of the lit area"). A scan with "keep proportions" gives them automatically
  but only once the scan works well.
- **Not verified:** a local Docker build of the image (only GitHub Actions builds it), the update error seen once at
  02:12 on 2026-11-16 (`update.install ... unknown error`, the update still installed).
- **Ideas, not started (live mode and data-driven effects).** Formulas could take inputs from Home Assistant (a temperature,
  a thermostat state, a media player). Two levels: (1) *stored*: the value is sampled when the movie is rendered and the movie is
  re-rendered and synced only when it changes noticeably (slow things like temperature or heating mode; keeps working without HA);
  (2) *live*: the add-on streams frames in real-time mode (UDP, 10-25 fps) computed from fast inputs (needs the add-on and HA up; has
  to fall back to the stored movie when the stream stops; the device keeps one login token, so streaming competes with other
  clients). HA does not expose an audio spectrum: music reactivity needs the audio analysed somewhere else (a microphone or a
  stream tapped by the add-on); a media player gives only state, volume, title and position.
