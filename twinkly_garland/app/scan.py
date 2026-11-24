"""LED position scan: drive the garland in real-time mode while a browser camera watches.

The browser asks for one pattern at a time (all dark, all on, Gray-code bit k, or a few
single LEDs), takes a photo and works out where every LED is. This module only lights the
patterns, keeps the real-time stream alive and restores the previous playback afterwards.
"""
import io
import json
import logging
import threading
import time
from datetime import datetime
from pathlib import Path

from . import device, live

log = logging.getLogger("twinkly.scan")
IDLE_TIMEOUT = 180  # s without a request: stop the scan and restore playback
_sess = None
_guard = threading.Lock()


def gray(i: int) -> int:
    return i ^ (i >> 1)


class Session:
    def __init__(self, dev: dict, inherit: tuple | None = None):
        self.dev = dev
        with device.lock_for(dev["host"]):
            self.ci = device.connect(dev["host"])
            self.profile, self.bytes_per_led = None, None
            try:
                info = device.retry(self.ci.get_device_info)
                self.n = int(info["number_of_led"])
                self.profile, self.bytes_per_led = info.get("led_profile"), info.get("bytes_per_led")
            except Exception:
                self.n = len(device.get_layout(dev))
            if inherit is not None:  # a live scene was streaming: what was on the garland before IT is what has to come back
                self.prev_mode, self.prev_uid = inherit
            else:
                self.prev_mode = device.retry(self.ci.get_mode).get("mode")
                try:
                    self.prev_uid = (device.retry(self.ci.get_movies_current).get("unique_id") or "").upper()
                except Exception:
                    self.prev_uid = ""
        self.frame = bytes(3 * self.n)
        self.lock = threading.Lock()
        self.wake = threading.Event()  # a new frame was set: send it now, do not wait for the next tick
        self.seq = 0   # number of the last frame set
        self.sent = 0  # number of the last frame that went out
        self.stop_evt = threading.Event()
        self.touched = time.time()
        self.playing = False  # a sequence is being played by play(): single patterns are refused meanwhile
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.ping_thread = threading.Thread(target=self._ping_loop, daemon=True)

    def _ping_loop(self):
        """Static frames stop rendering without an HTTP ping: one a second, in its own thread, so that a slow ping never delays a frame."""
        while not self.stop_evt.wait(1.0):
            try:
                with device.lock_for(self.dev["host"]):
                    self.ci.get_mode()
            except Exception as exc:
                log.warning("ping failed: %s", exc)

    def _run(self):
        try:
            with device.lock_for(self.dev["host"]):
                device.retry(self.ci.set_mode, "rt")
            while not self.stop_evt.is_set() and time.time() - self.touched < IDLE_TIMEOUT:
                with self.lock:
                    frame, seq = self.frame, self.seq
                try:
                    self.ci.set_rt_frame_socket(io.BytesIO(frame), 3)  # no HTTP lock: the token is only read (the live stream does the same)
                except Exception as exc:
                    log.warning("rt frame failed: %s", exc)
                self.sent = seq
                self.wake.wait(0.15)
                self.wake.clear()
        finally:
            self._restore()

    def _restore(self):
        try:
            with device.lock_for(self.dev["host"]):
                if self.prev_mode == "movie" and self.prev_uid:
                    device._select(self.ci, self.prev_uid)
                else:
                    device.retry(self.ci.set_mode, self.prev_mode or "off")
        except Exception as exc:
            log.warning("restore failed: %s", exc)
        device.scanning_hosts.discard(self.dev["host"])
        global _sess
        with _guard:
            if _sess is self:
                _sess = None
        log.info("scan session closed")

    def set_frame(self, frame: bytes) -> int:
        with self.lock:
            self.frame = frame
            self.seq += 1
            seq = self.seq
        self.touched = time.time()
        self.wake.set()
        return seq

    def wait_sent(self, seq: int, timeout: float = 0.6):
        """Waits until the frame `seq` (or a later one) has been sent to the device."""
        end = time.time() + timeout
        while self.sent < seq and time.time() < end and not self.stop_evt.is_set():
            time.sleep(0.005)


def current() -> "Session | None":
    return _sess


