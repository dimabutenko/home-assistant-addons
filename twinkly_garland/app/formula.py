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
import colorsys
import json
import math
import os
import re
import time
from pathlib import Path

from . import palettes
from .effects import Rendered

TAU = 2 * math.pi
DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
VERSION = 0  # bumped whenever the saved formulas change (part of the render cache key)

MAX_SRC, MAX_NODES, MAX_LINES, MAX_PARAMS = 4000, 900, 60, 8
TIME_BUDGET = 40.0  # s per render
NAME_RE = re.compile(r"^[A-Za-z0-9 _-]{1,32}$")
PARAM_RE = re.compile(r"^[a-z][a-z0-9_]{0,15}$")
BASE_VARS = ["x", "y", "u", "v", "r", "a", "i", "n", "t", "w", "h", "seed", "now"]
CONSTS = ["tau", "pi"]


class FormulaError(ValueError):
    def __init__(self, message: str, line: int | None = None):
        super().__init__(message)
        self.msg, self.line = message, line

    def __str__(self) -> str:
        return f"line {self.line}: {self.msg}" if self.line else self.msg


# ---- colour vector ----------------------------------------------------------------------------

class Vec:
    """RGB in 0..1; supports + - * with numbers and other colours."""
    __slots__ = ("r", "g", "b")

    def __init__(self, r, g, b):
        self.r, self.g, self.b = r, g, b

    def __add__(self, o):
        if o.__class__ is Vec:
            return Vec(self.r + o.r, self.g + o.g, self.b + o.b)
        return Vec(self.r + o, self.g + o, self.b + o)
    __radd__ = __add__

    def __sub__(self, o):
        if o.__class__ is Vec:
            return Vec(self.r - o.r, self.g - o.g, self.b - o.b)
        return Vec(self.r - o, self.g - o, self.b - o)

    def __rsub__(self, o):
        return Vec(o - self.r, o - self.g, o - self.b)

    def __mul__(self, o):
        if o.__class__ is Vec:
            return Vec(self.r * o.r, self.g * o.g, self.b * o.b)
        return Vec(self.r * o, self.g * o, self.b * o)
    __rmul__ = __mul__
    def __neg__(self): return Vec(-self.r, -self.g, -self.b)


def _num(x):
    if x.__class__ is Vec:
        raise TypeError("a colour cannot be used here, only a number")
    return x


def _div(a, b):
    if isinstance(b, Vec):
        return Vec(_div(a.r if isinstance(a, Vec) else a, b.r), _div(a.g if isinstance(a, Vec) else a, b.g),
                   _div(a.b if isinstance(a, Vec) else a, b.b))
    if b == 0:
        return 0.0
    if isinstance(a, Vec):
        return Vec(a.r / b, a.g / b, a.b / b)
    return a / b


def _mod(a, b):
    a, b = _num(a), _num(b)
    return 0.0 if b == 0 else a % b


def _pow(a, b):
    a, b = _num(a), _num(b)
    b = max(-12.0, min(12.0, b))
    if a < 0 and b != int(b):
        return 0.0
    try:
        return a ** b
    except (OverflowError, ZeroDivisionError):
        return 0.0


# ---- functions available to formulas ----------------------------------------------------------------

def _fract(x): x = _num(x); return x - math.floor(x)
def _clamp(x, a, b): return max(a, min(b, _num(x)))
def _sstep(a, b, x):
    if a == b:
        return 1.0 if x >= a else 0.0
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def _mix(a, b, t):
    if isinstance(a, Vec) or isinstance(b, Vec):
        return a * (1 - t) + b * t
    return a + (b - a) * t


def _h3(ix, iy, iz):
    n = (ix * 374761393 + iy * 668265263 + iz * 1274126177) & 0xFFFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n ^= n >> 16
    return n / 0xFFFFFFFF


_H_INV = 1.0 / 0xFFFFFFFF


def _sm(t): return t * t * (3 - 2 * t)


def _clean(x):
    if x.__class__ is Vec:
        raise TypeError("a colour cannot be used here, only a number")
    if x != x:
        return 0.0
    return -1e6 if x < -1e6 else (1e6 if x > 1e6 else x)


