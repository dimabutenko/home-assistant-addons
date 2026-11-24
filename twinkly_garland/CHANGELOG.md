# Changelog

## 0.17.2
- **Restore a saved layout.** Every write of a scan saves the layout it replaces (`/data/layouts/<name>.backup-<time>.json`), but there was no way back. The Scan tab now lists them ("Saved layouts (restore)", the oldest one is the layout from before your first scan) with a "Restore this layout" button (`GET api/devices/<name>/layout/backups`, `POST api/scan/restore`). A restore saves the layout it replaces first, so it can be undone too. The backup holds x, y, z only: a layout with z other than 0 goes back as 3d, the others as 2d.
- **Stray LEDs are removed from the layout.** A real scan wrote a layout in which one LED (number 89 of 600) stood at x = 3.1 while all others were within -0.28..0.25, and its neighbours 88 and 90 were fine. The filters of the scan did not catch it and the cause is not known yet (the synthetic tests cannot reproduce it). Now the finished layout is checked as a whole string: a LED that stands far from BOTH neighbours (more than 8 typical steps) while the neighbours stand close to each other (less than 4 steps) is put halfway between them (the end LEDs are checked against their single neighbour), and the result says which LEDs were replaced. Checked on the layout read back from the garland (only LED 89 is found), on 200 clean random strings (nothing touched) and on 200 strings with a planted spike (all found).
- **A warning before writing a layout that is mostly guessed**: if 30% or more of the LEDs were not seen and are only estimated along the string (a tree seen from one side), the confirmation says so.
- **Download the photos of a scan as one zip** (`GET api/scan/dump/<scan id>.zip`, and a link in the Scan tab after "Send the photos"). The photos that were already sent stay on the add-on (the last 4 scans are kept, also across updates): the ids are listed by `GET api/scan/dump`.

## 0.17.1
- **Fix: every scan failed at the first colour pattern** (`POST api/scan/pattern` answered 409, the page said "unknown pattern 'rgb'"). The `rgb` pattern (colour frames: the hue style, the colour-bit style and the red / green / blue light test) was added in 0.16.0 on the page and in the API model, but its branch in `scan.py` was never saved. The white style and the single-LED checks were not affected. Tested now against the real `scan.py` with a fake device: the bytes sent for dark, all, bit, leds and rgb patterns, refusal of a bad rgb request, and the time one pattern call takes (0.07 s).

## 0.17.0
Read in detail how the Twinkly app does the same job (parity table, colour classes, per-pixel decoding, step timing) and took the ideas that were better than ours:
- **Hue-coded patterns, LEDs always lit (the new default).** In every code photo every LED is lit, red for a 0 and blue for a 1. Nothing is switched off, so no brightness threshold is needed and a LED is visible in every photo; the colour decides. Two reference photos (all red, all blue) give every pixel its response to the two colours and a code photo is un-mixed with it. The previous styles stay selectable ("Patterns" in the Scan tab): *Colour bits* (red, green, blue on / off, three bits per photo, fewest photos) and *White on / off*. If the chosen style is not read the scan repeats itself with white by itself.
- **Pixel-by-pixel decoding** (hue style). Every pixel collects its bits over all photos; pixels that show a mixture of two LEDs, or are too dark or too bright, are dropped; the check bits correct one doubtful bit; a pixel then votes for the LED whose code it carries and a LED is where its pixels are (brightness-weighted centre of the pixels near their median). Merged blobs no longer matter: the pixels at the centre of each LED still carry its own code. Synthetic tree, 1000 LEDs: 485 LEDs recognised by code (colour-bit and white styles: 287) and the mean position error 0.15 px (the other styles put some LEDs on a wrong place: 11 px); 600 LEDs: 315 against 235. The price: 13 code photos instead of 5, so a scan takes more photos than the colour-bit style, but fewer single-LED checks.
- **Faster steps.** The add-on sends a new frame at once (it used to wait for the next tick of the 0.15 s stream) and answers when it is out; the page no longer waits a fixed 0.6 s but until the live picture stops changing (at least 0.15 s), which also waits out an automatic exposure that is still adapting. Single-LED checks wait 0.12 s plus that. Expected: about 0.5 s per photo instead of about 1.1 s (an estimate, not measured on a phone).
- **Camera locking is reported and undone.** The page freezes exposure (time, ISO), white balance (temperature) and focus at their current values where the camera offers it, tells in the result what could and could not be locked, and gives the automatics back after the scan.
- Not done on purpose: compensation of a shaking phone (a tripod is still needed) and the firmware's own "mapping" mode (OPENLOOP) that plays the sequence by itself; the latter needs to be tried on a real garland first.

