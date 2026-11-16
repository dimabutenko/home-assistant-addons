"""Effect generators. Each one renders RGB frames for a given LED layout.

A generator is a pure function (layout, params) -> Rendered. Frames are bytes,
3 per LED (RGB), in the order of the layout coordinates, which is the order the
device expects in a movie.

Every generator is a function of (x, y, t) with t in [0, 1) and uses only whole
numbers of cycles per loop, so the last frame flows into the first. Layout:
x in [-1, 1], y in [0, 1] (0 = bottom). Colours come from a palette.
"""
import hashlib
import json
import math
from dataclasses import dataclass

from . import palettes

TAU = 2 * math.pi


@dataclass
class Rendered:
    fps: int
    frames: list  # list[bytes], len == frames_number, each 3 * n_leds


# ---- helpers ------------------------------------------------------------

def _hash2(ix: int, iy: int, seed: int) -> float:
    n = (ix * 374761393 + iy * 668265263 + seed * 2246822519) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n ^= n >> 16
    return n / 0xFFFFFFFF


_hh = _hash2


def _smooth(t: float) -> float:
    return t * t * (3 - 2 * t)


def _sstep(a: float, b: float, x: float) -> float:
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def _fract(x: float) -> float:
    return x - math.floor(x)


def _c(r: float, g: float, b: float) -> tuple:
    return (min(255, max(0, int(r))), min(255, max(0, int(g))), min(255, max(0, int(b))))


def _sc(c: tuple, k: float) -> tuple:
    return _c(c[0] * k, c[1] * k, c[2] * k)


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


def _P(name, label, lo, hi, step, default):
    return {"name": name, "label": label, "min": lo, "max": hi, "step": step, "default": default}


def _PAL(default):
    return {"name": "palette", "label": "Palette", "type": "palette", "default": default}


def _bounds(layout):
    xs = [p["x"] for p in layout]
    ys = [p["y"] for p in layout]
    return min(xs), max(xs), min(ys), max(ys)


GENERATORS: dict = {}
COMMON = [
    _P("intensity", "Brightness", 0.1, 1.0, 0.05, 0.9),
    _P("seed", "Seed (random variation)", 0, 99, 1, 1),
]


def _register(name: str, title: str, own: list, build) -> None:
    plist = own + COMMON

    def render_fn(layout: list, params: dict) -> Rendered:
        p = {x["name"]: x["default"] for x in plist}
        p.update({k: v for k, v in params.items() if k in p})
        fps = int(params.get("fps", 10))
        n = int(params.get("duration", 10)) * fps
        pal = palettes.get(p["palette"]) if "palette" in p else None
        pix = build(layout, p, pal)
        frames = []
        for f in range(n):
            t = f / n
            buf = bytearray()
            for i, pt in enumerate(layout):
                buf += bytes(pix(i, pt["x"], pt["y"], t))
            frames.append(bytes(buf))
        return Rendered(fps=fps, frames=frames)

    GENERATORS[name] = {"title": title, "params": plist, "render": render_fn}


# ---- original generators (now palette driven) -----------------------------

def _flame(layout, p, P):
    k, sx, sy, seed, height = p["intensity"], p["scale_x"], p["scale_y"], int(p["seed"]), p["height"]
    # Lattice cells in y per vertical period; the pattern scrolls by whole periods per loop.
    period = max(2, int(sy * 2))
    cells = int(p["speed"]) * period

    def pix(i, x, y, t):
        ny = y * sy * 2 + cells * t
        n = (0.65 * _noise(x * sx, ny, period, seed)
             + 0.35 * _noise(x * sx * 2.1 + 9, ny * 2, period * 2, seed + 1))
        base = max(0.0, 1.0 - y / height)
        heat = n * (0.35 + 0.65 * base) * (0.4 + 0.9 * base) * 1.5
        return _sc(P.at(heat), k)
    return pix


_register("flame", "Flame", [
    _PAL("fire"), _P("speed", "Rise speed (periods per loop)", 1, 6, 1, 2),
    _P("scale_x", "Horizontal scale", 1, 12, 0.5, 4), _P("scale_y", "Vertical scale", 1, 12, 0.5, 4),
    _P("height", "Flame height", 0.3, 2.0, 0.05, 1.0)], _flame)


