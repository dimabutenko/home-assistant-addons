"""0.22.0: channels. The move of the inputs of the formulas into channels (frames before and after identical for every example, merging
only of identical inputs, a backup, once), usage and merging, defaults for a channel that is not bound or not available, the theme
channels, the history of a channel. Run from twinkly_garland/: python tests/test_channels.py (no Home Assistant, no garland)."""
import json
import random
import sys
import tempfile
from pathlib import Path

import numpy as np
from harness import *  # noqa
from app import channels, formula, hadata, live, palettes, rounds
from app.examples_live import EXAMPLE_CHANNELS

bad = []
GOLD = Path(__file__).parent / "golden"
old = json.loads((GOLD / "examples_0_20_1.json").read_text())      # the examples as shipped in 0.20.1: inline inputs
gold = np.load(GOLD / "frames.npz")
lays = layouts()


def fresh(tmp: str):
    formula.DATA_DIR = channels.DATA_DIR = Path(tmp)
    channels.reset_cache()
    formula._items = None


def inline_current() -> list:
    """The examples of this release as a 0.21.0 data directory had them: the inputs written out in full."""
    return [{**e, "inputs": [{"name": i["name"], **EXAMPLE_CHANNELS[i["channel"]]} for i in e.get("inputs", [])]} for e in formula.EXAMPLES]


# 1. every example, before and after the move: the same inputs reach the engine, so the same frames (and the 0.20.1 golden frames, see test_golden)
with tempfile.TemporaryDirectory() as tmp:
    fresh(tmp)
    before = inline_current()
    (Path(tmp) / "formulas.json").write_text(json.dumps(before))
    items = {i["name"]: i for i in formula.load()}
    n_inputs = sum(len(e["inputs"]) for e in before)
    users = channels.usage(list(items.values()), [])
    n_channels = len(channels.values())
    sequences = 0
    for ex in before:
        after = items[ex["name"]]
        if any(set(i) != {"name", "channel"} for i in after["inputs"]):
            bad.append(f"{ex['name']}: inputs are not only an alias and a channel: {after['inputs']}")
        exp_after = formula.expand_inputs(after)
        exp_before = [{"name": i["name"], "channel": None, **channels.clean(i)} for i in ex["inputs"]]
        if [{k: v for k, v in i.items() if k != "channel"} for i in exp_after] != [{k: v for k, v in i.items() if k != "channel"} for i in exp_before]:
            bad.append(f"{ex['name']}: the inputs changed by the move")
            continue
        spec = {**after}
        for kind, lay in lays.items():
            for sc in range(3):
                a = run_expanded(spec, exp_after, kind, lay, sc)
                b = run_expanded(spec, [{k: v for k, v in i.items() if k != "channel"} for i in exp_before], kind, lay, sc)
                sequences += 1
                if a != b:
                    bad.append(f"{ex['name']} {kind}/{sc}: frames differ after the move")
    print(f"{sequences} sequences identical before and after the move; {n_inputs} inputs became {n_channels} channels")
    if not 0 < n_channels < n_inputs:
        bad.append(f"equal inputs were not merged ({n_channels} channels for {n_inputs} inputs)")
    # only identical inputs are one channel: every input of every channel has the same key, and no two channels have the same key
    keys = [channels.merge_key(c) for c in channels.values()]
    if len(set(keys)) != len(keys):
        bad.append("two channels with the same behaviour")
    for ex in before:
        for i, r in zip(ex["inputs"], items[ex["name"]]["inputs"]):
            if channels.merge_key(channels.get(r["channel"])) != channels.merge_key(channels.clean(i)):
                bad.append(f"{ex['name']}/{i['name']}: wired to a channel with other settings")
    names = [c["name"] for c in channels.all_channels()]
    if len({n.lower() for n in names}) != len(names):
        bad.append("channel names are not unique")
    if not any(d.name.startswith("backup-0.21-") for d in Path(tmp).iterdir()):
        bad.append("no backup of the data directory")
    else:
        bk = next(d for d in Path(tmp).iterdir() if d.name.startswith("backup-0.21-"))
        if json.loads((bk / "formulas.json").read_text()) != before:
            bad.append("the backup is not the data directory as it was")
    # once: a second start changes nothing and makes no second backup
    snap = ((Path(tmp) / "formulas.json").read_text(), (Path(tmp) / "channels.json").read_text())
    fresh(tmp)
    formula.load()
    if snap != ((Path(tmp) / "formulas.json").read_text(), (Path(tmp) / "channels.json").read_text()):
        bad.append("the second start changed the files")
    if sum(d.name.startswith("backup-") for d in Path(tmp).iterdir()) != 1:
        bad.append("a second backup was made")