def _noise2(x, y):
    x, y = _clean(x), _clean(y)
    ix, iy = math.floor(x), math.floor(y)
    fx, fy = x - ix, y - iy
    fx, fy = fx * fx * (3 - 2 * fx), fy * fy * (3 - 2 * fy)
    # the four corners of the cell, the hash written out (the same numbers as _h3(ix, iy, 0) and so on)
    px, py = ix * 374761393, iy * 668265263
    px1, py1 = px + 374761393, py + 668265263
    n = (px + py) & 0xFFFFFFFF;  n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF;  a = (n ^ (n >> 16)) * _H_INV
    n = (px1 + py) & 0xFFFFFFFF; n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF;  b = (n ^ (n >> 16)) * _H_INV
    n = (px + py1) & 0xFFFFFFFF; n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF;  c = (n ^ (n >> 16)) * _H_INV
    n = (px1 + py1) & 0xFFFFFFFF; n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF; d = (n ^ (n >> 16)) * _H_INV
    return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy


def _noise3(x, y, z, pz=0):
    """3D value noise; pz > 0 makes the z lattice repeat every pz cells."""
    x, y, z = _clean(x), _clean(y), _clean(z)
    x0, y0, z0 = math.floor(x), math.floor(y), math.floor(z)
    fx, fy, fz = _sm(x - x0), _sm(y - y0), _sm(z - z0)
    ix, iy, iz = int(x0), int(y0), int(z0)
    iz0, iz1 = (iz % pz, (iz + 1) % pz) if pz else (iz, iz + 1)
    def plane(zz):
        a, b, c, d = _h3(ix, iy, zz), _h3(ix + 1, iy, zz), _h3(ix, iy + 1, zz), _h3(ix + 1, iy + 1, zz)
        return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy
    p0, p1 = plane(iz0), plane(iz1)
    return p0 + (p1 - p0) * fz


def _tnoise(x, y, t, k):
    """Noise that changes over time and repeats exactly every loop (k whole cycles of the lattice)."""
    k = max(1, min(16, int(round(_clean(k)))))
    return _noise3(x, y, (_clean(t) % 1.0) * k, k)


def _rise(x, y, t, k):
    """Noise that drifts upward by |k| lattice cells per loop (k < 0: downward); exactly looping."""
    k = _clean(k)
    p = max(2, min(24, abs(int(round(k)))))
    x, y = _clean(x), _clean(y)
    ny = y - (1 if k >= 0 else -1) * (_clean(t) % 1.0) * p
    y0, x0 = math.floor(ny), math.floor(x)
    fx, fy = _sm(x - x0), _sm(ny - y0)
    ix, iy0 = int(x0), int(y0) % p
    iy1 = (int(y0) + 1) % p
    a, b, c, d = _h3(ix, iy0, 5), _h3(ix + 1, iy0, 5), _h3(ix, iy1, 5), _h3(ix + 1, iy1, 5)
    return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy


def _hash(a, b=0):
    return _h3(int(math.floor(_clean(a))), int(math.floor(_clean(b))), 7)


def _palette(name, v):
    c = palettes.get(name).at(_clean(v))
    return Vec(c[0] / 255, c[1] / 255, c[2] / 255)


def _cpalette(name, v):
    c = palettes.get(name).cyc(_clean(v))
    return Vec(c[0] / 255, c[1] / 255, c[2] / 255)


def _hsv(h, s, v):
    h = _num(h); h -= math.floor(h)
    s = max(0, min(1, _num(s))); v = max(0, min(1, _num(v)))
    if s == 0:
        return Vec(v, v, v)
    i = int(h * 6.0); f = h * 6.0 - i
    p, q, t = v * (1.0 - s), v * (1.0 - s * f), v * (1.0 - s * (1.0 - f))
    i %= 6
    if i == 0: return Vec(v, t, p)
    if i == 1: return Vec(q, v, p)
    if i == 2: return Vec(p, v, t)
    if i == 3: return Vec(p, q, v)
    if i == 4: return Vec(t, p, v)
    return Vec(v, p, q)