def _twinkle(layout, p, P):
    k, seed, sharp, rate = p["intensity"], int(p["seed"]), p["sharpness"], int(p["rate"])
    n = len(layout)
    ph = [_hh(i, 1, seed) for i in range(n)]
    fr = [1 + int(_hh(i, 2, seed) * rate) for i in range(n)]
    cv = [_hh(i, 3, seed) for i in range(n)]

    def pix(i, x, y, t):
        s = 0.5 + 0.5 * math.sin(TAU * (fr[i] * t + ph[i]))
        return _sc(P.at(cv[i]), (s ** (sharp * 2)) * k)
    return pix


_register("twinkle", "Twinkle", [
    _PAL("warm white"), _P("sharpness", "Sharpness", 1, 6, 0.5, 3), _P("rate", "Max blinks per loop", 1, 5, 1, 2)], _twinkle)


def _wave(layout, p, P):
    k, sc, cyc = p["intensity"], p["scale"], int(p["cycles"])
    a = math.radians(p["angle"])
    ca, sa = math.cos(a), math.sin(a)

    def pix(i, x, y, t):
        return _sc(P.cyc((x * ca + y * sa) * sc + cyc * t), k)
    return pix


_register("wave", "Colour wave", [
    _PAL("rainbow"), _P("scale", "Spatial scale", 0.2, 3, 0.1, 0.7), _P("angle", "Direction, deg", 0, 345, 15, 0),
    _P("cycles", "Colour cycles per loop", 1, 4, 1, 1)], _wave)


def _aurora(layout, p, P):
    k, drift = p["intensity"], int(p["drift"])

    def pix(i, x, y, t):
        u = 0.5 + 0.5 * math.sin(TAU * (0.9 * x - drift * t) + 3 * y + math.sin(TAU * t + 2 * x))
        v = 0.5 + 0.5 * math.sin(TAU * (0.6 * y + 0.4 * x + t) + 2 * math.sin(TAU * (x - t)))
        b = (v ** 2.2) * (0.3 + 0.7 * y)
        return _sc(P.at(u), b * k * 1.3)
    return pix


_register("aurora", "Aurora", [_PAL("aurora"), _P("drift", "Drift speed", 1, 3, 1, 1)], _aurora)


def _snow(layout, p, P):
    k, seed = p["intensity"], int(p["seed"])
    lanes, dens, fall, size = int(p["lanes"]), p["flakes"], int(p["fall"]), p["size"]

    def pix(i, x, y, t):
        lane = int(math.floor((x + 1) * lanes / 2))
        u = _fract(y * dens + fall * t + _hh(lane, 5, seed))
        b = max(0.0, 1 - abs(u - 0.5) / size) ** 2
        return _sc(P.at(0.35 + 0.65 * b), b * k)
    return pix


_register("snowfall", "Snowfall", [
    _PAL("ice"), _P("lanes", "Columns", 4, 30, 1, 14), _P("flakes", "Flakes per column", 1, 4, 0.5, 2),
    _P("fall", "Fall speed", 1, 6, 1, 2), _P("size", "Flake size", 0.05, 0.4, 0.01, 0.15)], _snow)


def _plasma(layout, p, P):
    k, sc, sp = p["intensity"], p["scale"], int(p["speed"])

    def pix(i, x, y, t):
        v = (math.sin(TAU * (x * sc * 0.5 + sp * t)) + math.sin(TAU * (y * sc * 0.7 + sp * t))
             + math.sin(TAU * ((x + y) * sc * 0.35 + 2 * sp * t))
             + math.sin(TAU * (math.hypot(x, y - 0.5) * sc * 0.6 - sp * t)))
        v = 0.5 + v / 8
        return _sc(P.cyc(v), (0.3 + 0.7 * v) * k)
    return pix


_register("plasma", "Plasma", [_PAL("rainbow"), _P("scale", "Scale", 1, 6, 0.5, 3), _P("speed", "Speed", 1, 3, 1, 1)], _plasma)


