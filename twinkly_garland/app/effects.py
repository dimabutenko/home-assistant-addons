"""Effect generators. Each one renders RGB frames for a given LED layout.

A generator is pure: (layout, params) -> Rendered. Frames are bytes, 3 per LED
(RGB), in the order of the layout coordinates, which is the order the device
expects in a movie.
"""
import hashlib
import json
import math
from dataclasses import dataclass


@dataclass
class Rendered:
    fps: int
    frames: list  # list[bytes], len == frames_number, each 3 * n_leds


def _hash2(ix: int, iy: int, seed: int) -> float:
    n = (ix * 374761393 + iy * 668265263 + seed * 2246822519) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n ^= n >> 16
    return n / 0xFFFFFFFF


def _smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


def _noise(x: float, y: float, period_y: int, seed: int) -> float:
    """Value noise in [0, 1], periodic in y with period `period_y` lattice cells."""
    x0, y0 = math.floor(x), math.floor(y)
    fx, fy = _smooth(x - x0), _smooth(y - y0)
    ya, yb = y0 % period_y, (y0 + 1) % period_y
    a = _hash2(x0, ya, seed)
    b = _hash2(x0 + 1, ya, seed)
    c = _hash2(x0, yb, seed)
    d = _hash2(x0 + 1, yb, seed)
    return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy


# heat (0..1) -> RGB: dark red -> orange -> rare yellow highlights
_STOPS = [
    (0.00, (0, 0, 0)),
    (0.25, (90, 6, 0)),
    (0.55, (230, 50, 0)),
    (0.80, (255, 120, 5)),
    (1.00, (255, 200, 40)),
]


def _heat_rgb(h: float) -> tuple:
    h = min(1.0, max(0.0, h))
    for (h0, c0), (h1, c1) in zip(_STOPS, _STOPS[1:]):
        if h <= h1:
            t = (h - h0) / (h1 - h0)
            return tuple(int(c0[i] + (c1[i] - c0[i]) * t) for i in range(3))
    return _STOPS[-1][1]


FLAME_PARAMS = [
    {"name": "duration", "label": "Loop length, s", "min": 4, "max": 30, "step": 1, "default": 10},
    {"name": "fps", "label": "FPS", "min": 5, "max": 15, "step": 1, "default": 10},
    {"name": "speed", "label": "Rise speed (periods per loop)", "min": 1, "max": 6, "step": 1, "default": 2},
    {"name": "scale_x", "label": "Horizontal scale", "min": 1, "max": 12, "step": 0.5, "default": 4},
    {"name": "scale_y", "label": "Vertical scale", "min": 1, "max": 12, "step": 0.5, "default": 4},
    {"name": "height", "label": "Flame height", "min": 0.3, "max": 2.0, "step": 0.05, "default": 1.0},
    {"name": "intensity", "label": "Brightness", "min": 0.1, "max": 1.0, "step": 0.05, "default": 0.9},
    {"name": "seed", "label": "Seed", "min": 0, "max": 99, "step": 1, "default": 7},
]


def render_flame(layout: list, params: dict) -> Rendered:
    p = {x["name"]: x["default"] for x in FLAME_PARAMS}
    p.update({k: v for k, v in params.items() if k in p})
    fps = int(p["fps"])
    frames_n = int(p["duration"]) * fps
    # Lattice cells in y per vertical period. The pattern scrolls by an integer
    # number of whole periods per loop, so the last frame flows into the first.
    period = max(2, int(p["scale_y"] * 2))
    sx, sy = p["scale_x"], p["scale_y"]
    cells_per_loop = int(p["speed"]) * period
    seed = int(p["seed"])
    k = p["intensity"]
    frames = []
    for f in range(frames_n):
        shift = cells_per_loop * f / frames_n
        buf = bytearray()
        for pt in layout:
            x, y = pt["x"], pt["y"]  # y: 0 = bottom, 1 = top
            ny = y * sy * 2 + shift
            n = (0.65 * _noise(x * sx, ny, period, seed)
                 + 0.35 * _noise(x * sx * 2.1 + 9, ny * 2, period * 2, seed + 1))
            base = max(0.0, 1.0 - y / p["height"])
            heat = n * (0.35 + 0.65 * base) * (0.4 + 0.9 * base) * 1.5
            r, g, b = _heat_rgb(heat)
            buf += bytes((int(r * k), int(g * k), int(b * k)))
        frames.append(bytes(buf))
    return Rendered(fps=fps, frames=frames)


GENERATORS = {
    "flame": {"title": "Flame", "params": FLAME_PARAMS, "render": render_flame},
}


# ---------------------------------------------------------------------------
# Abstract effects. Every one is a pure function of (x, y, t) with t in [0, 1)
# and only integer numbers of cycles per loop, so the last frame flows into
# the first. Layout: x in [-1, 1], y in [0, 1] (0 = bottom).
# ---------------------------------------------------------------------------