def _prev_unbound(x, y):
    """Replaced per scene by bind_prev(); a formula that is only checked sees black."""
    return Vec(0.0, 0.0, 0.0)


def _rotx(x, y, ang):
    c, s = math.cos(TAU * _clean(ang)), math.sin(TAU * _clean(ang))
    return _clean(x) * c - _clean(y) * s


def _roty(x, y, ang):
    c, s = math.cos(TAU * _clean(ang)), math.sin(TAU * _clean(ang))
    return _clean(x) * s + _clean(y) * c


def _mirror(a, n):
    n = max(1.0, min(64.0, _clean(n)))
    return abs(_fract(_clean(a) * n) - 0.5) / n


def _wrap(x, p):
    p = _clean(p)
    return 0.0 if p == 0 else _clean(x) - p * math.floor(_clean(x) / p)


# name -> (callable, min args, max args, description)
FUNCS = {
    "sin": (lambda a: math.sin(_clean(a)), 1, 1, "sin(a): sine, a in radians (use tau*cycles*t)"),
    "cos": (lambda a: math.cos(_clean(a)), 1, 1, "cos(a)"),
    "atan2": (lambda a, b: math.atan2(_clean(a), _clean(b)), 2, 2, "atan2(y, x): angle in radians"),
    "abs": (lambda a: abs(_num(a)), 1, 1, "abs(a)"),
    "sqrt": (lambda a: math.sqrt(max(0.0, _num(a))), 1, 1, "sqrt(a), 0 for negatives"),
    "exp": (lambda a: math.exp(max(-50.0, min(50.0, _num(a)))), 1, 1, "exp(a)"),
    "floor": (lambda a: float(math.floor(_clean(a))), 1, 1, "floor(a)"),
    "fract": (_fract, 1, 1, "fract(a): fractional part, 0..1"),
    "sign": (lambda a: (_num(a) > 0) - (_num(a) < 0), 1, 1, "sign(a): -1, 0 or 1"),
    "min": (lambda a, b: min(_num(a), _num(b)), 2, 2, "min(a, b)"),
    "max": (lambda a, b: max(_num(a), _num(b)), 2, 2, "max(a, b)"),
    "clamp": (_clamp, 3, 3, "clamp(a, lo, hi)"),
    "step": (lambda a, x: 1.0 if _num(x) >= _num(a) else 0.0, 2, 2, "step(edge, a): 1 when a >= edge else 0"),
    "smoothstep": (_sstep, 3, 3, "smoothstep(lo, hi, a): smooth 0..1 ramp"),
    "mix": (_mix, 3, 3, "mix(a, b, k): a*(1-k) + b*k, works with colours too"),
    "tri": (lambda a: 1 - abs(2 * _fract(a) - 1), 1, 1, "tri(a): triangle wave 0..1, period 1"),
    "dist": (lambda a, b, c, d: math.hypot(_num(a) - _num(c), _num(b) - _num(d)), 4, 4, "dist(x1, y1, x2, y2)"),
    "noise": (_noise2, 2, 2, "noise(x, y): smooth random 0..1"),
    "noise3": (lambda a, b, c: _noise3(a, b, c), 3, 3, "noise3(x, y, z): 3D noise 0..1"),
    "tnoise": (_tnoise, 4, 4, "tnoise(x, y, t, k): noise that evolves over the loop and repeats exactly (k = whole cycles, 1..16)"),
    "rise": (_rise, 4, 4, "rise(x, y, t, k): noise drifting upward |k| cells per loop (negative k: down), exactly looping"),
    "hash": (_hash, 1, 2, "hash(a, b): fixed random number 0..1 for the pair, e.g. hash(i, seed) per LED"),
    "palette": (_palette, 2, 2, 'palette("name", v): colour at v (0..1) of a palette, clamped'),
    "cpalette": (_cpalette, 2, 2, 'cpalette("name", v): the same but v wraps around (for cycling colours)'),
    "hsv": (_hsv, 3, 3, "hsv(h, s, v): colour from hue, saturation, value (0..1)"),
    "rgb": (lambda a, b, c: Vec(_clamp(a, 0, 1), _clamp(b, 0, 1), _clamp(c, 0, 1)), 3, 3, "rgb(r, g, b): colour, 0..1 each"),
    "gray": (lambda a: Vec(_clamp(a, 0, 1), _clamp(a, 0, 1), _clamp(a, 0, 1)), 1, 1, "gray(a): grey colour"),
    "rotx": (_rotx, 3, 3, "rotx(x, y, turns): x of the point (x, y) rotated by an angle in turns (use with roty)"),
    "roty": (_roty, 3, 3, "roty(x, y, turns): y of the point (x, y) rotated by an angle in turns"),
    "mirror": (_mirror, 2, 2, "mirror(a, n): fold the angle a (turns) into n mirrored segments, 0..0.5/n (kaleidoscope: px = r*cos(tau*mirror(a, 6)))"),
    "wrap": (_wrap, 2, 2, "wrap(x, p): x repeated with period p (tiling)"),
    "sat": (lambda a: _clamp(a, 0, 1), 1, 1, "sat(a): clamp to 0..1"),
    "prev": (_prev_unbound, 2, 2, "prev(x, y): colour of the PREVIOUS frame at that position: feedback for trails, zooming tunnels, fading (stored effects run one warm-up loop first)"),
}
PALETTE_FUNCS = {"palette", "cpalette"}
GLOBALS = {"__builtins__": {}, "tau": TAU, "pi": math.pi, "_div": _div, "_mod": _mod, "_pow": _pow,
           **{k: v[0] for k, v in FUNCS.items()}}

