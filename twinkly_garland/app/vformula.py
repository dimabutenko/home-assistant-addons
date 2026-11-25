"""The same formulas as formula.py, but computed for all LEDs at once with numpy.

formula.py checks a formula and compiles it into a Python function that is called for every LED. Here the SAME checked
syntax tree is written out as a function that works on arrays (one number per LED): every position variable is an array,
every function a numpy one, a condition (a if c else b) computes both sides and picks per LED. The pictures are the same
as the scalar ones (to a rounding of one step of a colour channel); on the Home Assistant host this is 5 to 10 times
cheaper than 600 calls of the scalar function.

It is an acceleration only: whatever does not fit (a colour used as a number, a parameter of a function that has to be one
number but differs per LED, numpy missing) raises here, and formula.eval_frame then uses the scalar function, which also
produces the error messages with the line of the formula.
"""
import ast
import copy
import math

try:
    import numpy as np
except ImportError:  # the scalar engine still works
    np = None

from . import formula, palettes
from .formula import FUNCS, Vec

TAU = 2 * math.pi
M32 = 0xFFFFFFFF


def available() -> bool:
    return np is not None


# ---- numbers ------------------------------------------------------------------------------------------

def _num(x):
    if x.__class__ is Vec:
        raise TypeError("a colour cannot be used here, only a number")
    return x


def C(x):
    """formula._clean for numbers and arrays: NaN becomes 0, the rest is held within +-1e6."""
    if x.__class__ is Vec:
        raise TypeError("a colour cannot be used here, only a number")
    return np.clip(np.nan_to_num(x, nan=0.0, posinf=1e6, neginf=-1e6), -1e6, 1e6)


def _scalar(x, what):
    a = np.asarray(_num(x))
    if a.size != 1:
        raise ValueError(f"{what} has to be one number, not one per LED")
    return float(a.reshape(()))


def _fract(x):
    x = _num(x)
    return x - np.floor(x)


def _div(a, b):
    if b.__class__ is Vec:
        ar, ag, ab = (a.r, a.g, a.b) if a.__class__ is Vec else (a, a, a)
        return Vec(_div(ar, b.r), _div(ag, b.g), _div(ab, b.b))
    z = np.asarray(b) == 0
    q = np.where(z, 1.0, b)
    if a.__class__ is Vec:
        return Vec(np.where(z, 0.0, a.r / q), np.where(z, 0.0, a.g / q), np.where(z, 0.0, a.b / q))
    return np.where(z, 0.0, a / q)


def _mod(a, b):
    a, b = _num(a), _num(b)
    z = np.asarray(b) == 0
    return np.where(z, 0.0, np.mod(a, np.where(z, 1.0, b)))


def _pow(a, b):
    a, b = _num(a), _num(b)
    b = np.clip(b, -12.0, 12.0)
    r = np.power(a, b)
    return np.where(np.isfinite(r), r, 0.0)


def _c(x):
    """A comparison gives 1.0 or 0.0 (adding two of them must give 2, not 'or')."""
    return np.asarray(x).astype(np.float64)


def _where(test, a, b):
    t = np.asarray(_num(test)) != 0
    if a.__class__ is Vec or b.__class__ is Vec:
        a = a if a.__class__ is Vec else Vec(a, a, a)
        b = b if b.__class__ is Vec else Vec(b, b, b)
        return Vec(np.where(t, a.r, b.r), np.where(t, a.g, b.g), np.where(t, a.b, b.b))
    return np.where(t, a, b)


def _and(a, b):
    return np.where(np.asarray(_num(a)) != 0, _num(b), a)


def _or(a, b):
    return np.where(np.asarray(_num(a)) != 0, a, _num(b))


# ---- noise -------------------------------------------------------------------------------------------

def _h(ix, iy, iz):
    n = (ix * 374761393 + iy * 668265263 + iz * 1274126177) & M32
    n = ((n ^ (n >> 13)) * 1274126177) & M32
    n = n ^ (n >> 16)
    return n / 4294967295.0


def _cell(x):
    f = np.floor(x)
    return f.astype(np.int64), x - f


