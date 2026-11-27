"""Formula effects: a tiny, safe expression language that is compiled to a Python function.

An effect is a few lines like

    n = rise(x*5, y*3, t, 6)
    palette("fire", n * 2 - y)

evaluated for every LED and every frame. The code is parsed with `ast` and only a small
whitelist is accepted (numbers, arithmetic, comparisons, ?: conditionals, calls of the functions below,
assignments to plain names). No attributes, indexing, loops, imports or strings (except the palette name),
so the formula cannot reach anything outside this module.

Variables: x y (position, y: 0 = bottom .. 1 = top, x in the real proportions), u v (0..1 across the lit
area), r a (distance and angle, in turns, from the centre), i n (LED index and count), t (0..1 loop phase),
w h (width and height of the area), seed, the user's own parameters and names assigned earlier.
Use whole numbers of cycles of t (sin(tau*2*t)) or the looping helpers (tnoise, rise) and the loop is seamless.
"""
import ast
import hashlib
import json
import math
import os
import re
import time
from pathlib import Path

import numpy as np

from . import palettes, vformula
from .effects import Rendered

TAU = 2 * math.pi
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
VERSION = 0  # bumped whenever the saved formulas change (part of the render cache key)

MAX_SRC, MAX_NODES, MAX_LINES, MAX_PARAMS = 4000, 900, 60, 8
TIME_BUDGET = 40.0  # s per render
NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{1,32}$")
PARAM_RE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
BASE_VARS = ["x", "y", "u", "v", "r", "a", "i", "n", "t", "w", "h", "seed", "now", "pace"]
CONSTS = ["tau", "pi"]


class FormulaError(ValueError):
    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.msg, self.line = message, line

    def __str__(self) -> str:
        return f"line {self.line}: {self.msg}" if self.line else self.msg


# ---- functions available to formulas -----------------------------------------------------------------
# name -> (min args, max args, description). The implementations (numpy) are in vformula.IMPL; prev(x, y) is passed in per scene.
FUNCS = {
    'sin': (1, 1, 'sin(a): sine, a in radians (use tau*cycles*t)'),
    'cos': (1, 1, 'cos(a)'),
    'atan2': (2, 2, 'atan2(y, x): angle in radians'),
    'abs': (1, 1, 'abs(a)'),
    'sqrt': (1, 1, 'sqrt(a), 0 for negatives'),
    'exp': (1, 1, 'exp(a)'),
    'floor': (1, 1, 'floor(a)'),
    'fract': (1, 1, 'fract(a): fractional part, 0..1'),
    'sign': (1, 1, 'sign(a): -1, 0 or 1'),
    'min': (2, 2, 'min(a, b)'),
    'max': (2, 2, 'max(a, b)'),
    'clamp': (3, 3, 'clamp(a, lo, hi)'),
    'step': (2, 2, 'step(edge, a): 1 when a >= edge else 0'),
    'smoothstep': (3, 3, 'smoothstep(lo, hi, a): smooth 0..1 ramp'),
    'mix': (3, 3, 'mix(a, b, k): a*(1-k) + b*k, works with colours too'),
    'tri': (1, 1, 'tri(a): triangle wave 0..1, period 1'),
    'dist': (4, 4, 'dist(x1, y1, x2, y2)'),
    'noise': (2, 2, 'noise(x, y): smooth random 0..1'),
    'noise3': (3, 3, 'noise3(x, y, z): 3D noise 0..1'),
    'tnoise': (4, 4, 'tnoise(x, y, t, k): noise that evolves over the loop and repeats exactly (k = whole cycles, 1..16)'),
    'rise': (4, 4, 'rise(x, y, t, k): noise drifting upward |k| cells per loop (negative k: down), exactly looping'),
    'hash': (1, 2, 'hash(a, b): fixed random number 0..1 for the pair, e.g. hash(i, seed) per LED'),
    'palette': (2, 2, 'palette("name", v): colour at v (0..1) of a palette, clamped; palette("theme", v) takes the palette of the round'),
    'cpalette': (2, 2, 'cpalette("name", v): the same but v wraps around (for cycling colours); cpalette("theme", v) takes the palette of the round'),
    'hsv': (3, 3, 'hsv(h, s, v): colour from hue, saturation, value (0..1)'),
    'rgb': (3, 3, 'rgb(r, g, b): colour, 0..1 each'),
    'gray': (1, 1, 'gray(a): grey colour'),
    'rotx': (3, 3, 'rotx(x, y, turns): x of the point (x, y) rotated by an angle in turns (use with roty)'),
    'roty': (3, 3, 'roty(x, y, turns): y of the point (x, y) rotated by an angle in turns'),
    'mirror': (2, 2, 'mirror(a, n): fold the angle a (turns) into n mirrored segments, 0..0.5/n (kaleidoscope: px = r*cos(tau*mirror(a, 6)))'),
    'wrap': (2, 2, 'wrap(x, p): x repeated with period p (tiling)'),
    'sat': (1, 1, 'sat(a): clamp to 0..1'),
    'prev': (2, 2, 'prev(x, y): colour of the PREVIOUS frame at that position: feedback for trails, zooming tunnels, fading (stored effects run one warm-up loop first)'),
}
PALETTE_FUNCS = {"palette", "cpalette"}

