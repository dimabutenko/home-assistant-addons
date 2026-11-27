"""Shared pieces of the golden-frame checks: synthetic layouts, input scenarios and the frame sequence of a formula."""
import math
import os
import random
import sys
from pathlib import Path

os.environ.setdefault("DATA_DIR", str(Path(__file__).parent / "_data"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import formula  # noqa: E402

N_FRAMES = 5


class Layout(list):
    box = None
    shade = None


def layouts() -> dict:
    """A wall (a window-like grid with jitter) and a tree (a cone), both with fixed positions."""
    rnd = random.Random(7)
    wall = Layout({"x": (c / 14 - 0.5) * 0.8 + rnd.uniform(-0.01, 0.01), "y": r / 11 + rnd.uniform(-0.01, 0.01)} for r in range(12) for c in range(15))
    tree = Layout()
    for k in range(160):
        h = k / 159
        ang = k * 2.399963
        rad = 0.5 * (1 - h)
        tree.append({"x": rad * math.cos(ang), "y": h * 1.2})
    tree.box = (-0.5, 0.5, 0.0, 1.2)
    return {"wall": wall, "tree": tree}


def scenarios(inputs: list) -> list:
    """Per-input extras (value, phase, kick, age, count, dir, delta) for three states: idle, active, extreme."""
    out = []
    for s, (val, kick, age, count, d, delta) in enumerate([(None, 0.0, 60.0, 0, 0, 0.0), (0.55, 0.7, 0.6, 3, 1, 0.4), (1.0, 1.0, 0.0, 17, -1, -2.5)]):
        T = []
        for j, i in enumerate(inputs):
            v = i["default"] if val is None else min(1.0, max(0.0, val + 0.13 * j * (-1) ** j))
            T.append((v, v * (3 + s * 5), kick, age + j, float(count + j), float(d), delta))
        out.append(T)
    return out


def frame_vals(defs: list, inputs: list, T: list) -> list:
    return ([float(d["default"]) for d in defs] + [t[0] for t in T] + [t[1] for t in T] + [t[2] for t in T] + [t[3] for t in T]
            + [t[4] for t in T] + [t[5] for t in T] + [t[6] for t in T])


def run(spec: dict, kind: str, lay: Layout, scen: int, prev_frames: list | None = None) -> list:
    """The frames of one scene. With prev_frames (the golden sequence) every frame is computed from the golden previous
    frame, so one rounding step cannot grow through the feedback of prev()."""
    spec = formula.validate_item({"name": "t", **spec})
    defs, inputs = spec["params"], spec["inputs"]
    fn = formula.compile_formula(spec["code"], formula.all_names(defs, inputs))
    prep = formula.Prepared(lay)
    k = 0.9
    prevfn, state = formula.make_prev(prep, k)
    T = scenarios(inputs)[scen]
    out = []
    for f in range(N_FRAMES):
        state["frame"] = (prev_frames[f - 1] if f else None) if prev_frames is not None else (out[-1] if out else None)
        t, now = (f * 0.137) % 1.0, 2.0 + f * 0.5
        vals = frame_vals(defs, inputs, [(a, b + f * 0.1, c, d + f * 0.5, e, g, h) for a, b, c, d, e, g, h in T])
        out.append(formula.eval_frame(fn, prep, t, now, 1.0, vals, k, prevfn))
    return out
