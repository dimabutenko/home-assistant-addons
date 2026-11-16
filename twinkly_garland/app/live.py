"""Live scenes: a formula evaluated frame by frame with the current values of Home Assistant inputs."""
import io
import logging
import math
import threading
import time

from . import device, formula, hadata

log = logging.getLogger("twinkly.live")

MAX_SLEW = 330.0  # max change of a colour channel per second (0..255): no strobing even if a formula asks for it
LOOP_S = 10.0     # `t` runs 0..1 over this many seconds in live mode


class LiveScene:
    def __init__(self, spec: dict, layout: list, params: dict | None = None, source=None):
        self.spec = formula.validate_item({"name": "live", **spec})
        self.params = dict(params or {})
        defs, self.inputs = self.spec["params"], self.spec["inputs"]
        self.fn = formula.compile_formula(self.spec["code"], formula.all_names(defs, self.inputs))
        self.prep = formula.Prepared(layout)
        self.pvals = [float(self.params.get(d["name"], d["default"])) for d in defs]
        self.k = float(self.params.get("intensity", 0.9))
        self.seed = float(self.params.get("seed", 1))
        self.prevfn, self.fb = formula.make_prev(self.prep, self.k)  # prev(x, y) reads the previous frame
        self.phase = {i["name"]: 0.0 for i in self.inputs}
        self.loop = float(self.params.get("loop", LOOP_S))
        self.source = source or hadata.read_input  # (input) -> (raw, normalized) | (None, None)
        self.smoothed = {i["name"]: float(i["default"]) for i in self.inputs}
        self.raw = {i["name"]: None for i in self.inputs}
        self.t0 = time.time()
        self.last = None
        self.prev = None

    def _update_inputs(self, dt: float):
        for inp in self.inputs:
            raw, norm = self.source(inp)
            self.raw[inp["name"]] = raw
            if norm is None:
                continue  # unavailable: keep the last value
            a = 1.0 if inp["smooth"] <= 0.01 else 1 - math.exp(-dt / inp["smooth"])
            self.smoothed[inp["name"]] += (norm - self.smoothed[inp["name"]]) * a
        for inp in self.inputs:  # running total of the value: a speed that follows data without jumps
            self.phase[inp["name"]] += self.smoothed[inp["name"]] * dt

    def values(self) -> dict:
        return {i["name"]: {"raw": self.raw[i["name"]], "value": round(self.smoothed[i["name"]], 3)} for i in self.inputs}

    def frame(self, now: float | None = None) -> bytes:
        now = time.time() if now is None else now
        dt = 0.1 if self.last is None else max(0.001, min(2.0, now - self.last))
        self.last = now
        self._update_inputs(dt)
        el = now - self.t0
        vals = self.pvals + [self.smoothed[i["name"]] for i in self.inputs] + [self.phase[i["name"]] for i in self.inputs]
        out = formula.eval_frame(self.fn, self.prep, (el / self.loop) % 1.0, el, self.seed, vals, self.k, self.prevfn)
        if self.prev is not None:
            lim = max(1, int(MAX_SLEW * dt))
            out = bytes(p + max(-lim, min(lim, c - p)) for p, c in zip(self.prev, out))
        self.prev = out
        self.fb["frame"] = out
        return out


class _Relogins(logging.Handler):
    """Counts the 401 answers xled logs when another client took the device's single login token."""
    def __init__(self):
        super().__init__()
        self.count = 0

    def emit(self, record):
        if "401" in record.getMessage():
            self.count += 1


_relogins = _Relogins()
logging.getLogger("xled.auth").addHandler(_relogins)