REFERENCE = {
    "variables": [
        "x, y: position. y = 0 at the bottom, 1 at the top; x follows the real proportions of the lit area",
        "u, v: position 0..1 across the lit area (left to right, bottom to top)",
        "r, a: distance and angle (in turns, -0.5..0.5) from the centre of the area",
        "i, n: number of this LED along the string and how many LEDs there are",
        "t: loop phase 0..1. Use whole cycles (sin(tau*2*t)) so the loop is seamless",
        "now: seconds since the effect started (live mode) or t * loop length (stored effect). Do not make loops with it",
        "pace: the speed multiplier of the round (0.6..1.6 in a live:random round, 1 otherwise): multiply the speeds by it, e.g. tm = now * pace, and use <input>_phase * pace",
        'palette("theme", v), cpalette("theme", v): the palette of the round (picked at random by live:random for every scene of the round; a scene started by hand or a stored effect gets the default one, rainbow)',
        "<input>_phase: for every input its running total over time (value * seconds): use it as a speed that follows data without jumps, e.g. cos(tau * (a + wind_phase * 0.1))",
        "<input>_kick: 1 at the moment the input jumps (a kettle is switched on, a CPU spike) and fading to 0 in about 1.5 s; <input>_age: seconds since the last jump; <input>_count: number of jumps so far (a seed for random places: hash(power_count, 1)); <input>_dir: +1 / -1 for a rise / fall; <input>_delta: how fast it is changing",
        "an input with auto = on maps the range of the last 30 minutes to 0..1 (so any sensor uses its whole range); the jump threshold is set per input",
        "inputs from Home Assistant: 0..1 numbers named by you (a temperature, a power, a valve...); a stored effect uses their default value, a live scene the real value",
        "w, h: width and height of the area; seed: the Seed slider; tau, pi",
        "your own parameters (they become sliders) and any name you assign: speed = 2",
    ],
    "functions": [v[2] for v in FUNCS.values()],
    "rules": [
        "One statement per line: name = expression. The last line is the colour: palette(...), hsv(...), rgb(...) or a number.",
        "Operators: + - * / % **, comparisons < > <= >= == !=, and/or, and conditions as (a if cond else b).",
        'Colours can be added, multiplied by numbers or by other colours: palette("fire", v) * brightness.',
    ],
}


# ---- compile -----------------------------------------------------------------------------------------

class _Ops(ast.NodeTransformer):
    """/, % and ** go through safe helpers (no division by zero, no huge numbers); the palette "theme" becomes the
    hidden argument _theme (the palette name of the scene's round)."""
    def visit_Call(self, node):
        self.generic_visit(node)
        if (isinstance(node.func, ast.Name) and node.func.id in PALETTE_FUNCS and node.args
                and isinstance(node.args[0], ast.Constant) and node.args[0].value == "theme"):
            node.args[0] = ast.copy_location(ast.Name(id="_theme", ctx=ast.Load()), node.args[0])
        return node

    def visit_BinOp(self, node):
        self.generic_visit(node)
        name = {ast.Div: "_div", ast.Mod: "_mod", ast.Pow: "_pow"}.get(type(node.op))
        if name:
            return ast.copy_location(ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=[node.left, node.right], keywords=[]), node)
        return node


