# Changelog

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