# 2. inputs that differ in any setting stay separate channels; the same inputs of different formulas are one
with tempfile.TemporaryDirectory() as tmp:
    fresh(tmp)
    base = {"entity": "sensor.house_power", "attribute": "", "min": 0, "max": 100, "smooth": 1, "default": 0.4, "auto": True, "kick": 0.1}
    variants = [base] + [{**base, **ch} for ch in ({"entity": "sensor.other"}, {"attribute": "a"}, {"min": 1}, {"max": 99}, {"smooth": 2}, {"default": 0.5},
                                                   {"auto": False}, {"kick": 0.2}, {"span": 5}, {"on_states": ["on"]})]
    ids = [channels.import_input(v) for v in variants]
    if len(set(ids)) != len(variants):
        bad.append("inputs with different settings were merged")
    if channels.import_input(dict(base)) != ids[0] or len(channels.values()) != len(variants):
        bad.append("an identical input did not find its channel")

# 3. a saved data directory without formulas: a fresh install gets the system channels and no backup
with tempfile.TemporaryDirectory() as tmp:
    fresh(tmp)
    formula.load()
    if [c["id"] for c in channels.all_channels()] != ["pace", "theme"] or not (Path(tmp) / "channels.json").exists():
        bad.append("fresh install: no system channels / no file")
    if any(d.name.startswith("backup-") for d in Path(tmp).iterdir()):
        bad.append("fresh install: a backup of nothing")

# 4. a crash between the two files: channels.json is written, the formulas are still inline -> the next start finishes without duplicates
with tempfile.TemporaryDirectory() as tmp:
    fresh(tmp)
    two = [next(e for e in old if e.get("inputs")), {**next(e for e in old if e.get("inputs")), "name": "Copy"}]
    (Path(tmp) / "formulas.json").write_text(json.dumps(two))
    channels.backup("0.21")
    items = [dict(e) for e in two]
    channels.migrate_inputs(items)           # channels.json written, formulas.json not
    n = len(channels.values())
    fresh(tmp)
    after = formula.load()
    if len(channels.values()) != n or any("channel" not in i for f in after for i in f.get("inputs", [])):
        bad.append("the interrupted move was not finished cleanly")
    if (json.loads((Path(tmp) / "formulas.json").read_text())[1]["inputs"] != after[1]["inputs"]):
        bad.append("formulas.json was not rewritten")