def _err(msg, node=None):
    return FormulaError(msg, getattr(node, "lineno", None))


def _check(node, scope):
    t = type(node)
    if t is ast.Constant:
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise _err("only numbers are allowed here (text is only used for palette names)", node)
    elif t is ast.Name:
        if node.id in FUNCS:
            raise _err(f"'{node.id}' is a function, call it with brackets: {node.id}(...)", node)
        if node.id not in scope:
            raise _err(f"unknown name '{node.id}'", node)
    elif t is ast.BinOp:
        if type(node.op) not in (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow):
            raise _err("this operator is not supported", node)
        _check(node.left, scope), _check(node.right, scope)
    elif t is ast.UnaryOp:
        if type(node.op) not in (ast.USub, ast.UAdd):
            raise _err("only unary + and - are supported", node)
        _check(node.operand, scope)
    elif t is ast.Compare:
        if any(type(o) not in (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq) for o in node.ops):
            raise _err("this comparison is not supported", node)
        _check(node.left, scope)
        for c in node.comparators:
            _check(c, scope)
    elif t is ast.BoolOp:
        for v in node.values:
            _check(v, scope)
    elif t is ast.IfExp:
        _check(node.test, scope), _check(node.body, scope), _check(node.orelse, scope)
    elif t is ast.Call:
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCS:
            raise _err("unknown function", node)
        name = node.func.id
        lo, hi, _doc = FUNCS[name]
        if node.keywords or not (lo <= len(node.args) <= hi):
            raise _err(f"{name}() takes {lo if lo == hi else f'{lo}-{hi}'} argument(s)", node)
        args = node.args
        if name in PALETTE_FUNCS:
            first = args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                raise _err(f'{name}() needs a palette name in quotes first: {name}("fire", v)', node)
            if first.value != "theme" and first.value not in {p["name"] for p in palettes.listing()}:
                raise _err(f"unknown palette '{first.value}'", node)
            args = args[1:]
        for a in args:
            _check(a, scope)
    else:
        raise _err(f"{t.__name__} is not allowed in a formula", node)


_compiled: dict = {}

def compile_formula(src: str, param_names: tuple = ()):
    """Validate and compile; returns the array function f(x, y, u, v, r, a, i, n, t, w, h, seed, now, pace, prev, _theme, *params)."""
    key = (src, param_names, palettes.VERSION)
    if key in _compiled:
        return _compiled[key]
    if len(src) > MAX_SRC or src.count("\n") >= MAX_LINES:
        raise FormulaError(f"the formula is too long (max {MAX_SRC} characters, {MAX_LINES} lines)")
    try:
        tree = ast.parse(src, mode="exec")
    except SyntaxError as exc:
        raise FormulaError(f"syntax error: {exc.msg}", exc.lineno) from None
    except (RecursionError, MemoryError, ValueError):
        raise FormulaError("the formula is too complicated") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise FormulaError("the formula is too complicated (too many operations)")
    if not tree.body:
        raise FormulaError("the formula is empty: write a colour expression, e.g. palette(\"fire\", y)")
    scope = set(BASE_VARS) | set(CONSTS) | set(param_names)
    reserved = set(BASE_VARS) | set(CONSTS) | set(FUNCS) | set(param_names)
    for st in tree.body[:-1]:
        if not (isinstance(st, ast.Assign) and len(st.targets) == 1 and isinstance(st.targets[0], ast.Name)):
            raise _err("only 'name = expression' lines are allowed before the last line", st)
        name = st.targets[0].id
        if name in reserved or name.startswith("_"):
            raise _err(f"'{name}' is already used (built-in names: {', '.join(BASE_VARS)}), choose another name", st)
        _check(st.value, scope)
        scope.add(name)
    last = tree.body[-1]
    if not isinstance(last, ast.Expr):
        raise _err("the last line must be the colour expression (not an assignment)", last)
    _check(last.value, scope)

    tree = _Ops().visit(tree)
    args = BASE_VARS + ["prev", "_theme"] + list(param_names)  # prev(x, y) and the theme palette are passed in per scene (no shared state in the code)
    try:
        fn, line_map = vformula.build(tree, args)
    except TypeError as exc:  # the last line is a yes/no
        raise FormulaError(str(exc)) from None
    if len(_compiled) > 60:
        _compiled.pop(next(iter(_compiled)))
    fn.uses_prev = re.search(r"(?<![A-Za-z0-9_])prev\s*\(", src) is not None
    fn.line_map = line_map  # line of the generated function -> line the user wrote
    _compiled[key] = fn
    return fn