def _sm(t):
    return t * t * (3 - 2 * t)


def _noise2(x, y):
    x, y = C(x), C(y)
    ix, fx = _cell(x)
    iy, fy = _cell(y)
    fx, fy = _sm(fx), _sm(fy)
    a, b, c, d = _h(ix, iy, 0), _h(ix + 1, iy, 0), _h(ix, iy + 1, 0), _h(ix + 1, iy + 1, 0)
    return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy


def _noise3(x, y, z, pz=0):
    x, y, z = C(x), C(y), C(z)
    ix, fx = _cell(x)
    iy, fy = _cell(y)
    iz, fz = _cell(z)
    fx, fy, fz = _sm(fx), _sm(fy), _sm(fz)
    iz0, iz1 = (iz % pz, (iz + 1) % pz) if (np.ndim(pz) > 0 or pz) else (iz, iz + 1)

    def plane(zz):
        a, b, c, d = _h(ix, iy, zz), _h(ix + 1, iy, zz), _h(ix, iy + 1, zz), _h(ix + 1, iy + 1, zz)
        return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy
    p0, p1 = plane(iz0), plane(iz1)
    return p0 + (p1 - p0) * fz


def _tnoise(x, y, t, k):
    k = np.clip(np.round(C(k)), 1, 16).astype(np.int64)  # one number or one per LED
    return _noise3(x, y, (C(t) % 1.0) * k, k)


def _rise(x, y, t, k):
    k = C(k)
    p = np.clip(np.abs(np.round(k)), 2, 24).astype(np.int64)
    x, y = C(x), C(y)
    ny = y - np.where(k >= 0, 1, -1) * (C(t) % 1.0) * p
    iy, fy = _cell(ny)
    ix, fx = _cell(x)
    fx, fy = _sm(fx), _sm(fy)
    iy0, iy1 = iy % p, (iy + 1) % p
    a, b, c, d = _h(ix, iy0, 5), _h(ix + 1, iy0, 5), _h(ix, iy1, 5), _h(ix + 1, iy1, 5)
    return (a + (b - a) * fx) * (1 - fy) + (c + (d - c) * fx) * fy


def _hash(a, b=0):
    return _h(np.floor(C(a)).astype(np.int64), np.floor(C(b)).astype(np.int64), 7)


# ---- colours -------------------------------------------------------------------------------------------

_luts: dict = {}


def _lut(name):
    key = (name, palettes.VERSION)
    if key not in _luts:
        p = palettes.get(name)
        _luts[key] = (np.array(p.lut, dtype=np.float64) / 255.0, p.closed)
        if len(_luts) > 80:
            _luts.pop(next(iter(_luts)))
    return _luts[key]


def _palette(name, v):
    lut, _closed = _lut(name)
    c = lut[np.floor(np.clip(C(v), 0.0, 1.0) * 255 + 0.5).astype(np.int64)]
    return Vec(c[..., 0], c[..., 1], c[..., 2])


def _cpalette(name, v):
    lut, closed = _lut(name)
    v = C(v)
    v = v - np.where(v >= 0, np.trunc(v), np.trunc(v) - 1)
    if not closed:
        v = 1 - np.abs(2 * v - 1)
    c = lut[np.floor(v * 255 + 0.5).astype(np.int64)]
    return Vec(c[..., 0], c[..., 1], c[..., 2])


def _hsv(h, s, v):
    h = _fract(h)
    s = np.clip(_num(s), 0.0, 1.0)
    v = np.clip(_num(v), 0.0, 1.0)
    i6 = np.floor(h * 6.0)
    f = h * 6.0 - i6
    i6 = i6.astype(np.int64) % 6
    p, q, t = v * (1.0 - s), v * (1.0 - s * f), v * (1.0 - s * (1.0 - f))
    shape = np.broadcast(i6, p, q, t, v).shape
    parts = [np.broadcast_to(a, shape) for a in (v, q, p, p, t, v)], [np.broadcast_to(a, shape) for a in (t, v, v, q, p, p)], \
            [np.broadcast_to(a, shape) for a in (p, p, t, v, v, q)]
    i6 = np.broadcast_to(i6, shape)
    return Vec(*(np.choose(i6, ch) for ch in parts))


