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


def lock_for(host: str) -> threading.RLock:
    """One re-entrant lock per device. The device keeps a single login token, so two
    requests logging in at the same time invalidate each other (HTTP 401, 'verify failed'):
    every sequence of calls to a device must run under this lock."""
    return _locks.setdefault(host, threading.RLock())


def retry(fn, *args, tries=4):
    """The device HTTP server sometimes drops the connection mid-request."""
    last = None
    for i in range(tries):
        try:
            return fn(*args)
        except Exception as exc:
            last = exc
            time.sleep(0.5 * (i + 1))
    _clients.clear()  # start from a fresh login next time
    raise last


_clients: dict = {}


def connect(host: str) -> ControlInterface:
    """Shared client per device (keeps its login token). Call it while holding lock_for(host)."""
    socket.create_connection((host, 80), timeout=3).close()  # xled has no timeout
    if host not in _clients:
        _clients[host] = ControlInterface(host)
    return _clients[host]


# ---- layout cache -------------------------------------------------------

def _layout_path(name: str) -> Path:
    return DATA_DIR / "layouts" / f"{name}.json"


def get_layout(dev: dict, refresh: bool = False) -> list:
    """Returns [{x,y,z}, ...]; reads from the device and caches it."""
    path = _layout_path(dev["name"])
    if refresh or not path.exists():
        with lock_for(dev["host"]):
            ci = connect(dev["host"])
            lay = retry(lambda: ci.session.get(ci.base_url + "led/layout/full").json())
        coords = [{"x": c["x"], "y": c["y"], "z": c.get("z", 0)} for c in lay["coordinates"]]
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(coords))
        return coords
    return json.loads(path.read_text())


# ---- per-device settings and the "physical" layout used for rendering -----------

def _settings_path() -> Path:
    return DATA_DIR / "settings.json"


def load_settings() -> dict:
    try:
        return json.loads(_settings_path().read_text())
    except (OSError, ValueError):
        return {}


def device_aspect(name: str):
    return load_settings().get("devices", {}).get(name, {}).get("aspect")


def save_device_aspect(name: str, aspect) -> None:
    st = load_settings()
    dev = st.setdefault("devices", {}).setdefault(name, {})
    if aspect is None:
        dev.pop("aspect", None)
    else:
        dev["aspect"] = float(aspect)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(st, indent=1))


def physical(layout: list, aspect=None) -> list:
    """Layout in 'height units': y in [0, 1], x centred with the real width/height ratio.
    Twinkly stretches a scan to x -1..1, y 0..1, which squeezes circles into ovals on a wall
    that is not 2:1; `aspect` (real width / height) puts the proportions back."""
    xs = [p["x"] for p in layout]
    ys = [p["y"] for p in layout]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    w, h = (x1 - x0) or 1.0, (y1 - y0) or 1.0
    a = aspect or (w / h)
    xc = (x0 + x1) / 2
    return [{"x": (p["x"] - xc) / w * a, "y": (p["y"] - y0) / h, "z": p.get("z", 0)} for p in layout]


def render_layout(dev: dict) -> list:
    return physical(get_layout(dev), device_aspect(dev["name"]))


# ---- desired state ------------------------------------------------------

def build_desired(dev: dict, instances: list, render_instance) -> list:
    """Render every enabled instance targeting this device -> list of movie specs."""
    layout = render_layout(dev)
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