def _meteors(layout, p, P):
    k, seed, lanes, sp, tail = p["intensity"], int(p["seed"]), int(p["lanes"]), int(p["speed"]), p["tail"]
    a = math.radians(p["angle"])
    ca, sa = math.cos(a), math.sin(a)

    def pix(i, x, y, t):
        along, perp = (x * ca + y * sa) * 0.7, -x * sa + y * ca
        lane = int(math.floor(perp * lanes))
        u = _fract(along + sp * t + _hh(lane, 7, seed))
        if u >= tail:
            return (0, 0, 0)
        return _sc(P.cyc(_hh(lane, 8, seed)), ((1 - u / tail) ** 2) * k)
    return pix


_register("meteors", "Meteors", [
    _PAL("ice"), _P("lanes", "Lanes", 3, 20, 1, 8), _P("speed", "Speed", 1, 4, 1, 2),
    _P("tail", "Tail length", 0.1, 0.9, 0.05, 0.5), _P("angle", "Direction, deg", 0, 345, 15, 300)], _meteors)


def _ripple(layout, p, P):
    k, cx, cy, rings, sp = p["intensity"], p["cx"], p["cy"], p["rings"], int(p["speed"])

    def pix(i, x, y, t):
        s = 0.5 + 0.5 * math.sin(TAU * (math.hypot(x - cx, y - cy) * rings - sp * t))
        return _sc(P.at(s), (s ** 2) * k)
    return pix


_register("ripple", "Ripples", [
    _PAL("neon"), _P("cx", "Centre x", -1, 1, 0.05, 0.0), _P("cy", "Centre y", 0, 1, 0.05, 0.4),
    _P("rings", "Rings", 1, 8, 0.5, 3), _P("speed", "Speed", 1, 3, 1, 1)], _ripple)


def _candy(layout, p, P):
    k, n, sp = p["intensity"], p["stripes"], int(p["speed"])
    a = math.radians(p["angle"])
    ca, sa = math.cos(a), math.sin(a)
    c1, c2 = P.at(0.0), P.at(1.0)

    def pix(i, x, y, t):
        s = _fract((x * ca + y * sa) * n * 0.5 + sp * t)
        w = _sstep(0.42, 0.5, s) - _sstep(0.92, 1.0, s)
        return _c(*(k * (c1[j] + (c2[j] - c1[j]) * w) for j in range(3)))
    return pix


_register("candy", "Candy stripes", [
    _PAL("candy"), _P("stripes", "Stripes", 2, 16, 1, 6), _P("speed", "Speed", 1, 3, 1, 1),
    _P("angle", "Direction, deg", 0, 345, 15, 45)], _candy)


def _fireflies(layout, p, P):
    k, seed, n, size, orbit = p["intensity"], int(p["seed"]), int(p["count"]), p["size"], p["orbit"]
    x0, x1, y0, y1 = _bounds(layout)
    ff = [(x0 + (x1 - x0) * _hh(j, 11, seed), y0 + (y1 - y0) * _hh(j, 12, seed),
           orbit * (0.4 + _hh(j, 13, seed)), orbit * (0.4 + _hh(j, 14, seed)) * 0.6,
           _hh(j, 15, seed), (1, -1, 2, 1)[j % 4], _hh(j, 16, seed)) for j in range(n)]
    inv = 1.0 / (2 * size * size)
    cache = {"t": None, "pos": []}

    def pix(i, x, y, t):
        if cache["t"] != t:
            cache["t"] = t
            cache["pos"] = [(cx + rx * math.cos(TAU * (rev * t + ph)), cy + ry * math.sin(TAU * (rev * t + ph)),
                             0.55 + 0.45 * math.sin(TAU * (2 * t + ph)), cv) for cx, cy, rx, ry, ph, rev, cv in ff]
        acc = hh = 0.0
        for fx, fy, blink, cv in cache["pos"]:
            g = math.exp(-((x - fx) ** 2 + (y - fy) ** 2) * inv) * blink
            acc += g
            hh += g * cv
        return _sc(P.at(0.3 + 0.7 * (hh / acc if acc > 1e-6 else 0)), min(1.0, acc) * k)
    return pix


_register("fireflies", "Fireflies", [
    _PAL("forest"), _P("count", "Fireflies", 3, 30, 1, 12), _P("size", "Glow size", 0.05, 0.4, 0.01, 0.14),
    _P("orbit", "Wander radius", 0.05, 0.5, 0.01, 0.2)], _fireflies)


