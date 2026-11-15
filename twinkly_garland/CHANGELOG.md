# Changelog

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