def movie_overhead(listing: dict) -> int:
    """Frames the device spends on each movie besides its own frames (measured: about 3-4)."""
    movies = listing["movies"]
    if not movies:
        return 4
    used = listing["max_capacity"] - listing["available_frames"]
    stored = sum(m["frames_number"] for m in movies)
    return max(2, -(-(used - stored) // len(movies)))


def plan(dev: dict, desired: list, listing: dict | None = None) -> dict:
    """Compare the stored movies with `desired`. `listing` = a get_movies() answer already in hand."""
    if listing is None:
        with lock_for(dev["host"]):
            listing = retry(connect(dev["host"]).get_movies)
    d = listing
    present = {m["unique_id"].upper(): m for m in d["movies"]}
    want = {m["uid"]: m for m in desired}
    missing = [m["key"] for u, m in want.items() if u not in present]
    extra = [m["name"] for u, m in present.items() if u not in want]
    need = sum(len(m["frames"]) + movie_overhead(d) for m in desired)
    return {
        "device": dev["name"],
        "action": "ok" if not missing and not extra else "update",
        "missing": missing,
        "extra": extra,
        "frames_needed": need,
        "capacity": d["max_capacity"],
        "fits": need <= d["max_capacity"],
    }


class _DeleteRefused(Exception):
    pass


def _delete_movie(ci, movie_id: int) -> None:
    """DELETE /movies/<id> removes one movie (ids above it shift down by one).
    Works while the LEDs are playing; not documented by the vendor."""
    r = retry(lambda: ci.session.delete(ci.base_url + f"movies/{movie_id}", timeout=15))
    try:
        code = r.json().get("code")
    except ValueError:
        code = None
    if r.status_code != 200 or code != 1000:
        raise _DeleteRefused(f"DELETE movies/{movie_id} -> HTTP {r.status_code}, code {code}")


def _upload(ci, m: dict) -> None:
    """movies/new must precede movies/full, so a failed pair is retried as a pair."""
    data = b"".join(m["frames"])
    last = None
    for attempt in range(3):
        try:
            ci.set_movies_new(m["name"], m["uid"], "rgb_raw", m["n_leds"], len(m["frames"]), m["fps"])
            ci.set_movies_full(io.BytesIO(data))
            return
        except Exception as exc:
            last = exc
            resp = getattr(exc, "response", None)
            if resp is not None and resp.status_code == 406:
                raise RuntimeError(f"the device refused {m['name']!r}: no room left") from exc
            time.sleep(1 + attempt)
    raise last


def ensure(dev: dict, desired: list, play_key: str | None = None) -> dict:
    """Make the device hold exactly `desired`: delete stale movies one by one and upload
    the missing ones. The LEDs keep playing meanwhile and a device that is off stays off.
    If the firmware refuses to delete a single movie, fall back to wiping everything (LEDs off)."""
    if dev["host"] in scanning_hosts:
        raise RuntimeError(f"{dev['name']}: a position scan is running")
    with lock_for(dev["host"]):
        ci = connect(dev["host"])
        listing = retry(ci.get_movies)
        pl = plan(dev, desired, listing)
        if pl["action"] == "ok":
            return pl
        want = {m["uid"]: m for m in desired}
        present = listing["movies"]
        stale = [m for m in present if m["unique_id"].upper() not in want]
        have = {m["unique_id"].upper() for m in present}
        missing = [m for m in desired if m["uid"] not in have]
        oh = movie_overhead(listing)
        free = listing["available_frames"] + sum(m["frames_number"] + oh for m in stale)
        need = sum(len(m["frames"]) + oh for m in missing)
        if need > free:
            raise ValueError(f"{dev['name']}: the new effects need {need} frames but only {free} will be free "
                             f"(capacity {pl['capacity']}): turn some effects off")
        try:
            before = retry(ci.get_movies_current)
        except Exception:  # empty answer when no movie is stored
            before = {}
        mode = retry(ci.get_mode).get("mode")
        cur_uid = (before.get("unique_id") or "").upper()
        try:
            if mode == "movie" and any(m["unique_id"].upper() == cur_uid for m in stale):
                keep = next((m for m in desired if m["uid"] in have), None)  # do not delete what is playing
                if keep:
                    _select(ci, keep["uid"])
            for m in sorted(stale, key=lambda x: x["id"], reverse=True):  # high ids first: ids shift
                _delete_movie(ci, m["id"])
            pl["action"] = "updated"
        except _DeleteRefused as exc:
            log.warning("single delete refused (%s): wiping all movies instead", exc)
            retry(ci.set_mode, "off")  # the firmware wipes only while the LEDs are off
            retry(ci.delete_movies)
            if retry(ci.get_movies)["movies"]:
                raise RuntimeError(f"{dev['name']}: the device did not delete its movies")
            missing = list(desired)
            pl["action"] = "rebuilt"
        for m in missing:
            _upload(ci, m)
        want_uid = next((m["uid"] for m in desired if m["key"] == play_key), None)
        if want_uid is None and mode == "movie":
            # The current movie is stored as an index, which moves when movies below it are deleted:
            # point it back at the movie that was playing (or at a wanted one if that is gone).
            if cur_uid in want:
                want_uid = cur_uid
            elif desired:
                want_uid = next((m["uid"] for m in desired if m["uid"] in have), desired[0]["uid"])
        if want_uid:
            _select(ci, want_uid)
        elif pl["action"] == "rebuilt" and mode:
            retry(ci.set_mode, mode)  # the wipe path switched the LEDs off: put the mode back
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
