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
  from the centre), `i n` (LED index and count), `t` (0..1 loop phase), `w h`, `seed`, `now` (seconds, live), `pace` (the speed multiplier of the live round, 1 elsewhere), `tau pi`, your own parameters
  (they become sliders) and any name you assign.
- **Theme of a round:** `palette("theme", v)` / `cpalette("theme", v)` take the palette that `live:random` picked for the round, `pace`
  is its speed multiplier (0.6 to 1.6): write `tm = now * pace` and `x_phase * pace` and the scene runs slower or faster from round to
  round with its colours changed. A scene started by name, a stored effect and the previews get the default theme (palette rainbow, pace 1).
- Functions: `sin cos atan2 abs sqrt exp floor fract sign min max clamp step smoothstep mix tri dist noise noise3 tnoise rise
  hash palette cpalette hsv rgb gray` (the editor lists them with descriptions). Colours (`palette`, `hsv`, `rgb`, `gray`) can be
  added and multiplied. Use whole numbers of cycles of `t` or `tnoise` / `rise` and the loop is seamless; the editor shows a warning
  when there is a jump.
- Safety: the code is parsed with `ast` and only whitelisted nodes are accepted (numbers, arithmetic, comparisons, conditions,
  calls of the listed functions, assignments); no attributes, indexing, loops, imports or text except palette names. `/`, `%` and `**`
  are made safe, size and render time are limited.
- Saved formulas live in `/data/formulas.json` and appear as generators in the effect editor ("<name> (formula)"), so they can be
  layered, masked and given a palette-free colour of their own. A formula that is used by an effect cannot be deleted.

### Geometry and feedback

`r` and `a` (distance and angle in turns from the centre) make shapes easy: concentric rings `sin(tau*(r*rings - t))`, a spiral
`fract(a*arms + r*twist - t)`, a six-fold kaleidoscope `m = mirror(a, 6)`, `px = r*cos(m*tau)`, `py = r*sin(m*tau)` and then any pattern
of `(px, py)`. `<input>_phase` is the running total of an input (value x seconds), so `cos(tau*(a + wind_phase*0.1))` turns at a speed
that follows the wind without jumps. `prev(x, y)` is the colour of the previous frame at that position, interpolated between the LEDs:
`prev(x*0.97, (y-0.5)*0.97 + 0.5) * 0.95` pulls the picture outward and fades it (a tunnel); add something new in the middle and it
streams outward. Examples: "Rings live", "Kaleidoscope live", "Spiral live", "Tunnel live", "Mandala live" (bound to power, wind, sun,
radiator valve and the load of two PCs).

### Inputs from Home Assistant and live preview

A formula can have **inputs**: a name, an entity (and optionally an attribute, e.g. `sun.sun` / `elevation`), the value that maps to
0 and to 1, a smoothing time in seconds and a default. The input is then an ordinary variable 0..1 in the formula, for example

    glow = smoothstep(valve * 0.9, 0, y) * valve      # a warm glow as high as the radiator valve is open

Non-numeric states count as 1 when they are "on", "home", "playing", "cleaning", "heat", "heating", "open", "detected", else 0.
Unavailable values keep the last one. "Live preview" computes frames on the server from the current values of Home Assistant; a
stored effect (movie on the garland) uses the default values, so it stays deterministic and keeps working without Home Assistant.
Access to Home Assistant uses the Supervisor (`homeassistant_api: true`). For development without the Supervisor set
`TWINKLY_HA_BASE` and `TWINKLY_HA_TOKEN` to a Home Assistant URL and a long-lived token.

### Auto range and events

Real sensors rarely use the range you guessed. Tick **auto** on an input and the last 30 minutes of that sensor (read from the Home
Assistant history when the scene starts) are mapped to 0..1, so it always moves over its whole range; "to 0" / "to 1" are only the
starting guess. Besides the value every input gives event signals, so a static sensor can still drive something lively:
`name_kick` (1 when the value jumps, fades in about 1.5 s), `name_age` (seconds since the last jump), `name_count` (number of jumps:
use it as a seed, `hash(name_count, 1)` is a new random place for every event), `name_dir` (+1 rise / -1 fall) and `name_delta`
(speed of change). "event" is the size of a jump as a share of the 0..1 range. Example, a ring that is born at a random place whenever
the house power jumps:

    ring = smoothstep(0.1, 0, abs(dist(x, y, (hash(house_count, 1) - 0.5) * w, hash(house_count, 2)) - house_age * 0.45))
    ring * max(1 - house_age / 3.5, 0)

Examples: "Spectrum live", "Pulse rings live", "Network comets live", "Heartbeat live" and the retuned "House / Rings / Kaleidoscope /
Spiral / Tunnel / Mandala live".

### Live scenes on the garland