def _breathe(layout, p, P):
    k, spread = p["intensity"], p["spread"]

    def pix(i, x, y, t):
        c = 0.5 + 0.5 * math.sin(TAU * (t - x * spread * 0.25))
        c2 = 0.5 + 0.5 * math.sin(TAU * (t - x * spread * 0.25 - 0.2))
        return _sc(P.at(c), (0.25 + 0.75 * c2) * k)
    return pix


_register("breathe", "Breathing colours", [_PAL("sunset"), _P("spread", "Spatial delay", 0, 2, 0.1, 0.5)], _breathe)


def _pinwheel(layout, p, P):
    k, arms, sp, cx, cy = p["intensity"], int(p["arms"]), int(p["speed"]), p["cx"], p["cy"]

    def pix(i, x, y, t):
        th = math.atan2(y - cy, x - cx) / TAU
        r = math.hypot(x - cx, y - cy)
        h = arms * th + sp * t
        return _sc(P.cyc(h), (0.45 + 0.55 * math.sin(TAU * (h + r))) * k)
    return pix


_register("pinwheel", "Pinwheel", [
    _PAL("rainbow"), _P("arms", "Arms", 1, 8, 1, 3), _P("speed", "Speed", 1, 3, 1, 1),
    _P("cx", "Centre x", -1, 1, 0.05, 0.0), _P("cy", "Centre y", 0, 1, 0.05, 0.4)], _pinwheel)


# ---- new generators --------------------------------------------------------

def _clouds(layout, p, P):
    k, seed, sc, sp, contrast = p["intensity"], int(p["seed"]), p["scale"], int(p["speed"]), p["contrast"]
    terms = []
    for j in range(5):
        terms.append(((_hh(j, 51, seed) * 2 - 1) * sc * 2, (_hh(j, 52, seed) * 2 - 1) * sc * 2,
                      (1 + int(_hh(j, 53, seed) * sp)) * (1 if _hh(j, 54, seed) > 0.5 else -1), _hh(j, 55, seed)))

    def pix(i, x, y, t):
        n = 0.5 + sum(math.sin(TAU * (a * x + b * y + c * t + ph)) for a, b, c, ph in terms) / 10
        n = min(1.0, max(0.0, (n - 0.5) * contrast + 0.5))
        return _sc(P.at(n), (0.25 + 0.75 * n) * k)
    return pix


_register("clouds", "Drifting clouds", [
    _PAL("sunset"), _P("scale", "Scale", 0.3, 4, 0.1, 1.2), _P("speed", "Speed", 1, 3, 1, 1),
    _P("contrast", "Contrast", 0.5, 4, 0.1, 1.8)], _clouds)


def _stars(layout, p, P):
    k, seed, dens, rate = p["intensity"], int(p["seed"]), p["density"], int(p["rate"])
    n = len(layout)
    star = [_hh(i, 21, seed) < dens for i in range(n)]
    ph = [_hh(i, 22, seed) for i in range(n)]
    fr = [1 + int(_hh(i, 24, seed) * rate) for i in range(n)]
    cv = [_hh(i, 23, seed) for i in range(n)]

    def pix(i, x, y, t):
        if not star[i]:
            return (0, 0, 0)
        b = (0.5 + 0.5 * math.sin(TAU * (fr[i] * t + ph[i]))) ** 3
        return _sc(P.at(cv[i]), b * k)
    return pix


_register("stars", "Slow stars", [
    _PAL("starlight"), _P("density", "Share of lit LEDs", 0.05, 0.8, 0.05, 0.25), _P("rate", "Max pulses per loop", 1, 3, 1, 1)], _stars)


