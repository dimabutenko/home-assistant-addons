"""Device access: layout cache, ensure (reconcile) and play."""
import hashlib
import io
import json
import logging
import os
import socket
import threading
import time
import uuid
from pathlib import Path

from xled import ControlInterface

log = logging.getLogger("twinkly.device")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
NS = uuid.UUID("6f1d3a52-3b52-4c3e-9d0a-7a3c5b1f0e11")  # fixed namespace for movie ids
_locks: dict = {}
scanning_hosts: set = set()  # devices in real-time mode for a position scan: leave them alone


def lock_for(host: str) -> threading.Lock:
    return _locks.setdefault(host, threading.Lock())


def retry(fn, *args, tries=4):
    """The device HTTP server sometimes drops the connection mid-request."""
    last = None
    for i in range(tries):
        try:
            return fn(*args)
        except Exception as exc:
            last = exc
            time.sleep(0.5 * (i + 1))
    raise last


def connect(host: str) -> ControlInterface:
    socket.create_connection((host, 80), timeout=3).close()  # xled has no timeout
    return ControlInterface(host)


# ---- layout cache -------------------------------------------------------

def _layout_path(name: str) -> Path:
    return DATA_DIR / "layouts" / f"{name}.json"


def get_layout(dev: dict, refresh: bool = False) -> list:
    """Returns [{x,y,z}, ...]; reads from the device and caches it."""
    path = _layout_path(dev["name"])
    if refresh or not path.exists():
        ci = connect(dev["host"])
        lay = retry(lambda: ci.session.get(ci.base_url + "led/layout/full").json())
        coords = [{"x": c["x"], "y": c["y"], "z": c.get("z", 0)} for c in lay["coordinates"]]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(coords))
        return coords
    return json.loads(path.read_text())


# ---- desired state ------------------------------------------------------

def build_desired(dev: dict, instances: list, render_instance) -> list:
    """Render every enabled instance targeting this device -> list of movie specs."""
    layout = get_layout(dev)
    out = []
    for inst in instances:
        if not inst.get("on_device", True):
            continue
        targets = inst.get("devices") or []
        if targets and dev["name"] not in targets:
            continue
        r = render_instance(inst, layout)
        digest = hashlib.sha1(b"".join(r.frames) + str(r.fps).encode()).hexdigest()[:16]
        out.append({
            "key": inst["key"],
            "name": inst["key"][:32],
            # The id carries the content hash: the device itself tells us which
            # version of the effect it holds.
            "uid": str(uuid.uuid5(NS, f"{inst['key']}:{digest}")).upper(),
            "fps": r.fps,
            "frames": r.frames,
            "n_leds": len(layout),
            "rotation": inst.get("rotation", True),
            "weight": inst.get("weight", 1),
        })
    return out


# ---- reconcile ----------------------------------------------------------

def plan(dev: dict, desired: list) -> dict:
    ci = connect(dev["host"])
    d = retry(ci.get_movies)
    present = {m["unique_id"].upper(): m for m in d["movies"]}
    want = {m["uid"]: m for m in desired}
    missing = [m["key"] for u, m in want.items() if u not in present]
    extra = [m["name"] for u, m in present.items() if u not in want]
    need = sum(len(m["frames"]) for m in desired)
    return {
        "device": dev["name"],
        "action": "ok" if not missing and not extra else "rebuild",
        "missing": missing,
        "extra": extra,
        "frames_needed": need,
        "capacity": d["max_capacity"],
        "fits": need <= d["max_capacity"],
    }


def ensure(dev: dict, desired: list, play_key: str | None = None) -> dict:
    """Make the device hold exactly `desired`. Rebuilds the whole set on any
    drift, because the firmware cannot delete a single movie."""
    if dev["host"] in scanning_hosts:
        raise RuntimeError(f"{dev['name']}: a position scan is running")
    with lock_for(dev["host"]):
        pl = plan(dev, desired)
        if pl["action"] == "ok":
            return pl
        if not pl["fits"]:
            raise ValueError(f"{dev['name']}: {pl['frames_needed']} frames > capacity {pl['capacity']}")
        ci = connect(dev["host"])
        try:
            before = retry(ci.get_movies_current)
        except Exception:  # empty answer when no movie is stored
            before = {}
        orig_mode = retry(ci.get_mode).get("mode")
        # The firmware refuses to delete movies (code 1102) unless the LEDs are off.
        retry(ci.set_mode, "off")
        retry(ci.delete_movies)
        if retry(ci.get_movies)["movies"]:
            raise RuntimeError(f"{dev['name']}: the device did not delete its movies")
        for m in desired:
            retry(ci.set_movies_new, m["name"], m["uid"], "rgb_raw", m["n_leds"], len(m["frames"]), m["fps"])
            retry(ci.set_movies_full, io.BytesIO(b"".join(m["frames"])))
        pl["action"] = "rebuilt"
        uids = {m["uid"] for m in desired}
        want_uid = next((m["uid"] for m in desired if m["key"] == play_key), None)
        if want_uid is None and (before.get("unique_id") or "").upper() in uids:
            want_uid = before["unique_id"].upper()
        if want_uid is None and desired:
            want_uid = desired[0]["uid"]  # old selection is gone: play the first effect
        if want_uid:
            _select(ci, want_uid)
        elif orig_mode:
            retry(ci.set_mode, orig_mode)
        return pl


def _select(ci, uid: str) -> None:
    try:
        cur = retry(ci.get_movies_current)
        if (cur.get("unique_id") or "").upper() == uid and retry(ci.get_mode).get("mode") == "movie":
            return  # already playing: re-selecting would restart the loop
    except Exception:
        pass
    movies = retry(ci.get_movies)["movies"]
    mid = next(m["id"] for m in movies if m["unique_id"].upper() == uid)
    retry(ci.set_mode, "movie")
    retry(ci.set_movies_current, mid)  # selected by index, which shifts: always re-resolve


def play(dev: dict, desired: list, key: str) -> dict:
    if dev["host"] in scanning_hosts:
        raise RuntimeError(f"{dev['name']}: a position scan is running")
    with lock_for(dev["host"]):
        spec = next((m for m in desired if m["key"] == key), None)
        if spec is None:
            raise KeyError(f"effect {key!r} is not configured for {dev['name']}")
        ci = connect(dev["host"])
        _select(ci, spec["uid"])
        return {"device": dev["name"], "playing": key}
