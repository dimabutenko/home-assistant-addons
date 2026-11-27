"""0.21.0: the theme of a round (palette("theme", v), pace), the choice of the scenes of a live:random round by shape, and the move of
saved formulas to the new examples. Run from twinkly_garland/: python tests/test_theme.py"""
import json
import random
import sys
import tempfile
from pathlib import Path

from harness import *  # noqa
from app import formula, palettes, rounds

bad = []
lay = layouts()["wall"]
old = {e["name"]: e for e in json.loads((Path(__file__).parent / "golden" / "examples_0_20_1.json").read_text())}


def frames(spec, theme=None, pace=1.0):
    spec = formula.validate_item({"name": "t", **spec})
    defs, inputs = spec["params"], spec["inputs"]
    fn = formula.compile_formula(spec["code"], formula.all_names(defs, inputs))
    prep = formula.Prepared(lay)
    prevfn, state = formula.make_prev(prep, 0.9)
    T = scenarios(inputs)[1]
    out = []
    for f in range(N_FRAMES):
        state["frame"] = out[-1] if out else None
        vals = frame_vals(defs, inputs, [(a, b + f * 0.1, c, d + f * 0.5, e, g, h) for a, b, c, d, e, g, h in T])
        out.append(formula.eval_frame(fn, prep, (f * 0.137) % 1.0, 2.0 + f * 0.5, 1.0, vals, 0.9, prevfn, pace, theme))
    return out


# 1. a scene that only gained `pace` is the same picture at pace 1; every scene reacts to the theme / pace it uses
for ex in formula.EXAMPLES:
    if not ex.get("inputs"):
        continue
    if not formula.uses_theme(ex):
        bad.append(f"{ex['name']}: neither theme nor pace")
    elif '"theme"' not in ex["code"] and frames(ex, "neon", 1.0) != frames(old[ex["name"]], "neon", 1.0):
        bad.append(f"{ex['name']}: pace 1 changed the picture")
    if "pace" in ex["code"] and frames(ex, "aurora", 1.0) == frames(ex, "aurora", 1.6):
        bad.append(f"{ex['name']}: pace has no effect")
    if '"theme"' in ex["code"] and frames(ex, "aurora") == frames(ex, "ice"):
        bad.append(f"{ex['name']}: the theme has no effect")
    if ex["shape"] not in ("any", "wall", "tree"):
        bad.append(f"{ex['name']}: bad shape")


# 2. the language: palette("theme") is the named palette, cpalette too, pace multiplies, the default theme is rainbow, names are reserved
def one(code, theme=None, pace=1.0):
    return frames({"code": code, "params": [], "inputs": []}, theme, pace)


for name in ("ocean", "neon"):
    if one('palette("theme", u)', name) != one(f'palette("{name}", u)'):
        bad.append(f"palette theme != {name}")
    if one('cpalette("theme", u * 3 + now)', name) != one(f'cpalette("{name}", u * 3 + now)'):
        bad.append(f"cpalette theme != {name}")
if one('palette("theme", u)') != one('palette("rainbow", u)'):
    bad.append("default theme is not rainbow")
if one("gray(sat(fract(now * pace)))", None, 2.0) != one("gray(sat(fract(now * 2)))"):
    bad.append("pace does not multiply")
for code in ('palette("themes", u)', "pace = 2\ngray(pace)", "gray(_theme)"):
    try:
        one(code)
        bad.append(f"accepted: {code!r}")
    except formula.FormulaError:
        pass
try:
    formula.clean_params([{"name": "pace"}])
    bad.append("param pace accepted")
except formula.FormulaError:
    pass
if not any("theme" in l for l in formula.REFERENCE["variables"]) or not any("pace" in l for l in formula.REFERENCE["variables"]):
    bad.append("theme / pace are not in the reference")

# 3. a round: shapes, a shared theme, joining, preference for the scenes that use the theme
scenes = [{"name": n, "shape": s, "code": c, "inputs": [1]} for n, s, c in [
    ("w1", "wall", 'palette("theme", u)'), ("w2", "wall", "gray(1)"), ("t1", "tree", 'palette("theme", u)'),
    ("a1", "any", 'palette("theme", u)'), ("a2", "any", "gray(1)")]]