TAU = 2 * math.pi


def _c(r: float, g: float, b: float) -> tuple:
    return (min(255, max(0, int(r))), min(255, max(0, int(g))), min(255, max(0, int(b))))


def _hsv(h: float, s: float, v: float) -> tuple:
    h = (h % 1.0) * 6
    i = int(h)
    f = h - i
    v = min(1.0, max(0.0, v))
    s = min(1.0, max(0.0, s))
    p, q, t = v * (1 - s), v * (1 - f * s), v * (1 - (1 - f) * s)
    r, g, b = ((v, t, p), (q, v, p), (p, v, t), (p, q, v), (t, p, v), (v, p, q))[i % 6]
    return _c(r * 255, g * 255, b * 255)


def _fract(x: float) -> float:
    return x - math.floor(x)


def _sstep(a: float, b: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def _hh(i: int, salt: int, seed: int) -> float:
    return _hash2(i, salt, seed)


COMMON = [
    {"name": "duration", "label": "Loop length, s", "min": 4, "max": 30, "step": 1, "default": 10},
    {"name": "fps", "label": "FPS", "min": 5, "max": 15, "step": 1, "default": 10},
    {"name": "intensity", "label": "Brightness", "min": 0.1, "max": 1.0, "step": 0.05, "default": 0.9},
    {"name": "seed", "label": "Seed", "min": 0, "max": 99, "step": 1, "default": 1},
]


def _P(name, label, lo, hi, step, default):
    return {"name": name, "label": label, "min": lo, "max": hi, "step": step, "default": default}


def _register(name: str, title: str, own: list, build) -> None:
    plist = COMMON + own

    def render_fn(layout: list, params: dict) -> Rendered:
        p = {x["name"]: x["default"] for x in plist}
        p.update({k: v for k, v in params.items() if k in p})
        fps = int(p["fps"])
        n = int(p["duration"]) * fps
        pix = build(layout, p)
        frames = []
        for f in range(n):
            t = f / n
            buf = bytearray()
            for i, pt in enumerate(layout):
                buf += bytes(pix(i, pt["x"], pt["y"], t))
            frames.append(bytes(buf))
        return Rendered(fps=fps, frames=frames)

    GENERATORS[name] = {"title": title, "params": plist, "render": render_fn}


def _twinkle(layout, p):
    k, seed, hue, sat, sharp = p["intensity"], int(p["seed"]), p["hue"], p["sat"], p["sharpness"]
    rate = int(p["rate"])
    ph = [_hh(i, 1, seed) for i in range(len(layout))]
    fr = [1 + int(_hh(i, 2, seed) * rate) for i in range(len(layout))]
    hj = [(_hh(i, 3, seed) - 0.5) * 0.12 for i in range(len(layout))]

    def pix(i, x, y, t):
        s = 0.5 + 0.5 * math.sin(TAU * (fr[i] * t + ph[i]))
        return _hsv(hue + hj[i], sat, (s ** (sharp * 2)) * k)
    return pix


_register("twinkle", "Twinkle", [
    _P("hue", "Hue", 0, 1, 0.01, 0.10), _P("sat", "Saturation", 0, 1, 0.05, 0.35),
    _P("sharpness", "Sharpness", 1, 6, 0.5, 3), _P("rate", "Max blinks per loop", 1, 5, 1, 2)], _twinkle)


def _wave(layout, p):
    k, sc, cyc, sat = p["intensity"], p["scale"], int(p["cycles"]), p["sat"]
    a = math.radians(p["angle"])
    ca, sa = math.cos(a), math.sin(a)

    def pix(i, x, y, t):
        return _hsv((x * ca + y * sa) * sc + cyc * t, sat, k)
    return pix


_register("wave", "Rainbow wave", [
    _P("scale", "Spatial scale", 0.2, 3, 0.1, 0.7), _P("angle", "Direction, deg", 0, 345, 15, 0),
    _P("cycles", "Colour cycles per loop", 1, 4, 1, 1), _P("sat", "Saturation", 0, 1, 0.05, 1)], _wave)


def _aurora(layout, p):
    k, shift, drift = p["intensity"], p["hue_shift"], int(p["drift"])

    def pix(i, x, y, t):
        u = 0.5 + 0.5 * math.sin(TAU * (0.9 * x - drift * t) + 3 * y + math.sin(TAU * t + 2 * x))
        v = 0.5 + 0.5 * math.sin(TAU * (0.6 * y + 0.4 * x + t) + 2 * math.sin(TAU * (x - t)))
        b = (v ** 2.2) * (0.3 + 0.7 * y)
        return _hsv(0.33 + 0.45 * u + shift, 0.9, b * k * 1.3)
    return pix


_register("aurora", "Aurora", [
    _P("hue_shift", "Hue shift", 0, 1, 0.02, 0.0), _P("drift", "Drift speed", 1, 3, 1, 1)], _aurora)


def _snow(layout, p):
    k, seed = p["intensity"], int(p["seed"])
    lanes, dens, fall, size = int(p["lanes"]), p["flakes"], int(p["fall"]), p["size"]

    def pix(i, x, y, t):
        lane = int(math.floor((x + 1) * lanes / 2))
        u = _fract(y * dens + fall * t + _hh(lane, 5, seed))
        b = max(0.0, 1 - abs(u - 0.5) / size) ** 2
        return _hsv(0.58, 0.18, b * k)
    return pix


_register("snowfall", "Snowfall", [
    _P("lanes", "Columns", 4, 30, 1, 14), _P("flakes", "Flakes per column", 1, 4, 0.5, 2),
    _P("fall", "Fall speed", 1, 6, 1, 2), _P("size", "Flake size", 0.05, 0.4, 0.01, 0.15)], _snow)

_PLASMA_PAL = [(0.0, 1.0, 1.0), (0.0, 0.14, 1.0), (0.5, 0.72, 0.9), (0.78, 1.1, 1.0)]


def _plasma(layout, p):
    k, sc, sp = p["intensity"], p["scale"], int(p["speed"])
    h0, h1, sat = _PLASMA_PAL[int(p["palette"]) % 4]

    def pix(i, x, y, t):
        v = (math.sin(TAU * (x * sc * 0.5 + sp * t)) + math.sin(TAU * (y * sc * 0.7 + sp * t))
             + math.sin(TAU * ((x + y) * sc * 0.35 + 2 * sp * t)) + math.sin(TAU * (math.hypot(x, y - 0.5) * sc * 0.6 - sp * t)))
        v = 0.5 + v / 8
        return _hsv(h0 + (h1 - h0) * v, sat, (0.2 + 0.8 * v) * k)
    return pix


_register("plasma", "Plasma", [
    _P("scale", "Scale", 1, 6, 0.5, 3), _P("speed", "Speed", 1, 3, 1, 1),
    _P("palette", "Palette (0 rainbow, 1 lava, 2 ocean, 3 neon)", 0, 3, 1, 0)], _plasma)


def _meteors(layout, p):
    k, seed, lanes, sp, tail = p["intensity"], int(p["seed"]), int(p["lanes"]), int(p["speed"]), p["tail"]
    hue = p["hue"]
    a = math.radians(p["angle"])
    ca, sa = math.cos(a), math.sin(a)

    def pix(i, x, y, t):
        along, perp = (x * ca + y * sa) * 0.7, -x * sa + y * ca
        lane = int(math.floor(perp * lanes))
        u = _fract(along + sp * t + _hh(lane, 7, seed))
        if u >= tail:
            return (0, 0, 0)
        b = (1 - u / tail) ** 2
        return _hsv(hue + 0.15 * _hh(lane, 8, seed), 0.5 + 0.5 * u / tail, b * k)
    return pix


_register("meteors", "Meteors", [
    _P("lanes", "Lanes", 3, 20, 1, 8), _P("speed", "Speed", 1, 4, 1, 2), _P("tail", "Tail length", 0.1, 0.9, 0.05, 0.4),
    _P("angle", "Direction, deg", 0, 345, 15, 300), _P("hue", "Hue", 0, 1, 0.01, 0.55)], _meteors)


def _ripple(layout, p):
    k, cx, cy, rings, sp, hue = p["intensity"], p["cx"], p["cy"], p["rings"], int(p["speed"]), p["hue"]

    def pix(i, x, y, t):
        r = math.hypot(x - cx, y - cy)
        s = 0.5 + 0.5 * math.sin(TAU * (r * rings - sp * t))
        return _hsv(hue + 0.3 * s, 0.85, (s ** 2) * k)
    return pix


_register("ripple", "Ripples", [
    _P("cx", "Centre x", -1, 1, 0.05, 0.0), _P("cy", "Centre y", 0, 1, 0.05, 0.4), _P("rings", "Rings", 1, 8, 0.5, 3),
    _P("speed", "Speed", 1, 3, 1, 1), _P("hue", "Hue", 0, 1, 0.01, 0.55)], _ripple)


def _candy(layout, p):
    k, n, sp, hue = p["intensity"], p["stripes"], int(p["speed"]), p["hue"]
    a = math.radians(p["angle"])
    ca, sa = math.cos(a), math.sin(a)
    c1, c2 = _hsv(hue, 1.0, 1.0), _hsv(hue, 0.05, 1.0)

    def pix(i, x, y, t):
        s = _fract((x * ca + y * sa) * n * 0.5 + sp * t)
        w = _sstep(0.42, 0.5, s) - _sstep(0.92, 1.0, s)
        return _c(*(k * (c1[j] + (c2[j] - c1[j]) * w) for j in range(3)))
    return pix


_register("candy", "Candy stripes", [
    _P("stripes", "Stripes", 2, 16, 1, 6), _P("speed", "Speed", 1, 3, 1, 1),
    _P("angle", "Direction, deg", 0, 345, 15, 45), _P("hue", "Stripe hue", 0, 1, 0.01, 0.0)], _candy)


def _fireflies(layout, p):
    k, seed, n, size, hue, orbit = p["intensity"], int(p["seed"]), int(p["count"]), p["size"], p["hue"], p["orbit"]
    xs = [pt["x"] for pt in layout]
    ys = [pt["y"] for pt in layout]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    ff = []
    for j in range(n):
        ff.append((x0 + (x1 - x0) * _hh(j, 11, seed), y0 + (y1 - y0) * _hh(j, 12, seed),
                   orbit * (0.4 + _hh(j, 13, seed)), orbit * (0.4 + _hh(j, 14, seed)) * 0.6,
                   _hh(j, 15, seed), (1, -1, 2, 1)[j % 4], _hh(j, 16, seed)))
    inv = 1.0 / (2 * size * size)
    cache = {"t": None, "pos": []}

    def pix(i, x, y, t):
        if cache["t"] != t:
            cache["t"] = t
            cache["pos"] = [(cx + rx * math.cos(TAU * (rev * t + ph)), cy + ry * math.sin(TAU * (rev * t + ph)),
                             0.55 + 0.45 * math.sin(TAU * (2 * t + ph)), hj) for cx, cy, rx, ry, ph, rev, hj in ff]
        acc = 0.0
        hh = 0.0
        for fx, fy, blink, hj in cache["pos"]:
            g = math.exp(-((x - fx) ** 2 + (y - fy) ** 2) * inv) * blink
            acc += g
            hh += g * hj
        return _hsv(hue + 0.12 * (hh / acc if acc > 1e-6 else 0), 0.85, min(1.0, acc) * k)
    return pix


_register("fireflies", "Fireflies", [
    _P("count", "Fireflies", 3, 30, 1, 12), _P("size", "Glow size", 0.05, 0.4, 0.01, 0.14),
    _P("orbit", "Wander radius", 0.05, 0.5, 0.01, 0.2), _P("hue", "Hue", 0, 1, 0.01, 0.17)], _fireflies)


def _breathe(layout, p):
    k, ha, hb, spread = p["intensity"], p["hue_a"], p["hue_b"], p["spread"]

    def pix(i, x, y, t):
        c = 0.5 + 0.5 * math.sin(TAU * (t - x * spread * 0.25))
        c2 = 0.5 + 0.5 * math.sin(TAU * (t - x * spread * 0.25 - 0.2))
        return _hsv(ha + (hb - ha) * c, 0.9, (0.25 + 0.75 * c2) * k)
    return pix


_register("breathe", "Breathing colours", [
    _P("hue_a", "Colour A", 0, 1, 0.01, 0.6), _P("hue_b", "Colour B", 0, 1.2, 0.01, 0.92),
    _P("spread", "Spatial delay", 0, 2, 0.1, 0.5)], _breathe)


def _pinwheel(layout, p):
    k, arms, sp, cx, cy = p["intensity"], int(p["arms"]), int(p["speed"]), p["cx"], p["cy"]

    def pix(i, x, y, t):
        th = math.atan2(y - cy, x - cx) / TAU
        r = math.hypot(x - cx, y - cy)
        h = arms * th + sp * t
        return _hsv(h, 0.9, (0.45 + 0.55 * math.sin(TAU * (arms * th + sp * t + r))) * k)
    return pix


_register("pinwheel", "Pinwheel", [
    _P("arms", "Arms", 1, 8, 1, 3), _P("speed", "Speed", 1, 3, 1, 1),
    _P("cx", "Centre x", -1, 1, 0.05, 0.0), _P("cy", "Centre y", 0, 1, 0.05, 0.4)], _pinwheel)


def default_params(effect: str) -> dict:
    return {x["name"]: x["default"] for x in GENERATORS[effect]["params"]}


_cache: dict = {}


def render(effect: str, layout: list, params: dict) -> Rendered:
    """Cached: ensure/play re-renders every configured effect on each call."""
    sig = hashlib.md5(repr([(round(p["x"], 5), round(p["y"], 5)) for p in layout]).encode()).hexdigest()
    key = (effect, json.dumps(params, sort_keys=True), sig)
    if key not in _cache:
        if len(_cache) >= 40:
            _cache.pop(next(iter(_cache)))
        _cache[key] = GENERATORS[effect]["render"](layout, params)
    return _cache[key]