REFERENCE = {
    "variables": [
        "x, y: position. y = 0 at the bottom, 1 at the top; x follows the real proportions of the lit area",
        "u, v: position 0..1 across the lit area (left to right, bottom to top)",
        "r, a: distance and angle (in turns, -0.5..0.5) from the centre of the area",
        "i, n: number of this LED along the string and how many LEDs there are",
        "t: loop phase 0..1. Use whole cycles (sin(tau*2*t)) so the loop is seamless",
        "now: seconds since the effect started (live mode) or t * loop length (stored effect). Do not make loops with it",
        "<input>_phase: for every input its running total over time (value * seconds): use it as a speed that follows data without jumps, e.g. cos(tau * (a + wind_phase * 0.1))",
        "<input>_kick: 1 at the moment the input jumps (a kettle is switched on, a CPU spike) and fading to 0 in about 1.5 s; <input>_age: seconds since the last jump; <input>_count: number of jumps so far (a seed for random places: hash(power_count, 1)); <input>_dir: +1 / -1 for a rise / fall; <input>_delta: how fast it is changing",
        "an input with auto = on maps the range of the last 30 minutes to 0..1 (so any sensor uses its whole range); the jump threshold is set per input",
        "inputs from Home Assistant: 0..1 numbers named by you (a temperature, a power, a valve...); a stored effect uses their default value, a live scene the real value",
        "w, h: width and height of the area; seed: the Seed slider; tau, pi",
        "your own parameters (they become sliders) and any name you assign: speed = 2",
    ],
    "functions": [v[3] for v in FUNCS.values()],
    "rules": [
        "One statement per line: name = expression. The last line is the colour: palette(...), hsv(...), rgb(...) or a number.",
        "Operators: + - * / % **, comparisons < > <= >= == !=, and/or, and conditions as (a if cond else b).",
        'Colours can be added, multiplied by numbers or by other colours: palette("fire", v) * brightness.',
    ],
}


# ---- compile -----------------------------------------------------------------------------------------