rng = random.Random(3)
shared = 0
for _ in range(300):
    p = rounds.plan(scenes, {"lamp": "wall", "tree": "tree"}, {"lamp": None, "tree": None}, [], rng=rng)
    got = {d: g["scene"] for g in p["groups"] for d in g["devices"]}
    if got["lamp"] not in ("w1", "w2", "a1", "a2") or got["tree"] not in ("t1", "a1", "a2"):
        bad.append(f"round gave {got}")
        break
    shared += got["lamp"] == got["tree"]
    if got["lamp"] in ("a1", "a2") and got["tree"] != got["lamp"]:
        bad.append(f"an 'any' scene of the wall was not shared: {got}")
        break
if not shared:
    bad.append("the garlands never shared a scene")
# no scene for a shape: an error for that garland only
p = rounds.plan([s for s in scenes if s["shape"] == "wall"], {"lamp": "wall", "tree": "tree"}, {}, [], rng=rng)
errs = {d: g["error"] for g in p["groups"] for d in g["devices"]}
if errs["lamp"] or not errs["tree"]:
    bad.append(f"errors {errs}")
# a garland that asks a moment after another one: the same theme, and the scene if it may play it
p = rounds.plan(scenes, {"tree": "tree"}, {"tree": None}, [("a1", {"palette": "ice", "pace": 1.3})], rng=rng)
if p["theme"] != {"palette": "ice", "pace": 1.3} or p["groups"][0]["scene"] != "a1":
    bad.append(f"follow: {p}")
p = rounds.plan(scenes, {"tree": "tree"}, {"tree": None}, [("w1", {"palette": "ice", "pace": 1.3})], rng=rng)
if p["theme"]["palette"] != "ice" or p["groups"][0]["scene"] not in ("t1", "a1", "a2"):
    bad.append(f"follow with another shape: {p}")
# the running scene is not picked again; with nothing else it is kept
p = rounds.plan(scenes, {"lamp": "wall"}, {"lamp": "w1"}, [], rng=rng)
if p["groups"][0]["scene"] == "w1":
    bad.append("the running scene was picked again")
p = rounds.plan([scenes[0]], {"lamp": "wall"}, {"lamp": "w1"}, [], rng=rng)
if not p["groups"][0]["kept"]:
    bad.append("the only scene was not kept")
# scenes that use the theme are preferred (weight 3 : 1), the palette changes between rounds
n_themed = sum(rounds.plan(scenes, {"lamp": "wall"}, {"lamp": None}, [], rng=random.Random(k))["groups"][0]["scene"] in ("w1", "a1") for k in range(600))
if not 0.6 < n_themed / 600 < 0.9:
    bad.append(f"themed share {n_themed / 600}")
for k in range(50):
    th = palettes.pick_theme({"aurora", "ice"}, random.Random(k))
    if th["palette"] in ("aurora", "ice", "fire", "lava", "storm") or not 0.6 <= th["pace"] <= 1.6:
        bad.append(f"theme {th}")
        break

# 4. saved formulas: an example as it was shipped moves to the new code, an edited one stays; the old file is kept
with tempfile.TemporaryDirectory() as tmp:
    formula.DATA_DIR = Path(tmp)
    edited = {**old["Live rain"], "code": old["Live rain"]["code"] + "\n"}
    other = {**old["Live candy"], "name": "Candy copy"}
    (Path(tmp) / "formulas.json").write_text(json.dumps([old["Live twinkle"], edited, other, old["Live helix"]]))
    formula._items = None
    items = {i["name"]: i for i in formula.load()}
    ex = {e["name"]: e for e in formula.EXAMPLES}
    if items["Live twinkle"]["code"] != ex["Live twinkle"]["code"] or items["Live helix"]["code"] != ex["Live helix"]["code"]:
        bad.append("saved examples were not moved")
    if items["Live rain"]["code"] != edited["code"] or items["Candy copy"]["code"] != other["code"]:
        bad.append("an edited formula was touched")
    if json.loads((Path(tmp) / "formulas.json.bak-0.20").read_text())[0]["code"] != old["Live twinkle"]["code"]:
        bad.append("no backup of the old file")
    if json.loads((Path(tmp) / "formulas.json").read_text())[0]["code"] != ex["Live twinkle"]["code"]:
        bad.append("the moved formulas were not saved")
    if formula.migrate_saved([dict(i) for i in items.values()]) != 0:
        bad.append("the move is not once")
    formula._items = None

print("\n".join(bad) or "ALL OK")
sys.exit(1 if bad else 0)
