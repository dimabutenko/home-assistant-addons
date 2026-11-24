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

from . import device

log = logging.getLogger("twinkly.scan")
IDLE_TIMEOUT = 180  # s without a request: stop the scan and restore playback
_sess = None
_guard = threading.Lock()


def gray(i: int) -> int:
    return i ^ (i >> 1)


class Session:
    def __init__(self, dev: dict):
        self.dev = dev
        with device.lock_for(dev["host"]):
            self.ci = device.connect(dev["host"])
            try:
                self.n = int(device.retry(self.ci.get_device_info)["number_of_led"])
            except Exception:
                self.n = len(device.get_layout(dev))
            self.prev_mode = device.retry(self.ci.get_mode).get("mode")
            try:
                self.prev_uid = (device.retry(self.ci.get_movies_current).get("unique_id") or "").upper()
            except Exception:
                self.prev_uid = ""
        self.frame = bytes(3 * self.n)
        self.lock = threading.Lock()
        self.stop_evt = threading.Event()
        self.touched = time.time()
        self.thread = threading.Thread(target=self._run, daemon=True)

    def _run(self):
        last_ping = 0.0
        try:
            with device.lock_for(self.dev["host"]):
                device.retry(self.ci.set_mode, "rt")
            while not self.stop_evt.is_set() and time.time() - self.touched < IDLE_TIMEOUT:
                with self.lock:
                    frame = self.frame
                try:
                    with device.lock_for(self.dev["host"]):
                        self.ci.set_rt_frame_socket(io.BytesIO(frame), 3)
                        if time.time() - last_ping > 1.0:  # static frames stop rendering without an HTTP ping
                            self.ci.get_mode()
                            last_ping = time.time()
                except Exception as exc:
                    log.warning("rt frame failed: %s", exc)
                self.stop_evt.wait(0.15)
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

    def set_frame(self, frame: bytes):
        with self.lock:
            self.frame = frame
        self.touched = time.time()


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
    try:
        s = Session(dev)
    except Exception:
        device.scanning_hosts.discard(dev["host"])
        raise
    with _guard:
        _sess = s
    s.thread.start()
    time.sleep(0.4)  # let the first (dark) frame go out
    return {"leds": s.n, "bits": max(1, (s.n - 1).bit_length())}


def pattern(kind: str, bit: int = 0, leds: list = (), level: int = 200) -> dict:
    s = _sess
    if s is None:
        raise RuntimeError("no scan is running")
    level = min(255, max(1, int(level)))
    on = (level, level, level)
    n = s.n
    if kind == "dark":
        px = [0] * n
    elif kind == "all":
        px = [1] * n
    elif kind == "bit":
        px = [(gray(i) >> bit) & 1 for i in range(n)]
    elif kind == "leds":
        chosen = {int(i) for i in leds if 0 <= int(i) < n}
        px = [1 if i in chosen else 0 for i in range(n)]
    else:
        raise ValueError(f"unknown pattern {kind!r}")
    frame = b"".join(bytes(on) if p else b"\x00\x00\x00" for p in px)
    s.set_frame(frame)
    time.sleep(0.25)  # the stream resends every 0.15 s: make sure the device has rendered it
    return {"ok": True, "lit": sum(px)}


def stop() -> dict:
    s = _sess
    if s is None:
        return {"stopped": False}
    s.stop_evt.set()
    s.thread.join(timeout=15)
    return {"stopped": True}


def state() -> dict:
    s = _sess
    return {"running": s is not None, "device": s.dev["name"] if s else None, "leds": s.n if s else None}


def apply_layout(dev: dict, coords: list, scan_type: str = "flat") -> dict:
    """Back up the current layout, write the new one to the device and refresh the cache."""
    if dev["host"] in device.scanning_hosts:
        raise RuntimeError("stop the scan first")
    old = device.get_layout(dev, refresh=True)
    if len(coords) != len(old):
        raise ValueError(f"expected {len(old)} coordinates, got {len(coords)}")
    clean = []
    z = old[0].get("z", 0) if old else 0
    for c in coords:
        x, y = float(c["x"]), float(c["y"])
        if not (-10 < x < 10 and -10 < y < 10):
            raise ValueError("coordinate out of range")
        clean.append({"x": round(x, 6), "y": round(y, 6), "z": z})
    backup = device.DATA_DIR / "layouts" / f"{dev['name']}.backup-{datetime.now():%Y%m%d-%H%M%S}.json"
    backup.write_text(json.dumps(old))
    with device.lock_for(dev["host"]):
        device.retry(device.connect(dev["host"]).set_led_layout, "2d", clean)
    new = device.get_layout(dev, refresh=True)
    log.info("layout of %s written (%s scan, %d LEDs)", dev["name"], scan_type, len(new))
    return {"leds": len(new), "backup": backup.name}