class _Ops(ast.NodeTransformer):
    """/, % and ** go through safe helpers (no division by zero, no huge numbers)."""
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
        _, lo, hi, _doc = FUNCS[name]
        if node.keywords or not (lo <= len(node.args) <= hi):
            raise _err(f"{name}() takes {lo if lo == hi else f'{lo}-{hi}'} argument(s)", node)
        args = node.args
        if name in PALETTE_FUNCS:
            first = args[0]
            if not (isinstance(first, ast.Constant) and isinstance(first.value, str)):
                raise _err(f'{name}() needs a palette name in quotes first: {name}("fire", v)', node)
            if first.value not in {p["name"] for p in palettes.listing()}:
                raise _err(f"unknown palette '{first.value}'", node)
            args = args[1:]
        for a in args:
            _check(a, scope)
    else:
        raise _err(f"{t.__name__} is not allowed in a formula", node)


_compiled: dict = {}

PER_LED = {"x", "y", "u", "v", "r", "a", "i", "prev"}


def _invariant(node, inv: set) -> bool:
    """True when the expression gives the same number for every LED (it uses only the time, the parameters and such)."""
    if isinstance(node, ast.Name):
        return node.id in inv
    if isinstance(node, ast.Call):
        return all(_invariant(a, inv) for a in node.args if not isinstance(a, ast.Constant) or not isinstance(a.value, str))
    return all(_invariant(c, inv) for c in ast.iter_child_nodes(node) if not isinstance(c, (ast.operator, ast.unaryop, ast.cmpop, ast.boolop, ast.expr_context)))


def _split(tree, param_names):
    """Moves what does not depend on the LED out of the per-LED code: it is computed once per frame, not 600 times.
    Returns (pre_lines, body_statements, outputs) or None. Only expressions that are always evaluated are moved (a branch of
    a condition stays where it is), so the numbers are exactly the same; if the part computed in advance fails, the caller
    falls back to the plain function."""
    counts = {}
    for st in tree.body[:-1]:
        counts[st.targets[0].id] = counts.get(st.targets[0].id, 0) + 1
    inv = (set(BASE_VARS) - PER_LED) | set(CONSTS) | set(param_names)
    pre, outs, memo = [], [], {}

    def hoist(node):
        if isinstance(node, (ast.Constant, ast.Name)):
            return node
        if _invariant(node, inv):
            key = ast.unparse(node)
            if key not in memo:
                memo[key] = f"_c{len(memo)}"
                pre.append(f"{memo[key]} = {key}"); outs.append(memo[key])
            return ast.copy_location(ast.Name(id=memo[key], ctx=ast.Load()), node)
        if isinstance(node, ast.IfExp):
            node.test = hoist(node.test)
        elif isinstance(node, ast.BoolOp):
            node.values[0] = hoist(node.values[0])
        elif isinstance(node, ast.Compare):
            node.left = hoist(node.left)
            if len(node.comparators) == 1:
                node.comparators[0] = hoist(node.comparators[0])
        elif isinstance(node, ast.BinOp):
            node.left, node.right = hoist(node.left), hoist(node.right)
        elif isinstance(node, ast.UnaryOp):
            node.operand = hoist(node.operand)
        elif isinstance(node, ast.Call):
            node.args = [a if isinstance(a, ast.Constant) else hoist(a) for a in node.args]
        return node

    body = []
    for st in tree.body[:-1]:
        name = st.targets[0].id
        if counts[name] == 1 and _invariant(st.value, inv):
            pre.append(f"{name} = {ast.unparse(st.value)}"); outs.append(name); inv.add(name)
            continue
        st.value = hoist(st.value)
        body.append(st)
    last = tree.body[-1]
    last.value = hoist(last.value)
    body.append(last)
    return (pre, body, outs) if outs else None