def _storm(layout, p, P):
    k, seed, nf, decay = p["intensity"], int(p["seed"]), int(p["flashes"]), p["decay"]
    fl = [(_hh(j, 31, seed), -1 + 2 * _hh(j, 32, seed)) for j in range(nf)]
    cache = {"t": None, "v": []}

    def pix(i, x, y, t):
        if cache["t"] != t:
            cache["t"] = t
            cache["v"] = [(math.exp(-((t - tj) % 1.0) * decay) * (1 if ((t - tj) % 1.0) < 0.5 else 0), xj) for tj, xj in fl]
        n = 0.5 + 0.5 * math.sin(TAU * (0.7 * x + t) + 2 * math.sin(TAU * (y * 1.3 - t)))
        base = _sc(P.at(0.1 + 0.25 * n), 0.5 * k)
        f = max((fv * (0.35 + 0.65 * math.exp(-((x - xj) ** 2) * 1.5)) for fv, xj in cache["v"]), default=0)
        fc = P.at(1.0)
        return _c(base[0] + fc[0] * f * k, base[1] + fc[1] * f * k, base[2] + fc[2] * f * k)
    return pix


_register("storm", "Thunderstorm", [
    _PAL("storm"), _P("flashes", "Lightning flashes", 1, 5, 1, 3), _P("decay", "Flash decay", 3, 30, 1, 16)], _storm)


def _ocean(layout, p, P):
    k, level, amp, sp = p["intensity"], p["level"], p["amp"], int(p["speed"])

    def pix(i, x, y, t):
        h = level + amp * math.sin(TAU * (1.3 * x - sp * t)) + amp * 0.5 * math.sin(TAU * (2.7 * x + 2 * sp * t + 0.3))
        d = h - y
        if d < 0:
            return (0, 0, 0)
        if d < 0.05:
            return _sc(P.at(1.0), k)
        v = 1 - min(1.0, d * 2.2)
        return _sc(P.at(0.15 + 0.7 * v), (0.4 + 0.6 * v) * k)
    return pix


_register("ocean", "Ocean waves", [
    _PAL("ocean"), _P("level", "Water level", 0.2, 0.9, 0.05, 0.55), _P("amp", "Wave height", 0.02, 0.3, 0.01, 0.1),
    _P("speed", "Speed", 1, 3, 1, 1)], _ocean)


def _rain(layout, p, P):
    k, seed, lanes, dens, fall, tail = p["intensity"], int(p["seed"]), int(p["lanes"]), p["density"], int(p["fall"]), p["tail"]

    def pix(i, x, y, t):
        lane = int(math.floor((x + 1) * lanes / 2))
        u = _fract(y * dens + fall * t + _hh(lane, 61, seed))
        if u >= tail:
            return (0, 0, 0)
        b = (1 - u / tail) ** 2
        return _sc(P.at(0.3 + 0.7 * b), b * k)
    return pix


_register("rain", "Rain", [
    _PAL("ice"), _P("lanes", "Columns", 6, 40, 1, 20), _P("density", "Drops per column", 1, 4, 0.5, 2),
    _P("fall", "Fall speed", 1, 8, 1, 4), _P("tail", "Streak length", 0.1, 0.8, 0.05, 0.4)], _rain)


def _bars(layout, p, P):
    k, seed, nb, sp = p["intensity"], int(p["seed"]), int(p["bars"]), int(p["speed"])
    fr = [1 + int(_hh(c, 71, seed) * sp) for c in range(nb)]
    ph = [_hh(c, 72, seed) for c in range(nb)]

    def pix(i, x, y, t):
        pos = (x + 1) * nb / 2
        c = min(nb - 1, max(0, int(math.floor(pos))))
        xf = pos - math.floor(pos)
        if xf < 0.12 or xf > 0.88:
            return (0, 0, 0)
        h = 0.15 + 0.75 * (0.5 + 0.5 * math.sin(TAU * (fr[c] * t + ph[c])))
        if y > h:
            return (0, 0, 0)
        if y > h - 0.07:
            return _sc(P.at(1.0), k)
        return _sc(P.at(y / h), 0.8 * k)
    return pix


_register("bars", "Equalizer bars", [
    _PAL("sunset"), _P("bars", "Bars", 3, 20, 1, 10), _P("speed", "Max speed", 1, 3, 1, 2)], _bars)


