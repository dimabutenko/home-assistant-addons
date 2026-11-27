"""Frames of every example and edge construct against the golden frames made by the scalar engine before it was removed.
A rounding step of a colour channel (or two for prev() with fixed coordinates) is allowed, nothing more. Run: python tests/test_golden.py"""
import json
import sys

import numpy as np
from harness import *  # noqa
from edge_cases import EDGE, ERRORS
from app import formula, vformula

TOL = 2
gold = np.load(Path(__file__).parent / "golden" / "frames.npz")
lays = layouts()
specs = [(e["name"], e) for e in formula.EXAMPLES] + [("edge: " + k, {"code": v, "params": [], "inputs": []}) for k, v in EDGE.items()]
bad, worst, exact, total = [], 0, 0, 0
for name, ex in specs:
    for kind, lay in lays.items():
        for sc in range(3):
            g = gold[f"{name}|{kind}|{sc}"]
            sp = formula.validate_item({"name": "t", **ex})
            try:
                got = run(ex, kind, lay, sc, prev_frames=[g[f].tobytes() for f in range(N_FRAMES)])
            except Exception as e:
                bad.append(f"{name} {kind}/{sc}: raised {e}"); continue
            a = np.frombuffer(b"".join(got), np.uint8).reshape(N_FRAMES, -1).astype(int)
            d = int(np.abs(a - g.astype(int)).max())
            worst, total, exact = max(worst, d), total + 1, exact + (d == 0)
            if d > TOL:
                bad.append(f"{name} {kind}/{sc}: max diff {d}")
print(f"{total} sequences, {exact} identical to the byte, worst difference {worst} step(s)")

# error messages and lines: those of the scalar engine, except two deliberate changes (a colour as a condition or in a comparison is an error now)
want = json.loads((Path(__file__).parent / "golden" / "errors.json").read_text())
lay = lays["wall"]
for name, code in ERRORS.items():
    try:
        run({"code": code, "params": [], "inputs": []}, "wall", lay, 0)
        got = "OK"
    except formula.FormulaError as e:
        got = [e.msg, e.line]
    if got != want[name]:
        bad.append(f"error {name}: want {want[name]} got {got}")
# every function of the language has an implementation and the other way round
impl = set(vformula.IMPL) | {"prev"}
if impl != set(formula.FUNCS):
    bad.append(f"FUNCS and IMPL differ: {sorted(impl ^ set(formula.FUNCS))}")
print("\n".join(bad) or "ALL OK")
sys.exit(1 if bad else 0)