def start(dev: dict) -> dict:
    global _sess
    with _guard:
        if _sess is not None:
            raise RuntimeError("a scan is already running")
        if dev["host"] in device.scanning_hosts:
            raise RuntimeError("a scan is already running")
        device.scanning_hosts.add(dev["host"])
    # A live scene of the add-on that is still streaming to this garland would send its frames at the same time as the scan and the garland would
    # show a mix of both (the picture never calms down, red and blue run into each other): stop it, without restoring anything (the scan
    # restores what was on the garland before the live scene when it ends).
    inherit = None
    st = device.live_hosts.get(dev["host"])
    if st is not None:
        inherit = (st.prev_mode, st.prev_uid)
        log.info("stopping the live scene %s on %s for the scan", st.name, dev["name"])
        live.stop_for(dev, restore=False)
    try:
        s = Session(dev, inherit)
    except Exception:
        device.scanning_hosts.discard(dev["host"])
        raise
    with _guard:
        _sess = s
    s.thread.start()
    s.ping_thread.start()
    time.sleep(0.4)  # let the first (dark) frame go out
    return {"leds": s.n, "bits": max(1, (s.n - 1).bit_length()), "profile": s.profile, "bytes_per_led": s.bytes_per_led}


def _show(s: "Session", frame: bytes):
    """Sends the frame at once and returns when it is out and the device has had a moment to light it
    (the browser then waits for the camera to see it)."""
    s.wait_sent(s.set_frame(frame))
    time.sleep(0.06)


def _frame(s: "Session", kind: str, bit: int = 0, leds=(), level: int = 200, channels=()) -> tuple:
    """The bytes of a pattern and the number of LEDs that are lit."""
    level = min(255, max(1, int(level)))
    n = s.n
    if kind == "dark":
        return bytes(3 * n), 0
    if kind == "all":
        return bytes((level, level, level)) * n, n
    if kind == "bit":
        lit = [(gray(i) >> bit) & 1 for i in range(n)]
        return b"".join(bytes((level, level, level)) if p else bytes(3) for p in lit), sum(lit)
    if kind == "leds":
        chosen = {int(i) for i in leds if 0 <= int(i) < n}
        return b"".join(bytes((level, level, level)) if i in chosen else bytes(3) for i in range(n)), len(chosen)
    if kind == "rgb":  # colour code frame: channels = [LEDs lit in red, in green, in blue]
        if len(channels) != 3:
            raise ValueError("rgb pattern needs three lists of LEDs")
        sets = [{int(i) for i in ch if 0 <= int(i) < n} for ch in channels]
        return b"".join(bytes(level if i in sets[c] else 0 for c in range(3)) for i in range(n)), len(sets[0] | sets[1] | sets[2])
    raise ValueError(f"unknown pattern {kind!r}")


def pattern(kind: str, bit: int = 0, leds: list = (), level: int = 200, channels: list = ()) -> dict:
    s = _sess
    if s is None:
        raise RuntimeError("no scan is running")
    if s.playing:
        raise RuntimeError("a sequence is playing")
    frame, lit = _frame(s, kind, bit, leds, level, channels)
    _show(s, frame)
    return {"ok": True, "lit": lit}


def play(steps: list, slot_ms: int = 240, lead_ms: int = 700) -> dict:
    """Plays a sequence of patterns by itself, one every `slot_ms`, the first after `lead_ms` (the page films it: no round trip per
    pattern). Each step is {kind, bit, leds, level, channels} like pattern(). The frames are built first, then a thread sets them on time
    (the sender thread puts every new frame on the wire at once)."""
    s = _sess
    if s is None:
        raise RuntimeError("no scan is running")
    if s.playing:
        raise RuntimeError("a sequence is already playing")
    if not 1 <= len(steps) <= 80:
        raise ValueError("a sequence has 1 to 80 steps")
    slot_ms, lead_ms = int(min(2000, max(60, slot_ms))), int(min(5000, max(0, lead_ms)))
    frames = [_frame(s, st.get("kind", "dark"), st.get("bit", 0), st.get("leds", ()), st.get("level", 200), st.get("channels", ()))[0] for st in steps]
    s.playing = True
    s.touched = time.time()

    def run():
        try:
            t0 = time.perf_counter() + lead_ms / 1000.0
            for k, fr in enumerate(frames):
                target = t0 + k * slot_ms / 1000.0
                while not s.stop_evt.is_set():
                    d = target - time.perf_counter()
                    if d <= 0:
                        break
                    time.sleep(min(d, 0.005))
                if s.stop_evt.is_set():
                    return
                s.set_frame(fr)
            time.sleep(slot_ms / 1000.0)  # the last pattern gets its slot too
        finally:
            s.playing = False

    threading.Thread(target=run, daemon=True).start()
    return {"slots": len(frames), "slot_ms": slot_ms, "lead_ms": lead_ms, "duration_ms": lead_ms + slot_ms * len(frames)}


def stop() -> dict:
    s = _sess
    if s is None:
        return {"stopped": False}
    s.stop_evt.set()
    s.wake.set()
    s.thread.join(timeout=15)
    s.ping_thread.join(timeout=5)
    return {"stopped": True}


def state() -> dict:
    s = _sess
    return {"running": s is not None, "device": s.dev["name"] if s else None, "leds": s.n if s else None, "playing": bool(s and s.playing)}


