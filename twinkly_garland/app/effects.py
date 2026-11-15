"""Effect generators. Each one renders RGB frames for a given LED layout.

A generator is pure: (layout, params) -> Rendered. Frames are bytes, 3 per LED
(RGB), in the order of the layout coordinates, which is the order the device
expects in a movie.
"""
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


def default_params(effect: str) -> dict:
    return {x["name"]: x["default"] for x in GENERATORS[effect]["params"]}


def render(effect: str, layout: list, params: dict) -> Rendered:
    return GENERATORS[effect]["render"](layout, params)