A saved formula (typically with inputs from Home Assistant) can be played **live**: the add-on computes frames from the current
values and streams them to the garland in real-time mode, instead of storing a movie. Start it with the button "Play live on the
garland" in the Formulas tab, `POST api/live/play {"scene": "<formula name>"}` or, through the existing `rest_command`, `effect: "live:<name>"`.

- **From the automation:** `effect: "live:<name>"` plays a saved formula; `effect: "live:random"` starts a **round**: every garland gets one of the saved formulas that have
  inputs (every live scene you save joins the rotation) meant for its shape (a wall: "wall" or "any", a tree: "tree" or "any", set in "Meant for" of the
  editor), preferring another one than the current and the scenes that use the theme; where the pools overlap the garlands share the scene. **All the garlands of a
  round share one theme** (a palette and a pace, picked at random, shown in the device card). A garland that asks within 2 minutes after another one
  started a round joins its theme (and its scene, if it may play it). The same scene called again is kept
  (not restarted), so it is safe to call every few minutes. `POST api/live/play` has a `restart` flag (used after editing).
- It never loops (no seam), the inputs are smoothed and every colour channel is limited in how fast it may change (no strobing).
- **Stop:** the Stop button, `POST api/live/stop`, or any explicit `play` of a stored effect / a Sync. The garland returns to what it
  was doing (the same stored movie, or off). `effect: "random"` (the automation) leaves a running live scene alone.
- If somebody else changes the mode of the device (Home Assistant turns the light off, the phone app), the stream ends at once.
- The device keeps ONE login token and the Home Assistant Twinkly integration logs in about every 30 s, so a live stream sees a re-login
  every half minute or so (shown in the device card). The stream recovers on its next HTTP ping; if it is visible as a hiccup, switch off
  polling of the Twinkly integration in Home Assistant.
- If the add-on dies while streaming, the device stays in real-time mode showing the last frame; the add-on switches it back at its
  next start and the automation's next `random` restores it as well.

## Scanning LED positions

Tab **Scan**: open it on a phone through the https address of Home Assistant (browsers give the camera only to https
pages), darken the room, hold the phone steady with the whole garland in view, press "Open camera", then "Start scan".
The garland switches to real-time mode and shows patterns while the page takes photos; playback is restored afterwards.
Press "Light test" first to see by eye that the garland follows the patterns (no camera needed).
Check the result (green = recognised, blue = found separately, orange = estimated from neighbours), rotate/mirror if
needed and press "Apply to the garland". The previous layout is saved in `/data/layouts/<name>.backup-<time>.json`.

Scan types: *flat wall or window* (every LED visible), *tree, one side* (the far side is estimated along the string) and
*tree, front and back (3D)*: two views, the scan asks you to move the phone to the opposite side after the first one; the
result is a 3D layout (a cone) written to the garland as `3d`. Patterns (selector in the tab): *hue* (default: every LED is
lit in every photo, red = 0 and blue = 1, read pixel by pixel; best for dense strings), *colour bits* (three bits per photo,
fewest photos) and *white on / off*. A style that is not read makes the scan repeat itself with white by itself. The page
locks exposure, white balance and focus where the browser allows (Chrome on Android most; iPhone and Firefox hardly) and
says in the result what it could lock.

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
- **Scan: a tree from the front and the back only.** Four sides ("Tree, all sides") are not done; the two-view merge assumes the
  tree is upright and roughly a cone, and the add-on's own effects still use x, y of the layout, not z. A 3d layout written to the
  device is not verified on a real garland. Syncing two garlands is also open (the tree is not online; group/sync API of the firmware is unexplored).
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
- **Ideas, not started (data-driven stored effects, music).** Live scenes are done. Still open: *stored* effects that re-render and sync only
  when a Home Assistant value changes noticeably (slow things like temperature or heating mode; would keep working without Home
  Assistant). Home Assistant has no audio spectrum: music reactivity needs the audio analysed elsewhere (a microphone or a stream
  tapped by the add-on, or a PC program posting levels); a media player gives only state, volume, title and position.
  A live scene's `fps` is fixed at 12 and the add-on has not been measured on the real Home Assistant host yet.

## Home Assistant entities (MQTT)

Set the broker in the add-on options (the add-on does not look for it by itself):

```yaml
mqtt_host: <broker host, e.g. the EMQX or Mosquitto add-on hostname>
mqtt_port: 1883
mqtt_user: "!secret twinkly_mqtt_user"
mqtt_password: "!secret twinkly_mqtt_password"
```

Every device from `devices` then shows up in Home Assistant through MQTT discovery as `light.<device name in lowercase>`
(spaces and symbols become `_`). Turn it on or off, set the brightness, pick an effect (`random`, `live:random`,
`live:<scene>` or any library effect); the `light.turn_on` call with `effect:` does what `POST api/play` does. The state is read
from the device every 15 s (not while a live scene runs, then the add-on already knows). The broker user needs access to
`homeassistant/#` and `twinkly/#`. Remove the Home Assistant Twinkly integration of the same devices first or
afterwards, otherwise the entity ids are taken.
