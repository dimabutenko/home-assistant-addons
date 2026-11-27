"""Device access: layout cache, ensure (reconcile) and play."""
import hashlib
import io
import json
import logging
import math
import os
import socket
import threading
import time
import uuid
from pathlib import Path

from xled import ControlInterface
from xled.udp_client import UDPClient

log = logging.getLogger("twinkly.device")
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
NS = uuid.UUID("6f1d3a52-3b52-4c3e-9d0a-7a3c5b1f0e11")  # fixed namespace for movie ids
_locks: dict = {}
scanning_hosts: set = set()  # devices in real-time mode for a position scan: leave them alone
live_hosts: dict = {}  # host -> LiveStream: a live scene is streaming to this device


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
    _clients.clear()  # start from a fresh login next time (a stream that still holds the old client keeps its own socket)
    raise last


_clients: dict = {}


class SendOnlyUDP(UDPClient):
    """xled binds its UDP socket to the local port 7777 (the port it sends to), so a second garland in the same process,
    or a client that has not been garbage collected yet, fails with "Address in use". Sending needs no fixed local port."""

    @property
    def handle(self):
        if self._handle is None:
            self._handle = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        return self._handle


def connect(host: str) -> ControlInterface:
    """Shared client per device (keeps its login token). Call it while holding lock_for(host)."""
    socket.create_connection((host, 80), timeout=3).close()  # xled has no timeout
    if host not in _clients:
        ci = ControlInterface(host)
        ci._udpclient = SendOnlyUDP(7777, host)  # xled's REALTIME_UDP_PORT_NUMBER
        _clients[host] = ci
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


def device_settings(name: str) -> dict:
    return load_settings().get("devices", {}).get(name, {})


def device_aspect(name: str):
    return device_settings(name).get("aspect")


def device_shape(name: str) -> str:
    """'wall' (a flat area: a window, a wall) or 'tree' (a cone seen from one side)."""
    return "tree" if device_settings(name).get("shape") == "tree" else "wall"


def device_shade(name: str) -> float:
    """How much the far side of a tree is dimmed (0 = not at all, 1 = the back is dark); a wall has none."""
    if device_shape(name) != "tree":
        return 0.0
    return max(0.0, min(1.0, float(device_settings(name).get("shade", 0.5))))


LIVE_FPS_DEFAULT = 12.0


def device_live_fps(name: str) -> float:
    """Frames a second of a live scene on this garland (2..25)."""
    try:
        v = float(device_settings(name).get("live_fps", LIVE_FPS_DEFAULT))
    except (TypeError, ValueError):
        v = LIVE_FPS_DEFAULT
    return max(2.0, min(25.0, v))


def save_device_settings(name: str, **changes) -> None:
    """Keys: live_fps (frames a second of a live scene), aspect (float or None), shape ('wall' / 'tree'), shade (0..1, dimming of the far side of a tree), back (indexes of the LEDs on the far side of a tree, from a scan)."""
    st = load_settings()
    dev = st.setdefault("devices", {}).setdefault(name, {})
    for k, v in changes.items():
        if v is None or (k == "shape" and v == "wall") or (k == "back" and not v):
            dev.pop(k, None)
        else:
            dev[k] = float(v) if k in ("aspect", "shade", "live_fps") else v
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _settings_path().write_text(json.dumps(st, indent=1))


def save_device_aspect(name: str, aspect) -> None:
    save_device_settings(name, aspect=aspect)


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


MAPPINGS = ("plane", "apex", "cone", "wrap")


class Layout(list):
    """A layout (a list of {x, y, z}) that also knows the frame it is measured in. The effects and the formulas take the centre of the lit
    area for the middle of the picture (r, a, u, v): that is the centre of the bounding box of the LEDs unless `box` = (x0, x1, y0, y1) says
    otherwise. The disk the tip mapping lays a tree on has its centre (the tip) at (0, 0.5) whatever the LEDs fill of it."""
    box = None
    shade = None   # one brightness factor (0..1) per LED, applied to every picture drawn on this layout (the far side of a tree is dimmer)