## 0.16.0
Three ideas taken from how the Twinkly app maps a garland (studied from the outside: the standard techniques, no code or data of theirs):
- **Colour code frames (faster scan).** Red, green and blue of every LED are three independent lamps, so one photo carries three bits of the code (and of the check bits). A 300-LED scan needs 5 code photos instead of 13. Three extra photos (all LEDs red, then green, then blue) give every blob its own 3x3 response matrix of the camera; a code photo is then un-mixed with it, which takes care of the crosstalk between the camera's channels, of the white balance and of a different order of the LED colours. A blob whose colours cannot be told apart (saturated) counts as doubtful. If too few LEDs are recognised the scan repeats itself with white patterns by itself. The checkbox "Colour patterns (faster)" in the Scan tab turns it off. The camera's white balance is locked together with the exposure, where the phone allows it. In a synthetic scan (300 LEDs) the colour scan found the same LEDs as the white one with 12 photos instead of 17 per view; the saving is smaller than a third because of the three calibration photos.
- **Catmull-Rom instead of a straight line** for the LEDs nobody saw: a curve through the known LEDs on both sides (knots = LED numbers, so uneven neighbours are fine; it may leave the straight line by at most 0.4 of the gap). On a winding string with gaps of 9 LEDs the mean error went from 2.9 px to 0.3 px.
- **Tree, front and back (3D)**, a new scan type: two views, the phone is moved to the opposite side after the first one (or the tree is turned by 180 degrees). The back view is mirrored and moved onto the front one with the LEDs both views saw (least squares, bad matches thrown out; with fewer than 6 of them the outlines are laid over each other and the result says so). The tree is taken as a cone: for every height the half width is measured, a LED seen from the front gets z = +sqrt(R^2 - x^2), from the back -sqrt(...). A LED nobody saw is put on a spiral between its neighbours (height by the curve, angle along the shorter arc). The result is written to the garland as a **3d** layout; the add-on itself still draws with x and y only (the front projection). Synthetic tree, 300 LEDs: mean 3D error 0.023 of a cone radius of 0.55, the front/back side of every recognised LED right.
- The photos sent for analysis are now colour PNGs for the colour frames, named `f0..`, `cal*`, and `v1_...` for the second view.
- **Not verified on a real device:** a 3d layout written to the garland (the 2d one is known to work), and the whole colour scan with a real phone camera.

## 0.15.2
- **Check frames in the scan** (a Hamming code over the bits of the Gray code): 4 more photos per scan (14 code frames for 600 LEDs instead of 10). Every LED gets its code checked: one wrongly read bit (a merged blob, a flicker, a reflection) is corrected, anything worse is rejected instead of ending up at a wrong place. In a synthetic scan with 3% of the bits read wrongly the number of wrongly placed LEDs went from 32 to 0 and the number of correctly found ones from 340 to 547 of 600.
- **Outlier filter**: after decoding and before the layout is built, a LED is dropped when its distance per index to both its previous and its next known neighbour is more than 5 times the typical step (the median distance between LEDs with consecutive numbers). Repeated until nothing more is dropped. In synthetic tests 83-96% of misplaced LEDs were caught with 1-4 good ones lost. The result shows the number of LEDs dropped, corrected and rejected by the check.

