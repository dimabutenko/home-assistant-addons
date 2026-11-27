"""The choice of a `live:random` round: which scene each garland gets and the theme (palette, pace) of all of them.
Pure logic (no Home Assistant, no devices), so it can be checked on stubs."""
import random

from . import formula, palettes

THEMED_WEIGHT = 3  # a scene that uses the theme is this many times more likely than one that does not


def plan(scenes: list, shapes: dict, running: dict, recent: list, avoid: set = frozenset(), rng=random) -> dict:
    """scenes: the saved live scenes (specs); shapes: {device: "wall" | "tree"}; running: {device: name of its live scene or None};
    recent: [(scene name, theme)] of the round that another garland (not in this call) started a moment ago, newest first;
    avoid: palettes of the themes playing now (a new round takes another palette).
    A garland takes a scene meant for its shape or for any; garlands share a scene where the pools allow it and share the theme always.
    Returns {"theme": {...}, "groups": [{"devices": [...], "scene": name | None, "kept": bool, "error": str | None}]}."""
    theme = dict(recent[0][1]) if recent else palettes.pick_theme(avoid, rng)
    by_shape: dict = {}
    for n, shp in shapes.items():
        by_shape.setdefault(shp, []).append(n)
    chosen = [recent[0][0]] if recent else []  # scenes of this round so far: the next kind of garland joins one if it may
    out = []
    for shp, group in by_shape.items():
        pool = sorted(f["name"] for f in scenes if f.get("shape", "any") in ("any", shp))
        if not pool:
            out.append({"devices": group, "scene": None, "kept": False, "error": f"no live scene is meant for a {shp}"})
            continue
        joined = next((s for s in chosen if s in pool), None)
        if joined is None:
            current = {running[n] for n in group if running.get(n)}
            fresh = [p for p in pool if p not in current]
            if not fresh:  # nothing else to switch to: what runs keeps running (and nothing running: the first of the pool)
                out.append({"devices": group, "scene": None if current else pool[0], "kept": bool(current), "error": None})
                continue
            used = {f["name"] for f in scenes if formula.uses_theme(f)}
            joined = rng.choices(fresh, [THEMED_WEIGHT if p in used else 1 for p in fresh])[0]
        chosen.append(joined)
        out.append({"devices": group, "scene": joined, "kept": False, "error": None})
    return {"theme": theme, "groups": out}