def compile_formula(src: str, param_names: tuple = ()):
    """Validate and compile; returns the function f(x, y, u, v, r, a, i, n, t, w, h, seed, *params)."""
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
    args = BASE_VARS + ["prev"] + list(param_names)  # prev(x, y) is passed in per scene (no shared state in the code)
    # The checked and transformed tree is written out as ordinary source text and compiled the normal way
    # (hand-assembled ASTs with positions that do not fit together are an unusual input for the compiler).
    def source(name, argl, body_nodes, head=()):
        lines, line_map = [f"def {name}({', '.join(argl)}):"] + ["    " + x for x in head], {}
        for st in body_nodes[:-1]:
            lines.append("    " + ast.unparse(st))
            line_map[len(lines)] = st.lineno
        lines.append("    return " + ast.unparse(body_nodes[-1].value))
        line_map[len(lines)] = body_nodes[-1].lineno
        return lines, line_map

    lines, line_map = source("_f", args, list(tree.body))
    ns = dict(GLOBALS)
    exec(compile("\n".join(lines) + "\n", "<formula>", "exec"), ns)
    fn = ns["_f"]
    # the fastest way: all LEDs at once with numpy (vformula.py); None when numpy is missing or the formula does not fit
    fn.vec = None
    try:
        from . import vformula
        fn.vec = vformula.build(tree, args)
    except Exception:
        fn.vec = None
    # the faster way without numpy: what is the same for every LED is computed once per frame (see _split)
    fn.split = None
    try:
        sp = _split(tree, param_names)  # after the plain function was written out: the tree is changed here
        if sp:
            pre, body, outs = sp
            pargs = [v for v in BASE_VARS if v not in PER_LED] + list(param_names)
            ptxt = "\n".join([f"def _pre({', '.join(pargs)}):"] + ["    " + x for x in pre] + [f"    return ({', '.join(outs)},)"]) + "\n"
            blines, bmap = source("_b", args + ["_k"], body, head=[f"({', '.join(outs)},) = _k"])
            ns2 = dict(GLOBALS)
            exec(compile(ptxt, "<pre>", "exec"), ns2)
            exec(compile("\n".join(blines) + "\n", "<formula>", "exec"), ns2)
            ns2["_b"].line_map = bmap
            fn.split = (ns2["_pre"], ns2["_b"])
    except Exception:  # whatever goes wrong here, the plain function still works
        fn.split = None
    if len(_compiled) > 60:
        _compiled.pop(next(iter(_compiled)))
    fn.uses_prev = re.search(r"\bprev\s*\(", src) is not None
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
    return {"name": name, "code": str(item["code"]), "params": defs, "inputs": inputs}


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
    return _items


def save(items: list) -> None:
    global _items, VERSION
    clean = [validate_item(i) for i in items]
    if len({c["name"] for c in clean}) != len(clean):
        raise FormulaError("two formulas have the same name")
    _items = clean
    VERSION += 1
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    _path().write_text(json.dumps(clean, indent=1))


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


def _rgb(res, k):
    if isinstance(res, Vec):
        r, g, b = res.r, res.g, res.b
    elif isinstance(res, (int, float)) and not isinstance(res, bool):
        r = g = b = res
    else:
        raise TypeError("the last line must give a colour (palette, hsv, rgb, gray) or a number")
    out = []
    for c in (r, g, b):
        c = 0.0 if c != c else c
        out.append(min(255, max(0, int(c * 255 * k))))
    return bytes(out)


class Prepared:
    """Per-LED constants of a layout, computed once."""
    def __init__(self, layout: list):
        xs, ys = [p["x"] for p in layout], [p["y"] for p in layout]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        self.w, self.h = (x1 - x0) or 1.0, (y1 - y0) or 1.0
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        self.n = len(layout)
        self.per = [(p["x"], p["y"], (p["x"] - x0) / self.w, (p["y"] - y0) / self.h, math.hypot(p["x"] - cx, p["y"] - cy),
                     math.atan2(p["y"] - cy, p["x"] - cx) / TAU, i) for i, p in enumerate(layout)]
        self.x0, self.y0 = x0, y0
        self._pts = [(p["x"], p["y"]) for p in layout]
        self._grid = None
        self._arr = None

    def arrays(self):
        """x, y, u, v, r, a, i of all LEDs as numpy arrays (for vformula)."""
        if self._arr is None:
            import numpy as np
            self._arr = tuple(np.array([row[j] for row in self.per], dtype=np.float64) for j in range(7))
        return self._arr

    GRID = 32
    KNN = 4

    def neighbours(self, x: float, y: float) -> list:
        """The few LEDs around (x, y) as (index, weight), weights adding up to 1: lets the previous frame
        be sampled between LEDs (a zoom of 2% per frame is much smaller than the LED spacing)."""
        G = self.GRID
        if self._grid is None:
            self._grid = []
            for gy in range(G):
                for gx in range(G):
                    px, py = self.x0 + (gx + 0.5) / G * self.w, self.y0 + (gy + 0.5) / G * self.h
                    near = sorted(range(self.n), key=lambda j: (self._pts[j][0] - px) ** 2 + (self._pts[j][1] - py) ** 2)[:self.KNN + 2]
                    self._grid.append(near)
        gx = min(G - 1, max(0, int((x - self.x0) / self.w * G)))
        gy = min(G - 1, max(0, int((y - self.y0) / self.h * G)))
        cand = self._grid[gy * G + gx]
        ds = sorted(((self._pts[j][0] - x) ** 2 + (self._pts[j][1] - y) ** 2, j) for j in cand)[:self.KNN]
        ws = [1.0 / (d + 0.0006) for d, _ in ds]
        tot = sum(ws)
        return [(j, w / tot) for (_, j), w in zip(ds, ws)]


