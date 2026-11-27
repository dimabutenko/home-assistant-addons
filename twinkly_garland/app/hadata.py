"""Reading Home Assistant entities (for live scenes).

In the add-on the Supervisor proxy is used (`homeassistant_api: true`, token from SUPERVISOR_TOKEN, base
http://supervisor/core). For development TWINKLY_HA_BASE / TWINKLY_HA_TOKEN can point at a Home Assistant directly.
A small background thread polls the entities that live scenes use, so reading a value never blocks a frame.
"""
import logging
import os
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import requests

log = logging.getLogger("twinkly.ha")
POLL_S = 1.0  # fast signals (CPU load, power) change every few seconds
KEEP_S = 120.0  # stop polling an entity nobody asked for during this long


class HAError(RuntimeError):
    pass


def base_url() -> str:
    return (os.environ.get("TWINKLY_HA_BASE") or "http://supervisor/core").rstrip("/")


def token() -> str:
    return os.environ.get("TWINKLY_HA_TOKEN") or os.environ.get("SUPERVISOR_TOKEN") or ""


def available() -> bool:
    return bool(token())


def _get(path: str):
    if not available():
        raise HAError("Home Assistant access is not available (needs the add-on permission homeassistant_api)")
    try:
        r = requests.get(base_url() + "/api" + path, headers={"Authorization": f"Bearer {token()}"}, timeout=6)
    except requests.RequestException as exc:
        raise HAError(f"cannot reach Home Assistant: {type(exc).__name__}") from None
    if r.status_code == 404:
        raise HAError("entity not found")
    if r.status_code != 200:
        raise HAError(f"Home Assistant answered HTTP {r.status_code}")
    return r.json()


# ---- value of a binding -------------------------------------------------------------------------------

def raw_value(state: dict, attribute: str, on_states: list):
    """Number from a state object, or None when unavailable. Numbers are read as they are; other states
    count as 1 when listed in on_states and 0 otherwise."""
    if state is None:
        return None
    val = state.get("attributes", {}).get(attribute) if attribute else state.get("state")
    if val is None or str(val).lower() in ("unavailable", "unknown", "none", ""):
        return None
    try:
        return float(val)
    except (TypeError, ValueError):
        return 1.0 if str(val).lower() in on_states else 0.0


def normalize(raw: float, lo: float, hi: float) -> float:
    return min(1.0, max(0.0, (raw - lo) / (hi - lo)))


# ---- background poller ----------------------------------------------------------------------------------

class Watcher:
    def __init__(self):
        self.lock = threading.Lock()
        self.wanted: dict = {}   # entity -> last time somebody asked
        self.states: dict = {}   # entity -> {"state":..., "attributes":..., "at": time}
        self.errors: dict = {}
        self.thread = None

    def _ensure_thread(self):
        if self.thread is None or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run, daemon=True)
            self.thread.start()

    def get(self, entity: str):
        """Latest known state object (starts polling the entity if needed)."""
        with self.lock:
            self.wanted[entity] = time.time()
            known = entity in self.states
        self._ensure_thread()
        if not known:
            self._fetch(entity)
        return self.states.get(entity)

    def error(self, entity: str):
        return self.errors.get(entity)

    def _fetch(self, entity: str):
        try:
            st = _get(f"/states/{entity}")
            with self.lock:
                self.states[entity] = {"state": st.get("state"), "attributes": st.get("attributes", {}), "at": time.time()}
                self.errors.pop(entity, None)
        except HAError as exc:
            with self.lock:
                self.errors[entity] = str(exc)

    def _run(self):
        while True:
            time.sleep(POLL_S)
            now = time.time()
            with self.lock:
                for e in [e for e, t in self.wanted.items() if now - t > KEEP_S]:
                    self.wanted.pop(e, None)
                    self.states.pop(e, None)
                todo = list(self.wanted)
            if not todo:
                return
            for e in todo:
                self._fetch(e)


WATCHER = Watcher()


def read_input(inp: dict):
    """(raw, normalized) for an input binding; (None, None) when the value is not available."""
    if not inp.get("entity"):  # a channel that is not bound to an entity
        return None, None
    st = WATCHER.get(inp["entity"])
    raw = raw_value(st, inp.get("attribute", ""), inp.get("on_states", []))
    if raw is None:
        return None, None
    return raw, normalize(raw, inp["min"], inp["max"])