## 0.15.1
- **One garland for every preview.** A "Preview on" selector in the page header (remembered in the browser) sets the garland whose LED layout all pictures are drawn on: the library thumbnails, the effect editor, the formula previews (also live and replay; "Play live on the garland" plays on it) and the Scan tab. The separate selector of the effect editor is gone.
- **Scan photos can be sent for analysis.** After a scan (also a failed one) the Scan tab has a button that uploads its photos (lossless grey PNGs) and a small result file to the add-on (`api/scan/dump`, the last 4 scans are kept), so a scan that went wrong can be examined offline.

## 0.15.0
- **Scan types** (Scan tab, remembered per garland): *Flat wall or window* (as before: every LED is found, by code and then one by one), *Tree, one side (profile)* and a placeholder for *Tree, several sides* (planned, not selectable yet).
- **Tree, one side**: only the LEDs facing the camera can be seen, so 5% recognised by code is enough to go on (the flat scan needs 50%). The runs of LEDs that code did not recognise are probed along the string with a stride of 3: a run that shows nothing is the far side and is skipped, a run that shows LEDs is searched fully (this finds the LEDs that were merged in the photo). The LEDs that stay hidden are estimated along the string, a long hidden run between two far-apart visible ends is drawn as an arc round the back of the tree. The search area for single LEDs is stretched upwards, the search takes up to 400 photos (about 5 minutes) and can be cancelled. With a synthetic tree (600 LEDs on a helix, far side hidden) the mean position error of all LEDs was 1.6 px of a 430 px high tree.
- **A scan owns the garland**: while it runs, `api/play`, `api/live/play`, the periodic ensure and light commands from Home Assistant leave that device alone (`api/play` answers 409) instead of switching it under the camera.
- Fixed a stray `null` printed at the bottom of the Scan tab.

## 0.14.1
- **Fix: two garlands could not stream at the same time** (a position scan of one garland while a live scene played on the other failed with `Address in use`). The xled library binds its UDP socket to local port 7777, so only one client per process could send real-time frames. The add-on now uses a send-only socket without a fixed local port. This also removes a rare failure after the clients were recreated following a connection error.

## 0.14.0
- Three new live examples built on the signal quality of the radios in the house (Wi-Fi and Bluetooth in dBm, Zigbee link quality): **Signal towers live** (eight towers, height and colour follow the quality, weak ones flicker, strong ones send radio rings), **Zigbee mesh live** (five radiators as wave sources, waves interfere and mix colours) and **Signal stars live** (a night sky, strong signal is a big steady blue-white star, weak is a small flickering red one). The ranges are fixed (not auto), so the picture means something.

## 0.13.0
- **Watch and try the inputs** (Formulas tab, under the inputs table): a chart per input with the last 30 minutes of the sensor in its own units, the range that becomes 0..1 (your "→ 0" / "→ 1" or the auto range) as a shaded band, the value now as a dot, parts beyond the range in red and the events that would fire (your "event" threshold) as orange lines. Changing a number above redraws the chart at once.
- **By hand**: a slider and an event button per input. The preview starts by itself and the formula gets your value instead of the sensor (smoothing and events work as usual), so you see what each input does.
- **Replay the last 24 h**: plays the history of the inputs back fast (24 h in 45 s to 6 min, looping, with a clock) to see how a scene looks through a whole day. Inputs with an attribute have no history and keep their default.
- New API: `POST api/ha/history`, `POST api/live/preview/<id>/manual`, `replay` in `api/live/preview/start`.