# ---- parameters, storage -----------------------------------------------------------------------------

INPUT_SUFFIXES = ("phase", "kick", "age", "count", "dir", "delta")


def all_names(defs: list, inputs: list) -> tuple:
    """Function arguments after the base variables: parameters, the inputs, then for every input
    <input>_phase, _kick, _age, _count, _dir, _delta (each group in the order of the inputs)."""
    return (tuple(d["name"] for d in defs) + tuple(i["name"] for i in inputs)
            + tuple(f"{i['name']}_{s}" for s in INPUT_SUFFIXES for i in inputs))


def input_defaults(inputs: list, now: float) -> list:
    """Values of the per-input extras for a stored effect (no live data): a steady input, no events."""
    out = [i["default"] * now for i in inputs]           # phase
    out += [0.0] * len(inputs)                           # kick
    out += [60.0] * len(inputs)                          # age
    out += [0.0] * len(inputs) * 3                       # count, dir, delta
    return out


def clean_params(defs) -> list:
    out, seen = [], set()
    if len(defs) > MAX_PARAMS:
        raise FormulaError(f"at most {MAX_PARAMS} parameters")
    for d in defs:
        name = str(d.get("name", "")).strip()
        if not PARAM_RE.match(name):
            raise FormulaError(f"parameter name '{name}': lowercase letters, digits and _, starting with a letter")
        if name in set(BASE_VARS) | set(CONSTS) | set(FUNCS) or name in seen or name in ("intensity", "color"):
            raise FormulaError(f"parameter name '{name}' is taken")
        seen.add(name)
        lo, hi = float(d.get("min", 0)), float(d.get("max", 1))
        if not hi > lo:
            raise FormulaError(f"parameter '{name}': max must be greater than min")
        default = min(hi, max(lo, float(d.get("default", lo))))
        step = float(d.get("step") or round((hi - lo) / 100, 4) or 0.01)
        out.append({"name": name, "label": str(d.get("label") or name)[:40], "min": lo, "max": hi, "step": step, "default": default})
    return out


ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
DEFAULT_ON_STATES = ["on", "home", "playing", "cleaning", "heat", "heating", "open", "detected"]
MAX_INPUTS = 8


def clean_inputs(inputs, taken: set) -> list:
    """Bindings of formula variables to Home Assistant entities (the value is mapped to 0..1)."""
    out = []
    if len(inputs) > MAX_INPUTS:
        raise FormulaError(f"at most {MAX_INPUTS} inputs")
    seen = set(taken)
    for d in inputs:
        name = str(d.get("name", "")).strip()
        if not PARAM_RE.match(name):
            raise FormulaError(f"input name '{name}': lowercase letters, digits and _, starting with a letter")
        if (name in set(BASE_VARS) | set(CONSTS) | set(FUNCS) or name in seen or name in ("intensity", "color")
                or any(name.endswith(f"_{s}") for s in INPUT_SUFFIXES)):
            raise FormulaError(f"input name '{name}' is taken")
        if any(f"{name}_{s}" in seen for s in INPUT_SUFFIXES):
            raise FormulaError(f"input name '{name}' clashes with another name")
        seen.add(name)
        seen.update(f"{name}_{s}" for s in INPUT_SUFFIXES)
        entity = str(d.get("entity", "")).strip()
        if not ENTITY_RE.match(entity):
            raise FormulaError(f"input '{name}': entity must look like sensor.power_total")
        lo, hi = float(d.get("min", 0)), float(d.get("max", 1))
        if lo == hi:
            raise FormulaError(f"input '{name}': min and max must differ")
        on_states = d.get("on_states") or DEFAULT_ON_STATES
        if isinstance(on_states, str):
            on_states = [x.strip().lower() for x in on_states.split(",") if x.strip()]
        out.append({"name": name, "entity": entity, "attribute": str(d.get("attribute") or "").strip(), "min": lo, "max": hi,
                    "smooth": min(120.0, max(0.0, float(d.get("smooth", 2)))), "default": min(1.0, max(0.0, float(d.get("default", 0.5)))),
                    "auto": bool(d.get("auto", False)), "span": max(0.0, float(d.get("span") or 0.0)),
                    "kick": min(0.5, max(0.02, float(d.get("kick") or 0.12))),
                    "on_states": [str(x).lower() for x in on_states]})
    return out