# 5. usage, personal, rename, delete, merge with a preview
with tempfile.TemporaryDirectory() as tmp:
    fresh(tmp)
    a = channels.import_input({"entity": "sensor.a", "min": 0, "max": 10, "smooth": 1})
    a2 = channels.create({"entity": "sensor.a", "min": 0, "max": 20, "smooth": 1})["id"]
    b = channels.import_input({"entity": "sensor.b", "min": 0, "max": 10})
    code = "palette(\"fire\", x1)"
    F = [{"name": "One", "code": code, "params": [], "inputs": [{"name": "x1", "channel": a}], "mapping": "plane", "shape": "any"},
         {"name": "Two", "code": code, "params": [], "inputs": [{"name": "x1", "channel": a}, {"name": "x2", "channel": b}], "mapping": "plane", "shape": "any"},
         {"name": "Three", "code": code, "params": [], "inputs": [{"name": "x1", "channel": a2}], "mapping": "plane", "shape": "any"}]
    I = [{"key": "fx", "layers": [{"effect": "custom:Two"}]}, {"key": "other", "layers": [{"effect": "twinkle"}]}]
    u = channels.usage(F, I)
    d = {c["id"]: c for c in channels.describe(u)}
    if d[a]["count"] != 3 or d[a]["personal"] or [x["name"] for x in d[a]["used_by"]] != ["One", "Two", "fx"]:
        bad.append(f"usage of a shared channel: {d[a]['used_by']}")
    if d[b]["count"] != 2 or not d[b]["personal"]:       # one scene (and the effect made of it): personal
        bad.append(f"personal channel: {d[b]['count']} {d[b]['personal']}")
    if d[a2]["count"] != 1 or not d[a2]["personal"]:
        bad.append("personal channel (one scene)")
    p = channels.merge_preview(a2, a, u)
    if p["scenes"] != ["Three"] or [x["field"] for x in p["diff"]] != ["max"] or p["identical"]:
        bad.append(f"merge preview: {p}")
    merged = channels.merge(a2, a, F)
    if merged[2]["inputs"][0]["channel"] != a or F[2]["inputs"][0]["channel"] != a2:
        bad.append("merge did not repoint the references (or changed the input list)")
    try:
        channels.delete(a, u)
        bad.append("a channel in use was deleted")
    except channels.ChannelError:
        pass
    channels.delete(a2, {})
    try:
        channels.delete("pace", {})
        bad.append("a system channel was deleted")
    except channels.ChannelError:
        pass
    channels.update(a, {"name": "House power"})
    try:
        channels.update(b, {"name": "house POWER"})
        bad.append("two channels got one name")
    except channels.ChannelError:
        pass
    if channels.get(a)["name"] != "House power" or channels.update(a, {"smooth": 3})["smooth"] != 3.0 or channels.get(a)["entity"] != "sensor.a":
        bad.append("rename / edit")
    try:
        channels.update(a, {"min": 5, "max": 5})
        bad.append("min == max accepted")
    except channels.ChannelError:
        pass
    # a formula must point at an existing value channel; a change of a channel changes the render version of the stored effects
    try:
        formula.validate_item({"name": "x", "code": code, "inputs": [{"name": "x1", "channel": "nope"}]})
        bad.append("a formula with an unknown channel was accepted")
    except formula.FormulaError:
        pass
    try:
        formula.validate_item({"name": "x", "code": code, "inputs": [{"name": "x1", "channel": "pace"}]})
        bad.append("a formula wired to a system channel was accepted")
    except formula.FormulaError:
        pass
    v0 = formula.VERSION
    channels.update(a, {"default": 0.9})
    if formula.VERSION == v0:
        bad.append("a channel change did not invalidate the stored renders")

# 6. not bound / not available: the default value; a stored effect takes the default of the channel
with tempfile.TemporaryDirectory() as tmp:
    fresh(tmp)
    unbound = channels.create({"entity": "", "min": 0, "max": 10, "default": 0.8, "smooth": 0})["id"]
    bound = channels.create({"entity": "sensor.gone", "min": 0, "max": 10, "default": 0.25, "smooth": 0})["id"]
    spec = {"code": "gray(a1 * 0.5 + b1 * 0.25)", "params": [], "inputs": [{"name": "a1", "channel": unbound}, {"name": "b1", "channel": bound}]}
    lay = lays["wall"]
    if hadata.read_input({"entity": "", "min": 0, "max": 1}) != (None, None):
        bad.append("an unbound channel read something")
    states = {"on": True}

    def source(inp):
        return (5.0, 0.5) if states["on"] and inp["name"] == "b1" else (None, None)
    sc = live.LiveScene(spec, lay, source=source, history=lambda i: [])
    for f in range(40):
        sc.frame(now=sc.t0 + 0.1 * (f + 1))
    if abs(sc.trk["a1"].value - 0.8) > 1e-9 or abs(sc.trk["b1"].value - 0.5) > 1e-6:
        bad.append(f"live values {sc.trk['a1'].value} {sc.trk['b1'].value}")
    states["on"] = False   # the entity became unavailable
    for f in range(40, 80):
        sc.frame(now=sc.t0 + 0.1 * (f + 1))
    if abs(sc.trk["b1"].value - 0.25) > 1e-6 or sc.trk["b1"].raw is not None:
        bad.append(f"an unavailable entity did not give the default: {sc.trk['b1'].value}")
    # the stored effect: the colour is the one made from the defaults
    r = formula.render_spec(lay, {"duration": 1, "fps": 2}, formula.validate_item({"name": "s", **spec}))
    g = round(255 * 0.9 * (0.8 * 0.5 + 0.25 * 0.25))
    if any(abs(c - g) > 2 for c in r.frames[0][:3]):
        bad.append(f"a stored effect did not use the defaults: {list(r.frames[0][:3])} want {g}")