def tree_polar(layout: list, back=()) -> list:
    """For every LED of a tree: (s, theta) - s = its distance from the tip along the cone, 0 at the tip and 1 at the base (that is the
    height below the tip), theta = its angle around the trunk in radians, 0 at the front (the side the camera saw), -pi..pi, the back at +-pi.

    With a 3D layout (a tree scanned from two sides) the angle comes from x and z across the tree at that height; with a 2D layout (one side)
    from where the LED stands across the tree (the width of the tree at that height is taken from the LEDs around it): a LED seen from the
    front is on the near half, one in `back` (not seen by the scan, so on the far side) on the far half."""
    n = len(layout)
    ys = [p["y"] for p in layout]
    y_top, y_bot = max(ys), min(ys)
    height = (y_top - y_bot) or 1.0
    has_z = max((abs(p.get("z", 0)) for p in layout), default=0) > 1e-6
    top = sorted(layout, key=lambda p: -p["y"])[:max(3, n // 20)]
    xc = sorted(p["x"] for p in top)[len(top) // 2]
    zc = sorted(p.get("z", 0) for p in top)[len(top) // 2] if has_z else 0.0
    xs = [p["x"] for p in layout]
    band = 0.05 * height
    back = set(back)

    def spread(vals):
        vals = sorted(vals)
        return vals[int(0.9 * (len(vals) - 1))] if vals else 0.0

    out = []
    for i, p in enumerate(layout):
        near = [q for q in layout if abs(q["y"] - p["y"]) <= band]
        half = max(spread([abs(q["x"] - xc) for q in near]), 1e-6, 0.05 * (max(xs) - min(xs)))
        cx = max(-1.0, min(1.0, (p["x"] - xc) / half))
        if has_z:
            deep = max(spread([abs(q.get("z", 0) - zc) for q in near]), 1e-6)
            cz = max(-1.0, min(1.0, (p.get("z", 0) - zc) / deep))
            theta = math.atan2(cx, cz)
        else:
            theta = math.pi - math.asin(cx) if i in back else math.asin(cx)
        theta = (theta + math.pi) % (2 * math.pi) - math.pi
        out.append(((y_top - p["y"]) / height, theta))
    return out


def _tree_width(layout: list) -> float:
    """Width of the tree at its base divided by its height (the layout is in height units)."""
    xs = [p["x"] for p in layout]
    return (max(xs) - min(xs)) or 0.5


def tree_shade(layout: list, back=(), strength: float = 0.5) -> list:
    """A brightness factor for every LED of a tree: 1 at the front, 1 - strength at the back, smooth round the sides. It gives the picture
    a body (the LEDs on the far side shine through the tree, but dimmer)."""
    return [1.0 - strength * (0.5 - 0.5 * math.cos(th)) for _s, th in tree_polar(layout, back)]


def apex_layout(layout: list, back=()) -> list:
    """A tree laid out like a round window whose centre is the tip: an effect that spreads from the centre of the window then spreads
    from the top of the tree down to its base, and an effect that turns around the centre turns around the trunk. The distance from the
    centre is the distance from the tip along the cone (0 at the tip, the radius 0.5 of the disk at the base), the angle is the angle
    around the trunk (all of it, 360 degrees)."""
    if len(layout) < 3:
        return layout
    out = [{"x": 0.5 * s * math.sin(th), "y": 0.5 + 0.5 * s * math.cos(th), "z": 0} for s, th in tree_polar(layout, back)]
    disk = Layout(out)
    disk.box = (-0.5, 0.5, 0.0, 1.0)  # the tip is the centre of the picture, the base circle its edge
    return disk


def cone_layout(layout: list, back=()) -> list:
    """The cone surface (without the base) rolled out flat: a sector of a circle with the tip at the top. Distances along the surface are
    kept, so an effect keeps its true shapes (a circle stays a circle, a diagonal stripe becomes a spiral round the tree). The sector is
    narrower than the full circle: 2*pi*R/L, about 109 degrees for a tree 180 cm high and 115 cm wide at the base. The seam is at the back."""
    if len(layout) < 3:
        return layout
    radius = _tree_width(layout) / 2           # of the base, in heights
    slant = math.hypot(1.0, radius)            # the length of the side of the cone
    k = radius / slant                         # the sector angle is 2*pi*k
    out = []
    for s, th in tree_polar(layout, back):
        d, psi = s * slant, th * k
        out.append({"x": d * math.sin(psi), "y": 1.0 - d * math.cos(psi), "z": 0})
    return Layout(out)


def wrap_layout(layout: list, back=()) -> list:
    """The surface of the tree as a strip: x = the way round the trunk (one turn is the length of the circle at the middle of the tree), y = the
    height. An effect that repeats along x (stripes, waves) closes round the tree without a seam; the seam is at the back."""
    if len(layout) < 3:
        return layout
    turn = math.pi * _tree_width(layout) / 2   # the circle at half the height: 2*pi*(R/2) with R = width/2
    out = [{"x": (th / (2 * math.pi)) * turn, "y": 1.0 - s, "z": 0} for s, th in tree_polar(layout, back)]
    strip = Layout(out)
    strip.box = (-turn / 2, turn / 2, 0.0, 1.0)
    return strip


def render_layout(dev: dict, mapping: str = "plane") -> list:
    """The layout effects are computed on. `mapping` (apex, cone, wrap) only applies to a garland whose shape is 'tree'."""
    lay = physical(get_layout(dev), device_aspect(dev["name"]))
    if device_shape(dev["name"]) != "tree" or len(lay) < 3:
        return lay
    back = device_settings(dev["name"]).get("back", [])
    out = {"apex": apex_layout, "cone": cone_layout, "wrap": wrap_layout}[mapping](lay, back) if mapping in MAPPINGS and mapping != "plane" else Layout(lay)
    strength = device_shade(dev["name"])
    if strength > 0:
        out.shade = tree_shade(lay, back, strength)
    return out


# ---- desired state ------------------------------------------------------

def build_desired(dev: dict, instances: list, render_instance) -> list:
    """Render every enabled instance targeting this device -> list of movie specs."""
    layouts = {}
    out = []
    for inst in instances:
        if not inst.get("on_device", True):
            continue
        targets = inst.get("devices") or []
        if targets and dev["name"] not in targets:
            continue
        mp = inst.get("mapping", "plane")
        layout = layouts.get(mp) or layouts.setdefault(mp, render_layout(dev, mp))
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
            "mapping": mp,
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
    if dev["host"] in live_hosts:
        raise RuntimeError(f"{dev['name']}: a live scene is running, stop it first")
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
    if dev["host"] in live_hosts:
        raise RuntimeError(f"{dev['name']}: a live scene is running, stop it first")
    with lock_for(dev["host"]):
        spec = next((m for m in desired if m["key"] == key), None)
        if spec is None:
            raise KeyError(f"effect {key!r} is not configured for {dev['name']}")
        ci = connect(dev["host"])
        _select(ci, spec["uid"])
        return {"device": dev["name"], "playing": key}