def validate_item(item: dict) -> dict:
    name = str(item.get("name", "")).strip()
    if not NAME_RE.match(name):
        raise FormulaError("name: 1-32 letters, digits, space, _ or -")
    defs = clean_params(item.get("params", []))
    inputs = clean_inputs(item.get("inputs", []), {d["name"] for d in defs})
    compile_formula(str(item.get("code", "")), all_names(defs, inputs))
    mapping = item.get("mapping") if item.get("mapping") in ("plane", "apex", "cone", "wrap") else "plane"
    shape = item.get("shape") if item.get("shape") in ("any", "wall", "tree") else "any"
    return {"name": name, "code": str(item["code"]), "params": defs, "inputs": inputs, "mapping": mapping, "shape": shape}


_items: list | None = None


def _path() -> Path:
    return DATA_DIR / "formulas.json"


def load() -> list:
    global _items
    if _items is None:
        try:
            _items = json.loads(_path().read_text())
        except (OSError, ValueError):
            _items = []
        migrate_saved(_items)
    return _items


def migrate_saved(items: list) -> int:
    """0.21.0: a saved formula that is still exactly one of the example scenes as shipped before (same name, same code, found by a
    hash) takes the new code of that example (theme and pace). An edited one is left alone. The old file is kept as formulas.json.bak-0.20.
    Returns how many formulas were replaced; once replaced, a formula no longer matches, so nothing is done twice."""
    new = {e["name"]: e["code"] for e in EXAMPLES}
    global VERSION
    changed = 0
    for it in items:
        legacy = LEGACY_CODE.get(it.get("name"))
        if legacy is None or hashlib.sha1(str(it.get("code", "")).encode()).hexdigest()[:16] != legacy:
            continue
        try:  # the new code needs the inputs and parameters this formula has (it only adds the names theme / pace)
            compile_formula(new[it["name"]], all_names(it.get("params", []), it.get("inputs", [])))
        except FormulaError:
            continue
        it["code"] = new[it["name"]]
        changed += 1
    if changed:
        try:
            bak = _path().with_name("formulas.json.bak-0.20")
            if not bak.exists():
                bak.write_bytes(_path().read_bytes())
            _path().write_text(json.dumps(items, indent=1))
        except OSError:
            pass  # the new code works in memory; it is saved with the next save
        VERSION += 1
    return changed


def save(items: list) -> None:
    global _items, VERSION
    clean = [validate_item(i) for i in items]
    if len({c["name"] for c in clean}) != len(clean):
        raise FormulaError("two formulas have the same name")
    _items = clean
    VERSION += 1
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(clean, indent=1))


THEME_USE = re.compile(r'"theme"|(?<![A-Za-z0-9_])pace(?![A-Za-z0-9_])')


def uses_theme(spec: dict) -> bool:
    """Does the scene follow the theme of the round (the palette "theme" or `pace`)?"""
    return THEME_USE.search(spec.get("code", "")) is not None


def get(name: str):
    return next((i for i in load() if i["name"] == name), None)


def exists(effect: str) -> bool:
    return effect.startswith("custom:") and get(effect[7:]) is not None


COMMON = [
    {"name": "intensity", "label": "Brightness", "min": 0.1, "max": 1.0, "step": 0.05, "default": 0.9},
    {"name": "seed", "label": "Seed (random variation)", "min": 0, "max": 99, "step": 1, "default": 1},
]