def _scanner(layout, p, P):
    k, w, cyc = p["intensity"], p["width"], int(p["cycles"])
    a = math.radians(p["angle"])
    ca, sa = math.cos(a), math.sin(a)
    proj = [pt["x"] * ca + pt["y"] * sa for pt in layout]
    lo, hi = min(proj), max(proj)
    span = (hi - lo) or 1.0

    def pix(i, x, y, t):
        u = (proj[i] - lo) / span
        pos = 0.5 + 0.5 * math.sin(TAU * cyc * t)
        b = math.exp(-((u - pos) ** 2) / (2 * w * w))
        return _sc(P.at(0.3 + 0.7 * b), b * k)
    return pix


_register("scanner", "Scanner", [
    _PAL("lava"), _P("width", "Beam width", 0.03, 0.5, 0.01, 0.12), _P("cycles", "Sweeps per loop", 1, 4, 1, 1),
    _P("angle", "Direction, deg", 0, 345, 15, 0)], _scanner)


def _lava(layout, p, P):
    k, seed, nb, r = p["intensity"], int(p["seed"]), int(p["blobs"]), p["radius"]
    x0, x1, y0, y1 = _bounds(layout)
    bl = [(x0 + (x1 - x0) * _hh(j, 81, seed), _hh(j, 82, seed), (1 if _hh(j, 83, seed) > 0.5 else -1)) for j in range(nb)]
    r2 = r * r
    cache = {"t": None, "pos": []}

    def pix(i, x, y, t):
        if cache["t"] != t:
            cache["t"] = t
            cache["pos"] = [(bx + 0.12 * math.sin(TAU * (t + ph)), y0 + (y1 - y0) * (0.5 + 0.42 * math.sin(TAU * (rev * t + ph))))
                            for bx, ph, rev in bl]
        f = sum(r2 / ((x - bx) ** 2 + (y - by) ** 2 + 1e-3) for bx, by in cache["pos"])
        b = _sstep(0.5, 1.3, f)
        return _sc(P.at(min(1.0, f * 0.4)), b * k)
    return pix


_register("lavalamp", "Lava lamp", [
    _PAL("lava"), _P("blobs", "Blobs", 2, 8, 1, 4), _P("radius", "Blob size", 0.1, 0.5, 0.01, 0.25)], _lava)


def _glitter(layout, p, P):
    k, seed, dens, rate = p["intensity"], int(p["seed"]), p["density"], int(p["rate"])
    n = len(layout)
    on = [_hh(i, 41, seed) < dens for i in range(n)]
    ph = [_hh(i, 42, seed) for i in range(n)]
    cv = [_hh(i, 43, seed) for i in range(n)]

    def pix(i, x, y, t):
        if not on[i]:
            return (0, 0, 0)
        u = _fract(t * rate + ph[i])
        b = max(0.0, 1 - u / 0.25) ** 2
        return _sc(P.cyc(cv[i]), b * k)
    return pix


_register("glitter", "Glitter", [
    _PAL("neon"), _P("density", "Share of sparkling LEDs", 0.1, 1.0, 0.05, 0.6), _P("rate", "Flashes per loop", 1, 6, 1, 3)], _glitter)


def _helix(layout, p, P):
    k, turns, w, amp, cyc = p["intensity"], p["turns"], p["width"], p["amp"], int(p["cycles"])

    def pix(i, x, y, t):
        ph = TAU * (y * turns - cyc * t)
        xs, depth = amp * math.sin(ph), math.cos(ph)
        ba = math.exp(-((x - xs) ** 2) / (2 * w * w)) * (0.55 + 0.45 * depth)
        bb = math.exp(-((x + xs) ** 2) / (2 * w * w)) * (0.55 - 0.45 * depth)
        return _sc(P.at(0.15), ba * k) if ba >= bb else _sc(P.at(0.85), bb * k)
    return pix


_register("helix", "Double helix", [
    _PAL("neon"), _P("turns", "Turns", 0.5, 4, 0.25, 1.5), _P("width", "Strand width", 0.03, 0.3, 0.01, 0.12),
    _P("amp", "Amplitude", 0.2, 1.0, 0.05, 0.6), _P("cycles", "Spin speed", 1, 3, 1, 1)], _helix)


def _checker(layout, p, P):
    k, cells, sp = p["intensity"], p["cells"], int(p["speed"])

    def pix(i, x, y, t):
        par = (int(math.floor((x + 1) * cells / 2)) + int(math.floor(y * cells / 2))) % 2
        v = 0.5 + 0.5 * math.sin(TAU * (sp * t + 0.5 * par))
        return _sc(P.at(v), k)
    return pix


