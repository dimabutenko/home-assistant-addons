"""Every live example through LiveScene with stub inputs: frames, error line numbers in the live path, no HA needed."""
import sys
from harness import *  # noqa
from app import formula, live

lay = layouts()["tree"]
bad = []
for ex in formula.EXAMPLES:
    if not ex.get("inputs"):
        continue
    vals = {}
    def source(inp, vals=vals):
        v = vals.setdefault(inp["name"], 0.2)
        vals[inp["name"]] = (v + 0.173) % 1.0
        return inp["min"] + v * (inp["max"] - inp["min"]), v
    sc = live.LiveScene(to_refs(ex), lay, source=source, history=lambda inp: [0.3 + 0.2 * ((j * 7) % 5) / 5 for j in range(60)])
    frames = [sc.frame(now=sc.t0 + 0.1 * (f + 1)) for f in range(12)]
    if any(len(f) != 3 * len(lay) for f in frames) or len({f for f in frames}) < 2:
        bad.append(f"{ex['name']}: frames wrong or static")
# a mistake on line 3 of a live formula is reported with the line
sc = live.LiveScene({"code": "a1 = 1\nb1 = 2\nc1 = sin(palette(\"fire\", u))\ngray(c1)", "params": [], "inputs": []}, lay)
try:
    sc.frame(); bad.append("no error raised")
except formula.FormulaError as e:
    if e.line != 3:
        bad.append(f"line {e.line} != 3")
print("\n".join(bad) or "ALL OK")
sys.exit(1 if bad else 0)