def catalog() -> dict:
    return {f"custom:{i['name']}": {"title": f"{i['name']} (formula)", "params": i["params"] + COMMON, "custom": True}
            for i in load()}


# ---- render ----------------------------------------------------------------------------------------------

def render_effect(effect: str, layout: list, params: dict) -> Rendered:
    if effect == "formula":
        spec = params.get("_formula")
        if not isinstance(spec, dict):
            raise FormulaError("no formula given")
        spec = validate_item({"name": "preview", **spec})
    elif effect.startswith("custom:"):
        spec = get(effect[7:])
        if spec is None:
            raise FormulaError(f"unknown formula {effect[7:]!r}")
    else:
        raise FormulaError(f"unknown effect {effect!r}")
    return render_spec(layout, params, spec)


def _line_of(exc, fn=None) -> int | None:
    tb, line = exc.__traceback__, None
    while tb:
        if tb.tb_frame.f_code.co_filename == "<formula>":
            line = tb.tb_lineno
        tb = tb.tb_next
    return getattr(fn, "line_map", {}).get(line, line) if line else None


class Prepared:
    """Per-LED constants of a layout, computed once."""
    def __init__(self, layout: list):
        xs, ys = [p["x"] for p in layout], [p["y"] for p in layout]
        x0, x1, y0, y1 = getattr(layout, "box", None) or (min(xs), max(xs), min(ys), max(ys))
        self.w, self.h = (x1 - x0) or 1.0, (y1 - y0) or 1.0
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.n = len(layout)
        x, y = np.array(xs, dtype=np.float64), np.array(ys, dtype=np.float64)
        self.arrays = (x, y, (x - x0) / self.w, (y - y0) / self.h, np.hypot(x - cx, y - cy),
                       np.arctan2(y - cy, x - cx) / TAU, np.arange(self.n, dtype=np.float64))  # x y u v r a i
        self.x0, self.y0 = x0, y0
        self._pts = list(zip(xs, ys))

    GRID = 32
    KNN = 4


def make_prev(prep: "Prepared", k: float):
    """prev(x, y) for one scene: reads the previous frame. Returns (function, state);
    set state["frame"] to the bytes of the frame just produced."""
    state = {"frame": None}
    return vformula.make_prev(prep, k, state), state


def apply_shade(buf: bytes, weights: list) -> bytes:
    """A picture (r, g, b of every LED) with every LED multiplied by its own factor."""
    a = np.frombuffer(buf, dtype=np.uint8).astype(np.float64).reshape(-1, 3)
    return (a * np.asarray(weights, dtype=np.float64)[:, None]).astype(np.uint8).tobytes()


def eval_frame(fn, prep: Prepared, t: float, now: float, seed: float, vals: list, k: float, prevfn=None,
               pace: float = 1.0, theme: str | None = None) -> bytes:
    """One frame: the formula for all LEDs at once. Raises FormulaError for mistakes in the formula
    (with the line the user wrote when the error comes from a line of the formula)."""
    n, w, h = prep.n, prep.w, prep.h
    try:
        with np.errstate(all="ignore"):
            res = fn(*prep.arrays, n, t, w, h, seed, now, pace, prevfn or vformula.prev_unbound, theme or palettes.DEFAULT_THEME["palette"], *vals)
            return vformula.frame_bytes(res, n, k)
    except FormulaError:
        raise
    except Exception as exc:  # a mistake in the formula (e.g. a colour used as a number)
        line = _line_of(exc, fn)
        msg = str(exc) if isinstance(exc, TypeError) and str(exc).startswith("the last line") else f"{type(exc).__name__}: {exc}"
        raise FormulaError(msg, line) from None


