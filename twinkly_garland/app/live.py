"""Live scenes: a formula evaluated frame by frame with the current values of Home Assistant inputs."""
import io
import logging
import math
import threading
import time

from . import device, formula, hadata

log = logging.getLogger("twinkly.live")

MAX_SLEW = 900.0  # max change of a colour channel per second (0..255): a full swing takes ~0.3 s, so no strobing even if a formula asks for it
LOOP_S = 10.0     # `t` runs 0..1 over this many seconds in live mode


class InputTracker:
    """Everything a formula can know about one input: the smoothed 0..1 value (with an auto range if wanted),
    its running phase, and event signals (kick, age, count, direction, speed of change)."""
    EVENT_TAU = 1.2   # a kick fades in about this many seconds
    BASE_TAU = 5.0    # the slow baseline a jump is measured against
    WARM = 4.0        # no events while the auto range settles after the start
    WINDOW_S = 1800.0

    def __init__(self, inp: dict, now: float):
        self.inp, self.t_start = inp, now
        self.auto = bool(inp.get("auto"))
        self.thr = float(inp.get("kick", 0.12))
        self.win = []          # (time, raw) once a second
        self.last_sample = -1e9
        self.lo = self.hi = None
        self.raw = None
        self.value = float(inp["default"])
        self.base = None
        self.kick, self.age, self.count, self.dir, self.delta, self.phase = 0.0, 120.0, 0, 0, 0.0, 0.0
        self.prev_v = None
        self.last_evt = -1e9
        self.manual = None     # a value 0..1 set by hand (the sliders of the editor) instead of the sensor

    def fire(self, now: float, direction: int = 1):
        """An event on demand (the kick button of the editor)."""
        self.kick, self.dir, self.age, self.last_evt = 0.9, direction, 0.0, now
        self.count += 1

    def seed(self, values: list, now: float):
        """History from Home Assistant: the auto range is useful from the first frame."""
        if not values:
            return
        step = self.WINDOW_S / len(values)
        self.win = [(now - self.WINDOW_S + (i + 1) * step, v) for i, v in enumerate(values)]
        self._range()

    def _range(self):
        vals = [v for _, v in self.win]
        self.lo, self.hi = (min(vals), max(vals)) if vals else (None, None)

    def _norm(self, raw: float) -> float:
        inp = self.inp
        if self.auto and self.lo is not None:
            span = max(float(inp.get("span") or 0.0), abs(inp["max"] - inp["min"]) * 0.05, 1e-9)
            lo, hi = self.lo, self.hi
            if hi - lo < span:
                mid = (hi + lo) / 2
                lo, hi = mid - span / 2, mid + span / 2
            return min(1.0, max(0.0, (raw - lo) / (hi - lo)))
        return min(1.0, max(0.0, (raw - inp["min"]) / (inp["max"] - inp["min"])))

    def update(self, raw, dt: float, now: float):
        inp = self.inp
        target = None
        if self.manual is not None:
            target = self.manual
            self.raw = inp["min"] + target * (inp["max"] - inp["min"])
            a = 1.0 if inp["smooth"] <= 0.01 else 1 - math.exp(-dt / inp["smooth"])
            self.value += (target - self.value) * a
        elif raw is not None:
            self.raw = raw
            if self.auto and now - self.last_sample >= 1.0:
                self.last_sample = now
                self.win.append((now, raw))
                while self.win and now - self.win[0][0] > self.WINDOW_S:
                    self.win.pop(0)
                self._range()
            target = self._norm(raw)
            a = 1.0 if inp["smooth"] <= 0.01 else 1 - math.exp(-dt / inp["smooth"])
            self.value += (target - self.value) * a
        v = self.value
        if self.base is None:
            self.base = target if target is not None else v
        # events are measured on the raw target, not on the smoothed value (which is still catching up after a jump)
        jump = (target - self.base) if target is not None else 0.0
        if now - self.t_start > self.WARM and abs(jump) > self.thr and now - self.last_evt > 0.8:
            self.kick = min(1.0, 0.45 + abs(jump) * 1.2)
            self.dir = 1 if jump > 0 else -1
            self.count += 1
            self.age = 0.0
            self.last_evt = now
            self.base = target
        else:
            if target is not None:
                self.base += (target - self.base) * (1 - math.exp(-dt / self.BASE_TAU))
            self.kick *= math.exp(-dt / self.EVENT_TAU)
            self.age = min(120.0, self.age + dt)
        if self.prev_v is not None:
            self.delta += ((v - self.prev_v) / dt - self.delta) * (1 - math.exp(-dt / 0.5))
        self.prev_v = v
        self.phase += v * dt


