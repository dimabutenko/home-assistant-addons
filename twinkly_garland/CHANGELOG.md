# Changelog

## 0.3.0
- `POST api/play` accepts `effect: "random"` (one key common to all target devices) and returns 502 when nothing could be played.

## 0.2.0
- Effect generator `flame` (seamless loop, parametric) and the effect editor with browser preview on the real LED layout.
- Ensure/reconcile layer: content-hashed movie ids, plan (dry run), rebuild on drift, optional periodic auto-ensure.
- `POST api/play` resolves an effect key to the right movie per device.

## 0.1.0
- Scaffold: ingress web page listing configured devices, firmware and stored movies.