def render_spec(layout: list, params: dict, spec: dict) -> Rendered:
    """A looping movie. Inputs use their default value (a stored effect does not follow live data)."""
    defs, inputs = spec["params"], spec.get("inputs", [])
    fn = compile_formula(spec["code"], all_names(defs, inputs))
    base = [float(params.get(d["name"], d["default"])) for d in defs] + [float(i["default"]) for i in inputs]
    k = float(params.get("intensity", 0.9))
    seed = float(params.get("seed", 1))
    fps = int(params.get("fps", 10))
    duration = int(params.get("duration", 10))
    frames_n = duration * fps
    prep = Prepared(layout)
    prevfn, state = make_prev(prep, k)
    feedback = fn.uses_prev
    start, frames = time.time(), []
    for f in range(frames_n * (2 if feedback else 1)):  # feedback: one warm-up loop first, only the second is kept
        t = (f % frames_n) / frames_n
        now = t * duration
        frame = eval_frame(fn, prep, t, now, seed, base + input_defaults(inputs, now), k, prevfn)
        state["frame"] = frame
        if f >= frames_n * (1 if feedback else 0):
            frames.append(frame)
        if time.time() - start > TIME_BUDGET:
            raise FormulaError(f"too slow: rendering takes more than {int(TIME_BUDGET)} s, simplify the formula")
    return Rendered(fps=fps, frames=frames)


# ---- examples shown in the editor ----------------------------------------------------------------------------

def _p(name, label, lo, hi, default, step=None):
    return {"name": name, "label": label, "min": lo, "max": hi, "default": default, **({"step": step} if step else {})}


EXAMPLES = [
    {"name": "Rising fire", "code": """# Tongues of flame rising from the bottom.
# rise(x, y, t, k): noise that drifts upward by k cells per loop (loops exactly).
q = 0.65 * rise(x*5, y*3, t, cells) + 0.35 * rise(x*10 + 9, y*6, t, cells*2)
base = max(1 - y/height, 0) ** 1.5
heat = (q - (1 - base) * 0.85) * contrast
palette("fire", heat)""", "params": [_p("cells", "Rise speed (cells per loop)", 2, 12, 6, 1), _p("height", "Flame height", 0.5, 2.5, 1.8, 0.05), _p("contrast", "Contrast", 1, 5, 2.8, 0.1)]},
    {"name": "Rainbow rings", "code": """# Colour rings spreading from the middle of the window.
d = dist(x, y, 0, 0.45)
cpalette("rainbow", d * rings - t * speed) * (0.55 + 0.45 * sin(tau * (d * rings * 2 - t * speed)))""",
     "params": [_p("rings", "Rings", 1, 6, 2.5, 0.1), _p("speed", "Speed (whole numbers loop)", 1, 3, 1, 1)]},
    {"name": "Lava blobs", "code": """# Slow blobs of light that grow and fade (tnoise loops exactly).
q = tnoise(x * scale, y * scale, t, 3)
glow = smoothstep(0.35, 0.75, q)
palette("lava", q) * glow""", "params": [_p("scale", "Blob size", 1, 5, 2.5, 0.1)]},
    {"name": "Sparkles", "code": """# Every LED flashes once per cycle at its own random moment.
s = hash(i, seed)
on = step(hash(i, seed + 1), density)
flash = max(1 - fract(t * rate + s) * 5, 0) ** 2
hsv(fract(s * 3), 0.6, flash * on)""", "params": [_p("rate", "Flashes per loop", 1, 6, 3, 1), _p("density", "Share of LEDs", 0.1, 1, 0.5, 0.05)]},
    {"name": "Heartbeat", "code": """# A double beat that spreads outward from the centre.
tt = fract(t * beats - dist(x, y, 0, 0.4) * spread * 0.5)
g = min(exp(-((tt - 0.1) / 0.09) ** 2) + 0.7 * exp(-((tt - 0.3) / 0.1) ** 2), 1)
palette("lava", g) * (0.08 + 0.92 * g)""", "params": [_p("beats", "Beats per loop", 1, 4, 2, 1), _p("spread", "Wave spread", 0, 2, 0.6, 0.1)]},
    {"name": "Diagonal waves", "code": """# Soft diagonal bands of colour moving across the window.
k = 0.5 + 0.5 * sin(tau * (x * 1.5 + y * 2 - t * speed))
palette("ocean", k)""", "params": [_p("speed", "Speed (whole numbers loop)", 1, 3, 1, 1)]},
]

from .examples_live import LEGACY_CODE, LIVE_EXAMPLES  # noqa: E402  (data only, no import cycle)

EXAMPLES.extend(LIVE_EXAMPLES)