def _cl01(x):
    return np.clip(_num(x), 0.0, 1.0)


def _smoothstep(a, b, x):
    a, b, x = _num(a), _num(b), _num(x)
    same = np.asarray(a) == np.asarray(b)
    t = np.clip((x - a) / np.where(same, 1.0, b - a), 0.0, 1.0)
    return np.where(same, np.where(x >= a, 1.0, 0.0), t * t * (3 - 2 * t))


def _mix(a, b, t):
    if a.__class__ is Vec or b.__class__ is Vec:
        return a * (1 - t) + b * t
    return a + (b - a) * t


def _rotx(x, y, ang):
    a = TAU * C(ang)
    return C(x) * np.cos(a) - C(y) * np.sin(a)


def _roty(x, y, ang):
    a = TAU * C(ang)
    return C(x) * np.sin(a) + C(y) * np.cos(a)


def _mirror(a, n):
    n = np.clip(C(n), 1.0, 64.0)
    return np.abs(_fract(C(a) * n) - 0.5) / n


def _wrap(x, p):
    p = C(p)
    z = np.asarray(p) == 0
    q = np.where(z, 1.0, p)
    return np.where(z, 0.0, C(x) - q * np.floor(C(x) / q))


VFUNCS = {
    "sin": lambda a: np.sin(C(a)), "cos": lambda a: np.cos(C(a)), "atan2": lambda a, b: np.arctan2(C(a), C(b)),
    "abs": lambda a: np.abs(_num(a)), "sqrt": lambda a: np.sqrt(np.maximum(0.0, _num(a))),
    "exp": lambda a: np.exp(np.clip(_num(a), -50.0, 50.0)), "floor": lambda a: np.floor(C(a)), "fract": _fract,
    "sign": lambda a: np.sign(_num(a)), "min": lambda a, b: np.minimum(_num(a), _num(b)), "max": lambda a, b: np.maximum(_num(a), _num(b)),
    "clamp": lambda x, a, b: np.maximum(a, np.minimum(b, _num(x))),
    "step": lambda a, x: np.where(_num(x) >= _num(a), 1.0, 0.0), "smoothstep": _smoothstep, "mix": _mix,
    "tri": lambda a: 1 - np.abs(2 * _fract(a) - 1), "dist": lambda a, b, c, d: np.hypot(_num(a) - _num(c), _num(b) - _num(d)),
    "noise": _noise2, "noise3": lambda a, b, c: _noise3(a, b, c), "tnoise": _tnoise, "rise": _rise, "hash": _hash,
    "palette": _palette, "cpalette": _cpalette, "hsv": _hsv,
    "rgb": lambda a, b, c: Vec(_cl01(a), _cl01(b), _cl01(c)), "gray": lambda a: Vec(_cl01(a), _cl01(a), _cl01(a)),
    "rotx": _rotx, "roty": _roty, "mirror": _mirror, "wrap": _wrap, "sat": _cl01,
}


# ---- the code -------------------------------------------------------------------------------------------

class _Vectorise(ast.NodeTransformer):
    """Conditions become _where, and/or become _and/_or, comparisons give numbers."""
    def _call(self, name, args, node):
        return ast.copy_location(ast.Call(func=ast.Name(id=name, ctx=ast.Load()), args=args, keywords=[]), node)

    def visit_IfExp(self, node):
        self.generic_visit(node)
        return self._call("_where", [node.test, node.body, node.orelse], node)

    def visit_BoolOp(self, node):
        self.generic_visit(node)
        name = "_and" if isinstance(node.op, ast.And) else "_or"
        out = node.values[0]
        for v in node.values[1:]:
            out = self._call(name, [out, v], node)
        return out

    def visit_Compare(self, node):
        self.generic_visit(node)
        parts, left = [], node.left
        for op, right in zip(node.ops, node.comparators):
            parts.append(self._call("_c", [ast.copy_location(ast.Compare(left=left, ops=[op], comparators=[right]), node)], node))
            left = right
        out = parts[0]
        for q in parts[1:]:
            out = self._call("_and", [out, q], node)
        return out


