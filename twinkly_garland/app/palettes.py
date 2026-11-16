"""Colour palettes (gradients) shared by all effects.

A palette is a list of stops [[position 0..1, "#rrggbb"], ...]. Built-in ones are
read-only; custom ones live in /data/palettes.json.
"""
import json
import os
import re
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")

BUILTIN = {
    "fire": [[0, "#000000"], [0.25, "#5a0600"], [0.55, "#e63200"], [0.8, "#ff7805"], [1, "#ffc828"]],
    "lava": [[0, "#300000"], [0.4, "#c00000"], [0.75, "#ff6a00"], [1, "#ffe000"]],
    "ocean": [[0, "#001030"], [0.4, "#0050a0"], [0.7, "#00b4c8"], [1, "#e0ffff"]],
    "aurora": [[0, "#0b3d2e"], [0.35, "#1fd68a"], [0.65, "#2fa8d8"], [1, "#9b4dff"]],
    "neon": [[0, "#ff00c8"], [0.5, "#7a00ff"], [1, "#00e5ff"]],
    "candy": [[0, "#ff0000"], [1, "#ffffff"]],
    "sunset": [[0, "#2b0a4a"], [0.35, "#c2185b"], [0.7, "#ff7043"], [1, "#ffd54f"]],
    "forest": [[0, "#021a08"], [0.5, "#1e8e3e"], [1, "#d4f542"]],
    "ice": [[0, "#0a1a40"], [0.5, "#6aa8ff"], [1, "#ffffff"]],
    "rainbow": [[0, "#ff0000"], [0.17, "#ffff00"], [0.33, "#00ff00"], [0.5, "#00ffff"],
                [0.67, "#0000ff"], [0.83, "#ff00ff"], [1, "#ff0000"]],
    "warm white": [[0, "#ff9a3c"], [0.5, "#ffd9a0"], [1, "#fff4e0"]],
    "starlight": [[0, "#9ec5ff"], [0.5, "#ffffff"], [1, "#ffe9b0"]],
    "storm": [[0, "#05061a"], [0.4, "#1a2a66"], [0.8, "#8aa8ff"], [1, "#ffffff"]],
}

VERSION = 0  # bumped on every change, part of the render cache keys
_custom: list = []
_loaded = False
_objs: dict = {}


def _rgb(h: str) -> tuple:
    return int(h[1:3], 16), int(h[3:5], 16), int(h[5:7], 16)


class Palette:
    def __init__(self, stops: list):
        stops = sorted(([float(p), _rgb(c)] for p, c in stops), key=lambda s: s[0])
        self.lut = []
        for i in range(256):
            v = i / 255
            if v <= stops[0][0]:
                self.lut.append(stops[0][1])
                continue
            for (p0, c0), (p1, c1) in zip(stops, stops[1:]):
                if v <= p1:
                    t = (v - p0) / (p1 - p0) if p1 > p0 else 1.0
                    self.lut.append(tuple(c0[j] + (c1[j] - c0[j]) * t for j in range(3)))
                    break
            else:
                self.lut.append(stops[-1][1])
        # first == last colour: the gradient is a closed loop, wrap instead of mirror
        self.closed = stops[0][1] == stops[-1][1]

    def at(self, v: float) -> tuple:
        """Colour at v, clamped to [0, 1]."""
        return self.lut[int(min(1.0, max(0.0, v)) * 255 + 0.5)]

    def cyc(self, v: float) -> tuple:
        """Colour for a cyclic variable (any v): wrap a closed palette, mirror an open one."""
        v -= int(v) if v >= 0 else int(v) - 1
        if not self.closed:
            v = 1 - abs(2 * v - 1)
        return self.lut[int(v * 255 + 0.5)]


def _path() -> Path:
    return DATA_DIR / "palettes.json"


def custom() -> list:
    global _custom, _loaded
    if not _loaded:
        try:
            _custom = json.loads(_path().read_text())
        except (OSError, ValueError):
            _custom = []
        _loaded = True
    return _custom


def listing() -> list:
    return ([{"name": n, "stops": s, "builtin": True} for n, s in BUILTIN.items()]
            + [{"name": p["name"], "stops": p["stops"], "builtin": False} for p in custom()])


def validate(items: list) -> list:
    seen = set()
    out = []
    for p in items:
        name = str(p["name"]).strip()
        if not name or len(name) > 32:
            raise ValueError("palette name must be 1-32 characters")
        if name in BUILTIN or name in seen:
            raise ValueError(f"palette name {name!r} is taken")
        seen.add(name)
        stops = [[min(1.0, max(0.0, float(a))), str(c)] for a, c in p["stops"]]
        if len(stops) < 2 or any(not HEX.match(c) for _, c in stops):
            raise ValueError(f"palette {name!r}: need 2+ stops with #rrggbb colours")
        out.append({"name": name, "stops": sorted(stops, key=lambda s: s[0])})
    return out


def save(items: list) -> None:
    global _custom, _loaded, VERSION
    _custom = validate(items)
    _loaded = True
    VERSION += 1
    _objs.clear()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(_custom, indent=1))


def get(name: str) -> Palette:
    if name not in _objs:
        stops = BUILTIN.get(name) or next((p["stops"] for p in custom() if p["name"] == name), None)
        _objs[name] = Palette(stops or BUILTIN["rainbow"])
    return _objs[name]