## 0.12.0
- **Garlands as Home Assistant lights (MQTT discovery).** Set `mqtt_host`, `mqtt_port`, `mqtt_user`, `mqtt_password` in the add-on options (the user and password can be `!secret` references) and every configured device appears in Home Assistant as a `light` named after the device (`light.<device name>`, e.g. `light.balcony`): on/off, brightness, and an effect list made of the library effects, `random`, `live:random` and `live:<scene>`. Diagnostic sensors: live scene, fps, slowest ping, re-logins. Availability follows the add-on and the device. Without `mqtt_host` nothing changes.
- The add-on becomes the only client of the garlands, so the Home Assistant Twinkly integration can be removed (two clients fight for the device's single login token).

## 0.11.2
Smoother live scenes (a freeze / jerk every ~30 s and at every scene change was seen on the garland):
- **The token ping runs in its own thread, every 0.25 s** (was once a second inside the frame loop, blocking it). The device keeps one login token and the Home Assistant Twinkly integration logs in about every 30 s, which kills ours: the device ignores the frames until the ping notices (HTTP 401) and logs in again. The frame loop never waits for HTTP any more, and the freeze after a foreign login is about four times shorter. Status shows `ping_ms` / `ping_max_ms`.
- **Scene changes are handed over**: the next scene is built while the old one still plays, then the stream continues in real-time mode with no visit to the stored movie in between (there was a flash of the stored effect and a pause every time the automation switched scenes).
- A mode change by someone else is noticed within a ping (0.25 s).

## 0.11.1
- **Watchdog**: the add-on declares a health URL (`/api/health`, no calls to Home Assistant or the garlands) so the Supervisor can restart it when it hangs or dies. The Supervisor switch "Watchdog" has to be on (it is set through the Supervisor API after the update); at start the add-on switches a device left in real-time mode back to movie mode.
- **`live:random`**: plays one of the saved formulas that have inputs (live scenes), preferring another one than the current; a `live:<name>` that already plays on the device is kept instead of being restarted (so a periodic automation call does not restart the stream); the Formulas tab passes `restart: true` after you edit and press play. `POST api/live/play` got the `restart` flag.
- **Contrast and colours inside one picture**: Kaleidoscope (stained glass), Rings, Spiral, Mandala, Tunnel, Heartbeat, Comets and Pulse rings now give every region (a ring, an arm of the spiral, a piece of the kaleidoscope, a beat, a comet lane) its own hue far away from its neighbours (steps of ~137 degrees on the colour wheel, complementary colours in the Mandala), with dark seams between them, instead of one smooth gradient.
- **Live scenes were being muted by the anti-strobe limit** (330 per second per channel: a full swing took 0.77 s, so heart-beats and event flashes blurred into grey). It is now 900 per second (about 0.3 s for a full swing): fast flashes read clearly, a full-strength strobe above ~2 Hz is still impossible.
- Formula size limit raised (4000 characters, 900 operations) for the longer scenes.

## 0.11.0
Livelier live scenes. The sensors were not static (house power 324-2252 W changed every ~14 s, a PC's GPU 0-75 %, the network 0-58 Mbit/s): the old examples mapped them to too narrow ranges, smoothed them for seconds and used them for slow things.
- **Auto range** per input: the last 30 minutes of the sensor (fetched from the Home Assistant history at the start) are mapped to 0..1, so every sensor uses its whole range. Smoothing can be 0.3-0.5 s for fast signals; polling is now once a second.
- **Events**: every input also gives `<input>_kick` (1 at the moment of a jump, fading in ~1.5 s), `_age` (seconds since the last jump), `_count` (number of jumps, a seed for random places), `_dir` (+1 / -1) and `_delta` (speed of change). The jump size is set per input. One jump fires exactly one event.
- **New scenes**: "Spectrum live" (eight bars = CPU / power / GPU of the two PCs, network down and up, house power, falling caps), "Pulse rings live" (a ring is born at a random place at every jump of five signals), "Network comets live" (comets fall with the download and rise with the upload), "Heartbeat live" (the pulse follows the CPU load of both PCs). The old examples were retuned to fast signals and faster motion.
- The inputs table has an "auto" checkbox and an "event" threshold; the value chips show a lightning mark and the event count.
- Hardening: a formula function is now compiled from ordinary source text produced from the checked tree (instead of a hand-assembled AST); error messages keep the line the user wrote.

## 0.10.0
- **Live scenes on the garland.** A saved formula can be streamed to a garland in real-time mode (UDP, about 10-12 frames per second; a frame costs about 1 ms on a PC): button "Play live on the garland" in the Formulas tab, `POST api/live/play {scene, devices}`, or through the existing `rest_command` with `effect: "live:<formula name>"`. The scene follows Home Assistant values (smoothed, with the running phase) and never loops, so there is no seam.
- **Stopping and restoring.** "Stop", any explicit `play` of a stored effect or a Sync stops the stream and puts the garland back the way it was (the same stored movie, or off). The automation's `effect: "random"` does NOT cut a live scene short (answers `kept`). If somebody else changes the device mode (Home Assistant turns the light off, the phone app), the stream ends at once without fighting back; if the device stops answering or the formula fails, it ends and restores.
- **Crash safety.** A device left in real-time mode by a dead add-on (it freezes on the last frame) is switched back to movie mode when the add-on starts; the automation's next `random` restores it too.
- The device card shows the running live scene (fps, uptime, frame cost, token re-logins) with a Stop button; the Formulas tab shows a calm note instead of the seam warning for live-style formulas.
- Measured on the real garland: 10.6 fps for 70 s, about 2 token re-logins per minute (the Home Assistant Twinkly integration polling).

## 0.9.1
- **Geometry in formulas** (music-visualiser style): new helpers `rotx`/`roty` (rotation), `mirror` (fold an angle into n mirrored segments: kaleidoscope), `wrap` (tiling), `sat`; with `r` and `a` (distance and angle from the centre) rings, spirals, kaleidoscopes and mandalas are a few lines.
- **`<input>_phase`**: every input also gives its running total over time, so a speed that follows data (rotation, expansion) never jumps when the value changes.
- **Feedback with `prev(x, y)`** (the colour of the previous frame, interpolated between the LEDs): trails, zooming tunnels, fading, as in MilkDrop. Live scenes use the real previous frame; stored effects run one warm-up loop first.
- Five new examples bound to Home Assistant data: "Rings live" (more rings with house power, drift with wind, colours with the sun), "Kaleidoscope live", "Spiral live", "Tunnel live" (feedback), "Mandala live" (two flowers turning with the two work PCs).
- Fix: a crash risk in the interpreter (copying compiled functions for `prev` shared code between two global scopes); `prev` is now an ordinary argument.

## 0.9.0
- **Inputs from Home Assistant in formulas.** A formula can bind variables to entities (or their attributes): the value is mapped to 0..1 with a min/max range and smoothed over a chosen number of seconds. Table "Inputs from Home Assistant" in the Formulas tab with entity suggestions, the current raw and mapped value next to each input, and a new variable `now` (seconds since the start).
- **Live preview** in the browser: the server computes frames from the current Home Assistant values (about 8 per second), so you see the formula follow real data. Frame cost is about 10 ms for 600 LEDs.
- Live scenes limit how fast any colour channel can change (no strobing even if a formula asks for it) and keep the last value of an input that becomes unavailable.
- New example "House live": sky follows the sun, clouds follow cloud cover and wind, a warm glow rises with the radiator valve, the left/right half twinkle with the load of two PCs, the whole picture warms up with the power draw of the house.
- The add-on now asks for `homeassistant_api` (reads states through the Supervisor, no long-lived token). Stored effects use the default value of an input, so they stay deterministic.
- Streaming a live scene to the garland (real-time mode) is the next step.

## 0.8.0
- **Formula effects** (new tab "Formulas"): write the colour of every LED as a few lines of maths in `x`, `y`, loop time `t`, your own sliders, noise and palettes; live preview on the real layout, error messages with line numbers, a check that the loop is seamless, 6 examples. Saved formulas become generators ("<name> (formula)") usable in layers like the built-in ones. The language is a small safe subset (parsed with `ast`, whitelisted nodes only: no attributes, indexing, loops, imports or strings except palette names) with limits on size and render time.
- Fix: the flame texture drifted **down** (since 0.2.0); it now rises. Meteors flew up-left; they now fall along their direction with the tail behind.

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