NS = {"__builtins__": {}, "tau": TAU, "pi": math.pi, "_div": _div, "_mod": _mod, "_pow": _pow, "_where": _where, "_and": _and,
      "_or": _or, "_c": _c}


def build(tree, args: list):
    """The array function for a checked and Ops-transformed tree (or None): same arguments as the scalar one."""
    if np is None:
        return None
    last = tree.body[-1].value
    if isinstance(last, (ast.Compare, ast.BoolOp)):
        return None  # the scalar path says that a yes/no is no colour
    t = _Vectorise().visit(copy.deepcopy(tree))
    lines = [f"def _v({', '.join(args)}):"]
    for st in t.body[:-1]:
        lines.append("    " + ast.unparse(st))
    lines.append("    return " + ast.unparse(t.body[-1].value))
    ns = dict(NS)
    ns.update(VFUNCS)
    exec(compile(chr(10).join(lines) + chr(10), "<vformula>", "exec"), ns)
    return ns["_v"]


# ---- the previous frame ---------------------------------------------------------------------------------

def make_prev_vec(prep, k, state):
    """prev(x, y) for arrays: the same four-nearest-LEDs blend as formula.make_prev."""
    G, K = prep.GRID, prep.KNN
    P = np.array(prep._pts, dtype=np.float64)
    gx = prep.x0 + (np.arange(G) + 0.5) / G * prep.w
    gy = prep.y0 + (np.arange(G) + 0.5) / G * prep.h
    cx, cy = np.meshgrid(gx, gy)  # row = gy, column = gx, like the scalar grid
    d2 = (P[None, :, 0] - cx.reshape(-1, 1)) ** 2 + (P[None, :, 1] - cy.reshape(-1, 1)) ** 2
    cand = np.argsort(d2, axis=1, kind="stable")[:, :K + 2]
    inv = 1.0 / (255.0 * max(k, 0.05))
    cache = {"id": None, "arr": None}

    def prev(x, y):
        fr = state["frame"]
        if fr is None:
            return Vec(0.0, 0.0, 0.0)
        if cache["id"] is not fr:
            cache["id"], cache["arr"] = fr, np.frombuffer(fr, dtype=np.uint8).reshape(-1, 3).astype(np.float64)
        arr = cache["arr"]
        x = np.broadcast_to(C(x), (prep.n,))
        y = np.broadcast_to(C(y), (prep.n,))
        ix = np.clip(((x - prep.x0) / prep.w * G).astype(np.int64), 0, G - 1)
        iy = np.clip(((y - prep.y0) / prep.h * G).astype(np.int64), 0, G - 1)
        c = cand[iy * G + ix]                                                    # (n, K + 2) candidate LEDs
        d = (P[c, 0] - x[:, None]) ** 2 + (P[c, 1] - y[:, None]) ** 2
        order = np.argsort(d, axis=1, kind="stable")[:, :K]
        sel, dd = np.take_along_axis(c, order, axis=1), np.take_along_axis(d, order, axis=1)
        w = 1.0 / (dd + 0.0006)
        w /= w.sum(axis=1, keepdims=True)
        col = (arr[sel] * w[:, :, None]).sum(axis=1) * inv
        col = np.minimum(1.0, col)
        return Vec(col[:, 0], col[:, 1], col[:, 2])

    return prev


def frame_bytes(res, n, k) -> bytes:
    """The result of the array function as the bytes of the frame (the same rounding as formula._rgb)."""
    if res.__class__ is Vec:
        chans = (res.r, res.g, res.b)
    else:
        if np.asarray(res).dtype == bool:
            raise TypeError("the last line must give a colour")
        chans = (res, res, res)
    out = np.empty((n, 3), dtype=np.uint8)
    for j, c in enumerate(chans):
        c = np.broadcast_to(np.nan_to_num(np.asarray(c, dtype=np.float64), nan=0.0, posinf=1e12, neginf=-1e12), (n,))
        out[:, j] = np.clip(c * 255 * k, 0, 255).astype(np.int64)
    return out.tobytes()