class LiveStream:
    """Streams the frames of a LiveScene to a garland in real-time mode (UDP), and puts the garland back
    the way it was when the stream ends. If somebody else changes the mode of the device (Home Assistant
    turns the light off, the phone app), the stream ends without fighting back."""

    def __init__(self, dev: dict, scene: LiveScene, name: str, fps: float = 12.0):
        self.dev, self.scene, self.name = dev, scene, name
        self.interval = 1.0 / max(2.0, min(25.0, fps))
        self.stop_evt = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.restore = True
        self.ended = None          # why the stream ended, if it did
        self.frames = 0
        self.fps_actual = 0.0
        self.compute_ms = 0.0
        self.relogins0 = 0
        self.prev_mode = None
        self.prev_uid = ""
        self.ci = None
        self.started = None

    # -- control ------------------------------------------------------------------------------------------
    def start(self):
        host = self.dev["host"]
        with device.lock_for(host):
            if host in device.scanning_hosts:
                raise RuntimeError("a position scan is running")
            self.ci = device.connect(host)
            self.prev_mode = device.retry(self.ci.get_mode).get("mode")
            try:
                self.prev_uid = (device.retry(self.ci.get_movies_current).get("unique_id") or "").upper()
            except Exception:
                self.prev_uid = ""
            device.retry(self.ci.set_mode, "rt")
        device.live_hosts[host] = self
        self.relogins0 = _relogins.count
        self.started = time.time()
        self.thread.start()

    def stop(self, restore: bool = True):
        self.restore = self.restore and restore
        self.stop_evt.set()
        if self.thread.is_alive() and threading.current_thread() is not self.thread:
            self.thread.join(timeout=15)

    def status(self) -> dict:
        return {"device": self.dev["name"], "scene": self.name, "fps": round(self.fps_actual, 1), "frames": self.frames,
                "compute_ms": round(self.compute_ms, 1), "relogins": _relogins.count - self.relogins0,
                "seconds": round(time.time() - (self.started or time.time())), "ended": self.ended, "values": self.scene.values()}

    # -- the loop -----------------------------------------------------------------------------------------------
    def _run(self):
        host, last_ping, errors, t_fps, n_fps = self.dev["host"], 0.0, 0, time.time(), 0
        try:
            while not self.stop_evt.is_set():
                t0 = time.time()
                try:
                    frame = self.scene.frame()
                except formula.FormulaError as exc:
                    self.ended = f"the formula failed: {exc}"
                    break
                self.compute_ms = self.compute_ms * 0.9 + (time.time() - t0) * 1000 * 0.1
                try:
                    with device.lock_for(host):
                        self.ci.set_rt_frame_socket(io.BytesIO(frame), 3)
                        if time.time() - last_ping > 1.0:  # static frames stop rendering without an HTTP ping
                            mode = self.ci.get_mode().get("mode")
                            last_ping = time.time()
                            if mode != "rt":
                                self.ended = f"the mode was changed to {mode!r} by someone else"
                                self.restore = False
                                break
                    errors = 0
                except Exception as exc:
                    errors += 1
                    if errors > 25:
                        self.ended = f"the device does not answer ({type(exc).__name__})"
                        self.restore = False
                        break
                self.frames += 1
                n_fps += 1
                if time.time() - t_fps >= 2.0:
                    self.fps_actual, t_fps, n_fps = n_fps / (time.time() - t_fps), time.time(), 0
                self.stop_evt.wait(max(0.0, self.interval - (time.time() - t0)))
        finally:
            device.live_hosts.pop(host, None)
            if self.restore:
                self._restore()
            log.info("live stream %s on %s ended (%s)", self.name, self.dev["name"], self.ended or "stopped")

    def _restore(self):
        try:
            with device.lock_for(self.dev["host"]):
                if self.prev_mode == "movie" and self.prev_uid:
                    device._select(self.ci, self.prev_uid)
                else:
                    device.retry(self.ci.set_mode, self.prev_mode or "off")
        except Exception as exc:
            log.warning("restore after the live stream failed: %s", exc)


def stop_for(dev: dict, restore: bool = True) -> bool:
    """Stop the live stream of a device, if any."""
    st = device.live_hosts.get(dev["host"])
    if st is None:
        return False
    st.stop(restore)
    return True
