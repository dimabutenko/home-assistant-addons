"""Effect instances: one or more layers mixed together.

Instance = {key, layers[], duration, fps, on_device, rotation, weight, devices[]}
Layer    = {effect, params{}, blend, opacity, mask{type, from, to, invert}}
"""
import copy
import hashlib
import json
import math

from . import effects, palettes

BLENDS = ("normal", "add", "screen", "multiply", "max")
MASKS = ("none", "x", "y", "radial")

# generators that are switched on for the devices by default; the rest start
# in the library only (the device holds ~22 effects of 100 frames)
DEFAULT_ON = {"flame", "twinkle", "wave", "aurora", "snowfall", "plasma", "meteors", "ripple", "candy",
              "fireflies", "breathe", "pinwheel"}


def default_layer(effect: str) -> dict:
    return {"effect": effect, "params": {}, "blend": "normal", "opacity": 1.0,
            "mask": {"type": "none", "from": 0.0, "to": 1.0, "invert": False}}


def default_instance(effect: str) -> dict:
    return {"key": effect, "layers": [default_layer(effect)], "duration": 10, "fps": 10,
            "on_device": effect in DEFAULT_ON, "rotation": True, "weight": 1, "devices": []}


def normalize(inst: dict) -> dict:
    """Fill defaults and convert the old single-effect form ({effect, params})."""
    inst = copy.deepcopy(inst)
    if "layers" not in inst:
        params = dict(inst.get("params", {}))
        inst["duration"] = params.pop("duration", inst.get("duration", 10))
        inst["fps"] = params.pop("fps", inst.get("fps", 10))
        inst["layers"] = [{"effect": inst.get("effect", "flame"), "params": params}]
        inst.pop("effect", None)
        inst.pop("params", None)
    inst.setdefault("duration", 10)
    inst.setdefault("fps", 10)
    inst.setdefault("on_device", True)
    inst.setdefault("rotation", True)
    inst.setdefault("weight", 1)
    inst.setdefault("devices", [])
    inst.setdefault("mapping", "plane")
    for layer in inst["layers"]:
        base = default_layer(layer["effect"])
        for k, v in base.items():
            layer.setdefault(k, v)
        layer["mask"] = {**base["mask"], **layer["mask"]}
        for k in ("duration", "fps"):
            layer["params"].pop(k, None)
    return inst


def _smooth(a: float, b: float, x: float) -> float:
    if a == b:
        return 1.0 if x >= a else 0.0
    t = min(1.0, max(0.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def mask_values(layout: list, mask: dict) -> list:
    kind = mask.get("type", "none")
    if kind == "none":
        return [1.0] * len(layout)
    xs = [p["x"] for p in layout]
    ys = [p["y"] for p in layout]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    dmax = math.hypot(x1 - cx, y1 - cy) or 1.0
    out = []
    for p in layout:
        if kind == "x":
            u = (p["x"] - x0) / ((x1 - x0) or 1.0)
        elif kind == "y":
            u = (p["y"] - y0) / ((y1 - y0) or 1.0)
        else:
            u = math.hypot(p["x"] - cx, p["y"] - cy) / dmax
        m = _smooth(mask["from"], mask["to"], u)
        out.append(1.0 - m if mask.get("invert") else m)
    return out


def _blend(mode: str, b: int, s: int) -> float:
    if mode == "add":
        return min(255, b + s)
    if mode == "screen":
        return 255 - (255 - b) * (255 - s) / 255
    if mode == "multiply":
        return b * s / 255
    if mode == "max":
        return max(b, s)
    return s


_cache: dict = {}


def render_instance(inst: dict, layout: list) -> effects.Rendered:
    inst = normalize(inst)
    sig = hashlib.md5(json.dumps([inst["layers"], inst["duration"], inst["fps"], palettes.VERSION,
                                  [(round(p["x"], 5), round(p["y"], 5)) for p in layout]]).encode()).hexdigest()
    if sig in _cache:
        return _cache[sig]
    parts = []
    for layer in inst["layers"]:
        params = {**layer["params"], "duration": inst["duration"], "fps": inst["fps"]}
        parts.append((layer, effects.render(layer["effect"], layout, params)))
    first, r0 = parts[0]
    if len(parts) == 1 and first["opacity"] >= 1 and first["mask"]["type"] == "none":
        out = r0
    else:
        n = len(r0.frames)
        n_leds = len(layout)
        alpha = [[ly["opacity"] * m for m in mask_values(layout, ly["mask"])] for ly, _ in parts]
        frames = []
        for f in range(n):
            buf = [0] * (3 * n_leds)
            for li, (ly, r) in enumerate(parts):
                src = r.frames[f]
                mode = "normal" if li == 0 else ly["blend"]
                al = alpha[li]
                for i in range(n_leds):
                    a = al[i]
                    if a <= 0:
                        continue
                    for c in (3 * i, 3 * i + 1, 3 * i + 2):
                        b = buf[c]
                        buf[c] = b + (_blend(mode, b, src[c]) - b) * a
            frames.append(bytes(min(255, max(0, int(v))) for v in buf))
        out = effects.Rendered(fps=r0.fps, frames=frames)
    if len(_cache) >= 60:
        _cache.pop(next(iter(_cache)))
    _cache[sig] = out
    return out