def make_prev(prep: "Prepared", k: float):
    """prev(x, y) for one scene: reads the previous frame. Returns (function, state);
    set state["frame"] to the bytes of the frame just produced."""
    state = {"frame": None}
    inv = 1.0 / (255.0 * max(k, 0.05))

    def prev(x, y):
        fr = state["frame"]
        if fr is None:
            return Vec(0.0, 0.0, 0.0)
        r = g = b = 0.0
        for j, w in prep.neighbours(_clean(x), _clean(y)):
            r += fr[3 * j] * w
            g += fr[3 * j + 1] * w
            b += fr[3 * j + 2] * w
        return Vec(min(1.0, r * inv), min(1.0, g * inv), min(1.0, b * inv))

    holder = []

    def vec(x, y):  # the array version for vformula, built when first used
        if not holder:
            from . import vformula
            holder.append(vformula.make_prev_vec(prep, k, state))
        return holder[0](x, y)

    prev.vec = vec
    return prev, state


def _prev_unbound_vec(x, y):
    return Vec(0.0, 0.0, 0.0)


def eval_frame(fn, prep: Prepared, t: float, now: float, seed: float, vals: list, k: float, prevfn=None) -> bytes:
    """One frame: the formula for every LED. Raises FormulaError for mistakes in the formula."""
    buf = bytearray()
    n, w, h = prep.n, prep.w, prep.h
    vec = getattr(fn, "vec", None)
    if vec is not None:  # all LEDs at once; anything unusual falls back to the plain function below
        try:
            from . import vformula
            pv = getattr(prevfn, "vec", None) if prevfn else _prev_unbound_vec
            if pv is None:
                raise TypeError("no array version of prev")
            with vformula.np.errstate(all="ignore"):
                return vformula.frame_bytes(vec(*prep.arrays(), n, t, w, h, seed, now, pv, *vals), n, k)
        except Exception:
            fn.vec = None
    prevfn = prevfn or _prev_unbound
    call, tail = fn, vals
    if fn.split is not None:  # what is the same for every LED is computed once; if that fails the plain function reports it
        try:
            tail = list(vals) + [fn.split[0](n, t, w, h, seed, now, *vals)]
            call = fn.split[1]
        except Exception:
            pass
    for x, y, u, v, r, a, i in prep.per:
        try:
            res = call(x, y, u, v, r, a, i, n, t, w, h, seed, now, prevfn, *tail)
        except (ZeroDivisionError, OverflowError, ValueError):
            res = 0.0
        except Exception as exc:  # a mistake in the formula (e.g. a colour used as a number)
            raise FormulaError(f"{type(exc).__name__}: {exc}", _line_of(exc, call)) from None
        try:
            buf += _rgb(res, k)
        except TypeError as exc:
            raise FormulaError(str(exc)) from None
    return bytes(buf)


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

from .examples_live import LIVE_EXAMPLES  # noqa: E402  (data only, no import cycle)

EXAMPLES.extend(LIVE_EXAMPLES)

