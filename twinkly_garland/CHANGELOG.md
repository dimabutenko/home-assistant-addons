# Changelog

## 0.7.2
- Scan is much more robust against clutter outside the garland: two "off" and two "on" photos (only what is the same in both counts, so flickering lights and passing cars drop out), single-LED search limited to the area where LEDs were found and away from unstable pixels, phone-motion check with a clear message, and a stop with an explanation instead of a "successful" garbage result when fewer than half of the LEDs are recognised.
- Tested on a synthetic camera with 8 street lights (2 flickering): 0 wrong LEDs with a steady phone (use a tripod), error under 0.5 px.

## 0.7.1
- Scan: the LED brightness calibration no longer dims the LEDs towards invisibility when a phone camera is dazzled (it went 170 -> 85 -> 42 -> 21, so single LEDs could not be seen by eye). The floor is 100 of 255, single LEDs are lit at 200+, and the status line shows the brightness used.
- Scan: new "Light test" button lights the garland step by step (everything, code pattern, single LEDs) so you can check by eye that scanning works, without the camera.

## 0.7.0
- Sync no longer wipes the device: stale effects are deleted one by one (`DELETE movies/<id>` works on this firmware, also while playing) and only the missing ones are uploaded. No blackout, much faster, a device that is off stays off.
- The playing effect stays selected after deletions (the device stores the current movie as an index that shifts).
- Capacity check includes the per-movie overhead (about 4 frames) and runs before anything is deleted; a full device (HTTP 406) gives a clear message instead of a half-finished sync. Frame budget in the library is more accurate.
- Fallback: if a single delete is refused, the old wipe-and-rebuild path is used (and it puts the previous mode back).

## 0.6.2
- Fix HTTP 401 / "verify failed" storms in the log and occasional 502 on play: the device keeps a single login token, and parallel requests (status polling, play, scan) each logged in again and invalidated one another. Now there is one shared client per device and all calls to a device are serialised.
- Status is cached for 10 s, built from fewer requests, the library polls every 45 s instead of 20 s, and the Refresh button forces a fresh read.

## 0.6.1
- Round shapes: effects are now drawn on the real proportions of the lit area. Twinkly stores a scan stretched to a 2:1 box, so circles became ovals on the wall. Enter the real width x height of the area in the device card ("Real size of the lit area"); preview and thumbnails use the same proportions.
- Generators no longer assume x in -1..1 (columns of snow/rain/bars, checker cells, storm flashes follow the real extent).
- Flame: new look with tongues of flame (contrast and fade-with-height parameters, taller and more varied by default).
- The library no longer redraws while you type in a field.

## 0.6.0
- LED position scan (tab "Scan"): the phone camera watches while the garland shows patterns in real-time mode
  (dark, all on, 10 Gray-code bit patterns), the browser finds every LED, decodes its index, checks doubtful ones
  one by one and estimates hidden ones from their neighbours on the string. The result can be rotated, mirrored and
  scaled, previewed next to the current layout and written to the device (the old layout is backed up first).
- The scan needs the camera, so Home Assistant must be opened through an https address.
- While a scan runs, play/ensure for that device are refused; playback is restored afterwards.

## 0.5.1
- Library thumbnails are still frames and animate only while hovered (tap on touch screens), which removes the lag with many effects.

## 0.5.0
- New web UI: library of live animated thumbnails with per-device status (what plays, what is stored, frame budget, sync state), a step-by-step editor with automatic preview, and a palette editor.
- Effects are made of 1-4 layers with palette, mix mode (normal/add/screen/multiply/max), opacity and an x/y/radial mask.
- Colour palettes (13 built-in, custom ones editable). Existing generators now take a palette instead of fixed hues, so they are re-uploaded once.
- Per effect: "on the garland" (stored on devices) and "in rotation" (picked by `effect: random`, with a weight 1-5).
- 14 new generators: clouds, stars, storm, ocean, rain, bars, scanner, lavalamp, glitter, helix, checker, confetti, radar, pulse. New ones start in the library only (not on the garland) to save device frames.
- API: `GET /api/status`, `GET /api/gallery`, `GET|PUT /api/palettes`; `POST /api/preview` takes a whole effect.

## 0.4.0
- 11 new abstract generators: twinkle, wave, aurora, snowfall, plasma, meteors, ripple, candy, fireflies, breathe, pinwheel. All loop seamlessly.
- Each generator gets one default saved effect the first time it is seen (a deleted effect is not brought back).
- Rendered frames are cached, so repeated play/ensure calls are cheap.

## 0.3.1
- Fix ensure: the firmware only deletes movies while the LEDs are off (code 1102 otherwise), so the mode is switched to `off` first and the result is verified.
- Fix ensure on a device with no stored movies (empty `movies/current` answer).
- `play` no longer restarts an effect that is already playing.

## 0.3.0
- `POST api/play` accepts `effect: "random"` (one key common to all target devices) and returns 502 when nothing could be played.

## 0.2.0
- Effect generator `flame` (seamless loop, parametric) and the effect editor with browser preview on the real LED layout.
- Ensure/reconcile layer: content-hashed movie ids, plan (dry run), rebuild on drift, optional periodic auto-ensure.
- `POST api/play` resolves an effect key to the right movie per device.

## 0.1.0
- Scaffold: ingress web page listing configured devices, firmware and stored movies.
