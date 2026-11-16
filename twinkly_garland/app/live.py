"""Live scenes: a formula evaluated frame by frame with the current values of Home Assistant inputs."""
import math
import time

from . import formula, hadata

MAX_SLEW = 330.0  # max change of a colour channel per second (0..255): no strobing even if a formula asks for it
LOOP_S = 10.0     # `t` runs 0..1 over this many seconds in live mode


class LiveScene:
    def __init__(self, spec: dict, layout: list, params: dict | None = None, source=None):
        self.spec = formula.validate_item({"name": "live", **spec})
        self.params = dict(params or {})
        defs, self.inputs = self.spec["params"], self.spec["inputs"]
        self.fn = formula.compile_formula(self.spec["code"], formula.all_names(defs, self.inputs))
        self.prep = formula.Prepared(layout)
        self.pvals = [float(self.params.get(d["name"], d["default"])) for d in defs]
        self.k = float(self.params.get("intensity", 0.9))
        self.seed = float(self.params.get("seed", 1))
        self.prevfn, self.fb = formula.make_prev(self.prep, self.k)  # prev(x, y) reads the previous frame
        self.phase = {i["name"]: 0.0 for i in self.inputs}
        self.loop = float(self.params.get("loop", LOOP_S))
        self.source = source or hadata.read_input  # (input) -> (raw, normalized) | (None, None)
        self.smoothed = {i["name"]: float(i["default"]) for i in self.inputs}
        self.raw = {i["name"]: None for i in self.inputs}
        self.t0 = time.time()
        self.last = None
        self.prev = None

    def _update_inputs(self, dt: float):
        for inp in self.inputs:
            raw, norm = self.source(inp)
            self.raw[inp["name"]] = raw
            if norm is None:
                continue  # unavailable: keep the last value
            a = 1.0 if inp["smooth"] <= 0.01 else 1 - math.exp(-dt / inp["smooth"])
            self.smoothed[inp["name"]] += (norm - self.smoothed[inp["name"]]) * a
        for inp in self.inputs:  # running total of the value: a speed that follows data without jumps
            self.phase[inp["name"]] += self.smoothed[inp["name"]] * dt

    def values(self) -> dict:
        return {i["name"]: {"raw": self.raw[i["name"]], "value": round(self.smoothed[i["name"]], 3)} for i in self.inputs}

    def frame(self, now: float | None = None) -> bytes:
        now = time.time() if now is None else now
        dt = 0.1 if self.last is None else max(0.001, min(2.0, now - self.last))
        self.last = now
        self._update_inputs(dt)
        el = now - self.t0
        vals = self.pvals + [self.smoothed[i["name"]] for i in self.inputs] + [self.phase[i["name"]] for i in self.inputs]
        out = formula.eval_frame(self.fn, self.prep, (el / self.loop) % 1.0, el, self.seed, vals, self.k, self.prevfn)
        if self.prev is not None:
            lim = max(1, int(MAX_SLEW * dt))
            out = bytes(p + max(-lim, min(lim, c - p)) for p, c in zip(self.prev, out))
        self.prev = out
        self.fb["frame"] = out
        return out