def apply_layout(dev: dict, coords: list, scan_type: str = "flat") -> dict:
    """Back up the current layout, write the new one to the device and refresh the cache.
    Coordinates with z (a tree scanned from two sides) are written as a 3d layout, the others as 2d."""
    if dev["host"] in device.scanning_hosts:
        raise RuntimeError("stop the scan first")
    old = device.get_layout(dev, refresh=True)
    if len(coords) != len(old):
        raise ValueError(f"expected {len(old)} coordinates, got {len(coords)}")
    clean = []
    three = bool(coords) and all("z" in c for c in coords)
    z0 = old[0].get("z", 0) if old else 0
    for c in coords:
        x, y = float(c["x"]), float(c["y"])
        z = float(c["z"]) if three else z0
        if not (-10 < x < 10 and -10 < y < 10 and -10 < z < 10):
            raise ValueError("coordinate out of range")
        clean.append({"x": round(x, 6), "y": round(y, 6), "z": round(z, 6) if three else z})
    backup = _save_backup(dev, old)
    new = _write_layout(dev, clean, three)
    log.info("layout of %s written (%s scan, %s, %d LEDs)", dev["name"], scan_type, "3d" if three else "2d", len(new))
    return {"leds": len(new), "backup": backup.name}


def _save_backup(dev: dict, layout: list) -> "Path":
    folder = device.DATA_DIR / "layouts"
    folder.mkdir(parents=True, exist_ok=True)
    backup = folder / f"{dev['name']}.backup-{datetime.now():%Y%m%d-%H%M%S}.json"
    backup.write_text(json.dumps(layout))
    return backup


def _plain(v: float) -> float:
    """A number that the garland reads right. JSON from Python writes anything under 0.0001 in the exponent form (2.2e-05) and the firmware of the
    garland drops the exponent: 2.2e-05 came out as 2.2 and put a LED two (or five) widths of the tree away from where it was (in two real scans:
    LEDs on the centre line of the picture, whose x is nearly 0). Such a number is written as 0.0."""
    v = float(v)
    return 0.0 if abs(v) < 1e-4 else round(v, 6)


def _write_layout(dev: dict, clean: list, three: bool) -> list:
    clean = [{k: _plain(p[k]) for k in ("x", "y", "z")} for p in clean]
    with device.lock_for(dev["host"]):
        device.retry(device.connect(dev["host"]).set_led_layout, "3d" if three else "2d", clean)
    return device.get_layout(dev, refresh=True)


def list_backups(dev: dict) -> list:
    """The saved layouts of a garland, newest first (every write of a scan or a restore saves the layout it replaces)."""
    folder, prefix, out = device.DATA_DIR / "layouts", f"{dev['name']}.backup-", []
    if folder.is_dir():
        for f in folder.iterdir():
            if f.name.startswith(prefix) and f.name.endswith(".json"):
                try:
                    n = len(json.loads(f.read_text()))
                except (OSError, ValueError):
                    continue
                t = f.name[len(prefix):-5]
                out.append({"name": f.name, "time": f"{t[:4]}-{t[4:6]}-{t[6:8]} {t[9:11]}:{t[11:13]}:{t[13:15]}", "leds": n})
    return sorted(out, key=lambda b: b["name"], reverse=True)


def restore_layout(dev: dict, backup: str) -> dict:
    """Writes a saved layout back to the garland (the layout it replaces is saved first, so a restore can be undone).
    The saved file keeps only x, y, z: a layout with z different from 0 goes back as 3d, the others as 2d."""
    if dev["host"] in device.scanning_hosts:
        raise RuntimeError("stop the scan first")
    if "/" in backup or "\\" in backup or not backup.startswith(f"{dev['name']}.backup-") or not backup.endswith(".json"):
        raise ValueError("bad backup name")
    f = device.DATA_DIR / "layouts" / backup
    if not f.is_file():
        raise ValueError("no such backup")
    coords = json.loads(f.read_text())
    cur = device.get_layout(dev, refresh=True)
    if len(coords) != len(cur):
        raise ValueError(f"the backup has {len(coords)} LEDs, the garland {len(cur)}")
    three = any(abs(float(c.get("z", 0))) > 1e-9 for c in coords)
    clean = [{"x": round(float(c["x"]), 6), "y": round(float(c["y"]), 6), "z": round(float(c.get("z", 0)), 6)} for c in coords]
    saved = _save_backup(dev, cur)
    new = _write_layout(dev, clean, three)
    log.info("layout of %s restored from %s (%s, %d LEDs)", dev["name"], backup, "3d" if three else "2d", len(new))
    return {"leds": len(new), "restored": backup, "saved_current_as": saved.name}