_register("checker", "Checkerboard", [
    _PAL("neon"), _P("cells", "Cells across", 2, 12, 1, 6), _P("speed", "Speed", 1, 3, 1, 1)], _checker)


def _confetti(layout, p, P):
    k, seed, n, size, rate = p["intensity"], int(p["seed"]), int(p["count"]), p["size"], int(p["rate"])
    x0, x1, y0, y1 = _bounds(layout)
    sp = [(_hh(j, 91, seed), x0 + (x1 - x0) * _hh(j, 92, seed), y0 + (y1 - y0) * _hh(j, 93, seed), _hh(j, 94, seed))
          for j in range(n)]
    inv = 1.0 / (2 * size * size)
    cache = {"t": None, "s": []}

    def pix(i, x, y, t):
        if cache["t"] != t:
            cache["t"] = t
            cache["s"] = [(sx, sy, math.sin(math.pi * _fract(t * rate + tj)) ** 2, cv) for tj, sx, sy, cv in sp]
        best, cv_best = 0.0, 0.0
        for sx, sy, life, cv in cache["s"]:
            g = math.exp(-((x - sx) ** 2 + (y - sy) ** 2) * inv) * life
            if g > best:
                best, cv_best = g, cv
        return _sc(P.cyc(cv_best), best * k)
    return pix


_register("confetti", "Confetti", [
    _PAL("rainbow"), _P("count", "Spots", 3, 30, 1, 14), _P("size", "Spot size", 0.04, 0.3, 0.01, 0.12),
    _P("rate", "Lifetimes per loop", 1, 3, 1, 2)], _confetti)


def _radar(layout, p, P):
    k, sp, trail, cx, cy = p["intensity"], int(p["speed"]), p["trail"], p["cx"], p["cy"]

    def pix(i, x, y, t):
        u = _fract(math.atan2(y - cy, x - cx) / TAU - sp * t)
        if u >= trail:
            return (0, 0, 0)
        b = (1 - u / trail) ** 2
        return _sc(P.at(0.25 + 0.75 * b), b * k)
    return pix


_register("radar", "Radar sweep", [
    _PAL("forest"), _P("speed", "Rotations per loop", 1, 3, 1, 1), _P("trail", "Trail length", 0.1, 1.0, 0.05, 0.6),
    _P("cx", "Centre x", -1, 1, 0.05, 0.0), _P("cy", "Centre y", 0, 1, 0.05, 0.4)], _radar)


def _pulse(layout, p, P):
    k, rate, spread = p["intensity"], int(p["rate"]), p["spread"]

    def pix(i, x, y, t):
        tt = _fract(t * rate - spread * math.hypot(x, y - 0.4) * 0.5)
        g = math.exp(-(((tt - 0.1) / 0.09) ** 2)) + 0.7 * math.exp(-(((tt - 0.3) / 0.1) ** 2))
        g = min(1.0, g)
        return _sc(P.at(g), (0.08 + 0.92 * g) * k)
    return pix


_register("pulse", "Heartbeat", [
    _PAL("lava"), _P("rate", "Beats per loop", 1, 4, 1, 2), _P("spread", "Wave spread", 0, 2, 0.1, 0.6)], _pulse)


# ---- registry API ---------------------------------------------------------

def default_params(effect: str) -> dict:
    return {x["name"]: x["default"] for x in GENERATORS[effect]["params"]}


_cache: dict = {}


def render(effect: str, layout: list, params: dict) -> Rendered:
    """Cached: ensure/play re-renders every configured effect on each call.
    `params` may carry `duration` (s) and `fps`."""
    sig = hashlib.md5(repr([(round(p["x"], 5), round(p["y"], 5)) for p in layout]).encode()).hexdigest()
    key = (effect, json.dumps(params, sort_keys=True), sig, palettes.VERSION)
    if key not in _cache:
        if len(_cache) >= 80:
            _cache.pop(next(iter(_cache)))
        _cache[key] = GENERATORS[effect]["render"](layout, params)
    return _cache[key]