def history(entity: str, minutes: float = 30.0) -> list:
    """Numeric states of the entity over the last minutes (oldest first), for seeding an auto range."""
    start = (datetime.now(timezone.utc) - timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S+00:00")
    data = _get(f"/history/period/{urllib.parse.quote(start)}?filter_entity_id={entity}&minimal_response&no_attributes")
    out = []
    for st in (data[0] if data else []):
        try:
            out.append(float(st["state"]))
        except (KeyError, TypeError, ValueError):
            pass
    return out


def history_points(entity: str, minutes: float = 30.0, on_states=()) -> list:
    """(epoch seconds, number) of the entity over the last minutes (oldest first). Non-numeric states count as 1 when
    listed in on_states and as 0 otherwise; unavailable / unknown are skipped."""
    start = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    q = urllib.parse.quote(start.strftime("%Y-%m-%dT%H:%M:%S+00:00"))
    data = _get(f"/history/period/{q}?filter_entity_id={entity}&minimal_response&no_attributes")
    out = []
    for st in (data[0] if data else []):
        text = str(st.get("state", "")).lower()
        if text in ("unavailable", "unknown", "none", ""):
            continue
        try:
            val = float(text)
        except ValueError:
            val = 1.0 if text in on_states else 0.0
        try:
            t = datetime.fromisoformat(st.get("last_changed") or st.get("last_updated")).timestamp()
        except (TypeError, ValueError):
            t = start.timestamp()
        out.append((max(t, start.timestamp()), val))
    return out


def resample(points: list, t0: float, t1: float, n: int) -> list:
    """Values at n evenly spaced moments between t0 and t1: a state holds until the next change (before the first
    known state the first value is used)."""
    if not points or n < 1:
        return []
    out, k, cur = [], 0, points[0][1]
    for i in range(n):
        t = t0 + (t1 - t0) * (i + 1) / n
        while k < len(points) and points[k][0] <= t:
            cur = points[k][1]
            k += 1
        out.append(cur)
    return out


class ReplaySource:
    """Plays the history of the inputs back as if it was live: `hours` of data in `seconds` of real time, looping.
    Works as the `source` of a LiveScene (and its `history` seeds the auto range with the whole replayed period)."""

    def __init__(self, inputs: list, hours: float = 24.0, seconds: float = 90.0, points=None):
        points = points or history_points
        self.t1 = time.time()
        self.t0 = self.t1 - hours * 3600
        self.n = int(max(60, min(8640, hours * 360)))
        self.seconds = max(5.0, float(seconds))
        self.series, self.missing = {}, []
        for inp in inputs:
            if inp.get("attribute") or not inp.get("entity"):
                self.missing.append(inp["name"])
                continue
            try:
                self.series[inp["name"]] = resample(points(inp["entity"], hours * 60, inp.get("on_states", ())), self.t0, self.t1, self.n)
            except HAError as exc:
                log.info("no history of %s for the replay: %s", inp["entity"], exc)
            if not self.series.get(inp["name"]):
                self.series.pop(inp["name"], None)
                self.missing.append(inp["name"])
        self.start = time.time()

    def pos(self) -> float:
        return ((time.time() - self.start) / self.seconds) % 1.0

    def at(self) -> float:
        """The moment of the replayed period that is on now (epoch seconds)."""
        return self.t0 + self.pos() * (self.t1 - self.t0)

    def __call__(self, inp: dict):
        arr = self.series.get(inp["name"])
        if not arr:
            return None, None
        return arr[min(self.n - 1, int(self.pos() * self.n))], None

    def history(self, inp: dict) -> list:
        return self.series.get(inp["name"]) or []


# ---- entity search for the editor -------------------------------------------------------------------------

_all: dict = {"t": 0.0, "items": []}


def search(q: str, limit: int = 30) -> list:
    if time.time() - _all["t"] > 30:
        _all["items"] = _get("/states")
        _all["t"] = time.time()
    q = q.strip().lower()
    out = []
    for s in _all["items"]:
        eid = s["entity_id"]
        name = str(s.get("attributes", {}).get("friendly_name", ""))
        if not q or q in eid.lower() or q in name.lower():
            out.append((0 if eid.lower().startswith(q) else 1, eid, name, s))
    out.sort(key=lambda r: (r[0], r[1]))
    return [{"entity_id": e, "name": n, "state": str(s.get("state"))[:24],
             "unit": s.get("attributes", {}).get("unit_of_measurement", ""),
             "attributes": [a for a, v in s.get("attributes", {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)][:10]}
            for _, e, n, s in out[:limit]]