class LiveScene:
    def __init__(self, spec: dict, layout: list, params: dict | None = None, source=None, history=None):
        self.spec = formula.validate_item({"name": "live", **spec})
        self.params = dict(params or {})
        defs, self.inputs = self.spec["params"], self.spec["inputs"]
        self.fn = formula.compile_formula(self.spec["code"], formula.all_names(defs, self.inputs))
        self.prep = formula.Prepared(layout)
        self.pvals = [float(self.params.get(d["name"], d["default"])) for d in defs]
        self.k = float(self.params.get("intensity", 0.9))
        self.seed = float(self.params.get("seed", 1))
        self.prevfn, self.fb = formula.make_prev(self.prep, self.k)  # prev(x, y) reads the previous frame
        self.loop = float(self.params.get("loop", LOOP_S))
        self.source = source or hadata.read_input  # (input) -> (raw, normalized) | (None, None)
        self.t0 = time.time()
        self.last = None
        self.prev = None
        self.trk = {i["name"]: InputTracker(i, self.t0) for i in self.inputs}
        history = history if history is not None else self._ha_history
        for i in self.inputs:  # an auto range starts from the last half hour instead of from nothing
            if i.get("auto") and not i.get("attribute"):
                try:
                    self.trk[i["name"]].seed(history(i), self.t0)
                except Exception as exc:
                    log.info("no history for %s: %s", i["entity"], exc)

    @staticmethod
    def _ha_history(inp: dict) -> list:
        return hadata.history(inp["entity"], InputTracker.WINDOW_S / 60) if hadata.available() else []

    def _update_inputs(self, dt: float, now: float):
        for inp in self.inputs:
            raw, _norm = self.source(inp)
            self.trk[inp["name"]].update(raw, dt, now)

    def set_manual(self, name: str, value) -> None:
        self.trk[name].manual = None if value is None else min(1.0, max(0.0, float(value)))

    def fire(self, name: str) -> None:
        self.trk[name].fire(time.time())

    def values(self) -> dict:
        return {n: {"raw": t.raw, "value": round(t.value, 3), "kick": round(t.kick, 2), "count": t.count} for n, t in self.trk.items()}

    def frame(self, now: float | None = None) -> bytes:
        now = time.time() if now is None else now
        dt = 0.1 if self.last is None else max(0.001, min(2.0, now - self.last))
        self.last = now
        self._update_inputs(dt, now)
        el = now - self.t0
        T = [self.trk[i["name"]] for i in self.inputs]
        vals = (self.pvals + [t.value for t in T] + [t.phase for t in T] + [t.kick for t in T] + [t.age for t in T]
                + [float(t.count) for t in T] + [float(t.dir) for t in T] + [max(-3.0, min(3.0, t.delta)) for t in T])
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
    turns the light off, the phone app), the stream ends without fighting back.

    Two threads: the frame loop only sends UDP packets (never waits for HTTP), the ping loop asks the device for
    its mode every 0.25 s. The device keeps ONE login token: when another client logs in (the Home Assistant Twinkly
    integration polls about every 30 s) our token dies, the device ignores our frames, and the ping notices it
    (HTTP 401), logs in again and the picture continues. A quick ping keeps that freeze short."""

    PING_S = 0.25

    def __init__(self, dev: dict, scene: LiveScene, name: str, fps: float = 8.0):
        self.dev, self.scene, self.name = dev, scene, name
        self.interval = 1.0 / max(2.0, min(25.0, fps))
        self.stop_evt = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.ping_thread = threading.Thread(target=self._ping_loop, daemon=True)
        self.restore = True
        self.ended = None          # why the stream ended, if it did
        self.frames = 0
        self.fps_actual = 0.0
        self.compute_ms = 0.0
        self.ping_ms = 0.0
        self.ping_max_ms = 0.0     # slowest ping of the last ~minute (a re-login shows up here)
        self._ping_peaks = []
        self.relogins0 = 0
        self.prev_mode = None
        self.prev_uid = ""
        self.ci = None
        self.started = None

    # -- control ------------------------------------------------------------------------------------------
    def start(self, inherit: tuple | None = None):
        """`inherit` = (mode, movie uid) of the stream this one replaces: the device is already streaming, so the
        scene changes without a visit to the stored movie in between."""
        host = self.dev["host"]
        with device.lock_for(host):
            if host in device.scanning_hosts:
                raise RuntimeError("a position scan is running")
            self.ci = device.connect(host)
            if inherit is not None:
                self.prev_mode, self.prev_uid = inherit
            else:
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
        self.ping_thread.start()

    def stop(self, restore: bool = True):
        self.restore = self.restore and restore
        self.stop_evt.set()
        me = threading.current_thread()
        for th in (self.thread, self.ping_thread):
            if th.is_alive() and th is not me:
                th.join(timeout=15)

    def status(self) -> dict:
        return {"device": self.dev["name"], "scene": self.name, "fps": round(self.fps_actual, 1), "frames": self.frames,
                "engine": "numpy" if getattr(self.scene.fn, "vec", None) is not None else "scalar", "compute_ms": round(self.compute_ms, 1), "ping_ms": round(self.ping_ms), "ping_max_ms": round(self.ping_max_ms),
                "relogins": _relogins.count - self.relogins0, "seconds": round(time.time() - (self.started or time.time())),
                "ended": self.ended, "values": self.scene.values()}

    # -- the frame loop: UDP only -----------------------------------------------------------------------------------
    def _run(self):
        host, errors, t_fps, n_fps = self.dev["host"], 0, time.time(), 0
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
                    self.ci.set_rt_frame_socket(io.BytesIO(frame), 3)  # no HTTP lock: the token is only read
                    errors = 0
                except Exception as exc:  # e.g. the token is being renewed right now
                    errors += 1
                    if errors > 60:
                        self.ended = f"frames cannot be sent ({type(exc).__name__})"
                        self.restore = False
                        break
                self.frames += 1
                n_fps += 1
                if time.time() - t_fps >= 2.0:
                    self.fps_actual, t_fps, n_fps = n_fps / (time.time() - t_fps), time.time(), 0
                self.stop_evt.wait(max(0.0, self.interval - (time.time() - t0)))
        finally:
            self.stop_evt.set()
            if self.ping_thread.is_alive() and self.ping_thread is not threading.current_thread():
                self.ping_thread.join(timeout=5)
            if device.live_hosts.get(host) is self:
                device.live_hosts.pop(host, None)
            if self.restore:
                self._restore()
            log.info("live stream %s on %s ended (%s)", self.name, self.dev["name"], self.ended or "stopped")

    # -- the ping loop: keeps the token alive, notices a mode change by someone else ----------------------------------------
    def _ping_loop(self):
        host, errors = self.dev["host"], 0
        while not self.stop_evt.is_set():
            t0 = time.time()
            try:
                with device.lock_for(host):
                    mode = self.ci.get_mode().get("mode")
                errors = 0
                self.ping_ms = (time.time() - t0) * 1000
                self._ping_peaks = [(t, v) for t, v in self._ping_peaks if t0 - t < 60] + [(t0, self.ping_ms)]
                self.ping_max_ms = max(v for _, v in self._ping_peaks)
                if mode != "rt":
                    self.ended = f"the mode was changed to {mode!r} by someone else"
                    self.restore = False
                    self.stop_evt.set()
                    break
            except Exception as exc:
                errors += 1
                if errors > 40:  # about 10 s without an answer
                    self.ended = f"the device does not answer ({type(exc).__name__})"
                    self.restore = False
                    self.stop_evt.set()
                    break
            self.stop_evt.wait(max(0.0, self.PING_S - (time.time() - t0)))

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