# 7. the theme channels: random (nothing fixed), fixed, from Home Assistant (stub), unavailable -> the channel's own value
with tempfile.TemporaryDirectory() as tmp:
    fresh(tmp)
    if channels.theme_override() != {}:
        bad.append("a random source fixes something")
    channels.update("pace", {"source": "fixed", "fixed": 1.3})
    channels.update("theme", {"source": "fixed", "fixed": "ice"})
    if channels.theme_override() != {"pace": 1.3, "palette": "ice"}:
        bad.append(f"fixed theme: {channels.theme_override()}")
    try:
        channels.update("theme", {"source": "fixed", "fixed": "fire"})  # near black: not a theme
        bad.append("a palette that is not a theme was accepted")
    except channels.ChannelError:
        pass
    channels.update("pace", {"source": "ha", "entity": "sensor.speed", "min": 0, "max": 10, "fixed": 1.1})
    channels.update("theme", {"source": "ha", "entity": "sensor.mood", "min": 0, "max": 4, "fixed": "ocean"})
    reads = {"sensor.speed": (7.0, 0.7), "sensor.mood": (2.0, 0.5)}
    real = hadata.read_input
    hadata.read_input = lambda inp: reads.get(inp["entity"], (None, None))
    try:
        o = channels.theme_override()
        names = palettes.theme_names()
        if o["pace"] != round(0.6 * (1.6 / 0.6) ** 0.7, 2) or o["palette"] != names[int(0.5 * len(names))]:
            bad.append(f"ha theme: {o}")
        reads.clear()
        if channels.theme_override() != {"pace": 1.1, "palette": "ocean"}:
            bad.append(f"an unavailable entity did not give the channel's own value: {channels.theme_override()}")
    finally:
        hadata.read_input = real
    # a round takes the fixed fields and picks the rest
    channels.update("theme", {"source": "random"})
    rnd = rounds.plan([{"name": "s", "shape": "any", "code": "", "inputs": [1]}], {"d": "wall"}, {}, [], override={"pace": 1.3}, rng=random.Random(1))
    if rnd["theme"]["pace"] != 1.3 or rnd["theme"]["palette"] not in palettes.theme_names():
        bad.append(f"round theme {rnd['theme']}")

# 8. the examples: taking one gives real channels (the same one that already behaves the same), nothing is created twice
with tempfile.TemporaryDirectory() as tmp:
    fresh(tmp)
    ex = next(e for e in formula.EXAMPLES if e["name"] == "Live twinkle")
    first = channels.adopt(ex["inputs"])
    n = len(channels.values())
    second = channels.adopt(ex["inputs"])
    if first != second or len(channels.values()) != n or any(i["channel"].startswith("ex:") for i in first):
        bad.append("taking an example twice made new channels")
    formula.validate_item({"name": "t", **ex, "inputs": first})
    try:
        formula.validate_item({"name": "t", **ex})
        bad.append("an example that was not taken was accepted")
    except formula.FormulaError:
        pass
    # the history of a channel (charts, replay) goes through hadata.history_points
    seen = []

    def points(entity, minutes, on_states=()):
        seen.append(entity)
        return [(0.0, 1.0), (1e12, 2.0)]
    sc_inputs = formula.expand_inputs({"inputs": first})
    rp = hadata.ReplaySource(sc_inputs, 1.0, 30.0, points=points)
    if sorted(set(seen)) != sorted({i["entity"] for i in sc_inputs if not i["attribute"] and i["entity"]}) or rp.missing != [i["name"] for i in sc_inputs if i["attribute"]]:
        bad.append(f"replay history of the channels: {sorted(set(seen))} missing {rp.missing}")

print("\n".join(bad) or "ALL OK")
sys.exit(1 if bad else 0)
