"""Channels: the Home Assistant signals that scenes read, kept in one place.

A channel is an entity (and optionally an attribute) with the range that becomes 0..1, the smoothing, the event
threshold, the auto range and a default value. A formula input is only an alias (the variable name used in the code) and a
reference `{"name": "house", "channel": "<id>"}`; the reference is expanded here (`expand`) before the engine sees it, so
the engine and the formula code do not know about channels.

Two system channels hold the theme of a live round: `pace` (the speed multiplier) and `theme` (the palette). Their source is
"random" (live:random picks it, as before), "fixed" or "ha" (an entity mapped onto the range of the pace / the list of the palettes).
They are not referenced by formulas (the code reads `pace` and palette("theme", v) as before).

Stored in DATA_DIR/channels.json (next to settings.json). `migrate_inputs` turns the inline inputs of the formulas of 0.21 and
earlier into channels once (see formula.load), after a backup of DATA_DIR.
"""
import hashlib
import json
import logging
import math
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path

from . import hadata, palettes

log = logging.getLogger("twinkly.channels")

DATA_DIR = Path(os.environ.get("DATA_DIR", "/data"))
SCHEMA = 1
VERSION = 0  # bumped whenever a channel changes (a stored effect uses the default value of its channels: part of the render cache key)

ENTITY_RE = re.compile(r"^[a-z0-9_]+\.[a-z0-9_]+$")
DEFAULT_ON_STATES = ["on", "home", "playing", "cleaning", "heat", "heating", "open", "detected"]
NAME_RE = re.compile(r"^[^\x00-\x1f]{1,48}$")
SYSTEM_IDS = ("pace", "theme")
EXAMPLE_PREFIX = "ex:"  # ids of the channels of the shipped examples: they are replaced by real channels when an example is taken (adopt)

_hooks: list = []  # called after every change (formula.py bumps its render cache version)


class ChannelError(ValueError):
    pass


def on_change(fn) -> None:
    _hooks.append(fn)


# ---- one channel --------------------------------------------------------------------------------------------

def _num(d: dict, key: str, default: float) -> float:
    v = d.get(key)
    try:
        return float(default if v is None or v == "" else v)
    except (TypeError, ValueError):
        raise ChannelError(f"{key} must be a number") from None


def _entity(d: dict) -> str:
    entity = str(d.get("entity") or "").strip()
    if entity and not ENTITY_RE.match(entity):
        raise ChannelError("entity must look like sensor.power_total (or empty: the channel is not bound, its default value is used)")
    return entity


def _on_states(d: dict) -> list:
    on = d.get("on_states") or DEFAULT_ON_STATES
    if isinstance(on, str):
        on = [x.strip().lower() for x in on.split(",") if x.strip()]
    return [str(x).lower() for x in on]


def clean(d: dict) -> dict:
    """The fields of a value channel, validated (no id / name)."""
    lo, hi = _num(d, "min", 0), _num(d, "max", 1)
    if lo == hi:
        raise ChannelError("min and max must differ")
    return {"entity": _entity(d), "attribute": str(d.get("attribute") or "").strip(), "min": lo, "max": hi,
            "smooth": min(120.0, max(0.0, _num(d, "smooth", 2))), "default": min(1.0, max(0.0, _num(d, "default", 0.5))),
            "auto": bool(d.get("auto", False)), "span": max(0.0, _num(d, "span", 0.0)),
            "kick": min(0.5, max(0.02, _num(d, "kick", 0.12))), "on_states": _on_states(d)}


def merge_key(c: dict) -> tuple:
    """Two channels with the same key behave identically in every frame, so they are one channel. Everything that changes
    a frame is in it: entity, attribute, min, max, smooth, kick, and also auto, span, on_states and the default value."""
    return (c["entity"], c["attribute"], float(c["min"]), float(c["max"]), float(c["smooth"]), float(c["kick"]),
            bool(c["auto"]), float(c["span"]), tuple(c["on_states"]), float(c["default"]))


def key_hash(c: dict) -> str:
    return hashlib.sha1(repr(merge_key(c)).encode()).hexdigest()[:8]


def auto_name(c: dict, taken: set) -> str:
    """A name made from the entity (and attribute); the user can rename it."""
    base = (c["entity"].split(".", 1)[-1] if c["entity"] else "unbound").replace("_", " ")
    if c["attribute"]:
        base += " " + c["attribute"].replace("_", " ")
    base, n, name = base[:40], 2, base[:40]
    low = {t.lower() for t in taken}
    while name.lower() in low:
        name = f"{base} {n}"
        n += 1
    return name


FIELDS = ("entity", "attribute", "min", "max", "smooth", "default", "auto", "span", "kick", "on_states")


# ---- the store ----------------------------------------------------------------------------------------------

_lock = threading.RLock()
_state: dict | None = None


def _path() -> Path:
    return DATA_DIR / "channels.json"


def exists_on_disk() -> bool:
    return _path().exists()


def _system_defaults() -> list:
    return [
        {"id": "pace", "name": "Pace", "kind": "pace", "source": "random", "fixed": 1.0, "entity": "", "attribute": "", "min": 0.0, "max": 1.0, "on_states": DEFAULT_ON_STATES},
        {"id": "theme", "name": "Theme palette", "kind": "palette", "source": "random", "fixed": palettes.DEFAULT_THEME["palette"], "entity": "", "attribute": "", "min": 0.0, "max": 1.0, "on_states": DEFAULT_ON_STATES},
    ]


def _write(state: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _path().with_name("channels.json.tmp")
    tmp.write_text(json.dumps(state, indent=1))
    os.replace(tmp, _path())


def _load() -> dict:
    global _state
    with _lock:
        if _state is None:
            try:
                raw = json.loads(_path().read_text())
                items = raw.get("channels", []) if isinstance(raw, dict) else []
            except (OSError, ValueError):
                items = []
            have = {c.get("id") for c in items}
            items = [c for c in _system_defaults() if c["id"] not in have] + items
            _state = {"schema": SCHEMA, "channels": items}
        return _state


def reset_cache() -> None:
    global _state
    with _lock:
        _state = None


def _changed() -> None:
    global VERSION
    VERSION += 1
    for fn in _hooks:
        fn()


def _save() -> None:
    _write(_load())
    _changed()


def all_channels() -> list:
    return list(_load()["channels"])


def get(cid: str) -> dict | None:
    return next((c for c in _load()["channels"] if c["id"] == cid), None)


def values() -> list:
    """The channels formulas can use as inputs (not the system ones)."""
    return [c for c in all_channels() if c.get("kind", "value") == "value"]


def _new_id(c: dict) -> str:
    cid = "c" + key_hash(c)
    while get(cid) is not None:
        cid = "c" + uuid.uuid4().hex[:8]
    return cid


def find_by_key(c: dict) -> dict | None:
    k = merge_key(c)
    return next((x for x in values() if merge_key(x) == k), None)


def _add(c: dict, name: str | None = None) -> dict:
    with _lock:
        st = _load()
        taken = {x["name"] for x in st["channels"]}
        name = (name or "").strip() or auto_name(c, taken)
        if name.lower() in {t.lower() for t in taken}:
            raise ChannelError(f"a channel named {name!r} already exists")
        item = {"id": _new_id(c), "name": name, "kind": "value", **c}
        st["channels"].append(item)
        return item


def import_input(d: dict) -> str:
    """The id of the channel that behaves exactly like this inline input: the same one if it exists, else a new one
    (migration of old formulas and the examples). Does not save."""
    c = clean(d)
    with _lock:
        found = find_by_key(c)
        return (found or _add(c))["id"]


# ---- editing (the API) --------------------------------------------------------------------------------------

def _check_name(name: str, cid: str | None) -> str:
    name = str(name or "").strip()
    if not NAME_RE.match(name):
        raise ChannelError("name: 1-48 characters")
    if any(c["name"].lower() == name.lower() and c["id"] != cid for c in all_channels()):
        raise ChannelError(f"a channel named {name!r} already exists")
    return name


def create(d: dict) -> dict:
    with _lock:
        c = clean(d)
        item = _add(c, _check_name(d["name"], None) if str(d.get("name") or "").strip() else None)
        _save()
        return item


def _clean_system(cur: dict, d: dict) -> dict:
    source = d.get("source", cur["source"])
    if source not in ("random", "fixed", "ha"):
        raise ChannelError("source: random, fixed or ha")
    out = {**cur, "source": source}
    if cur["kind"] == "pace":
        lo, hi = palettes.PACE_RANGE
        v = _num(d, "fixed", cur["fixed"])
        out["fixed"] = min(hi, max(lo, v))
    else:
        v = str(d.get("fixed", cur["fixed"]))
        if v not in palettes.theme_names():
            raise ChannelError(f"fixed: one of the palettes of the themes ({', '.join(palettes.theme_names())})")
        out["fixed"] = v
    if source == "ha" or "entity" in d:
        c = clean({"entity": d.get("entity", cur["entity"]), "attribute": d.get("attribute", cur["attribute"]),
                   "min": d.get("min", cur["min"]), "max": d.get("max", cur["max"]), "on_states": d.get("on_states", cur["on_states"])})
        out.update({k: c[k] for k in ("entity", "attribute", "min", "max", "on_states")})
        if source == "ha" and not out["entity"]:
            raise ChannelError("source ha needs an entity")
    return out


def update(cid: str, d: dict) -> dict:
    with _lock:
        st = _load()
        cur = get(cid)
        if cur is None:
            raise ChannelError(f"unknown channel {cid!r}")
        name = _check_name(d["name"], cid) if "name" in d else cur["name"]
        if cur.get("kind", "value") == "value":
            new = {"id": cid, "name": name, "kind": "value", **clean({**{k: cur[k] for k in FIELDS}, **{k: d[k] for k in FIELDS if k in d}})}
        else:
            new = {**_clean_system(cur, d), "name": cur["name"]}
        st["channels"][st["channels"].index(cur)] = new
        _save()
        return new


def delete(cid: str, users: dict) -> None:
    with _lock:
        cur = get(cid)
        if cur is None:
            raise ChannelError(f"unknown channel {cid!r}")
        if cur["id"] in SYSTEM_IDS:
            raise ChannelError("the system channels cannot be deleted")
        used = users.get(cid)
        if used and (used["scenes"] or used["effects"]):
            raise ChannelError(f"the channel is used by: {', '.join(used['scenes'] + used['effects'])}")
        _load()["channels"].remove(cur)
        _save()


def adopt(inputs: list) -> list:
    """Inputs of an example (channel ids `ex:...` and the definitions in `catalogue`) -> inputs with real channels: an existing
    channel that behaves exactly the same, or a new one. Inputs that already point at a real channel are kept."""
    from .examples_live import EXAMPLE_CHANNELS
    out = []
    with _lock:
        changed = False
        for i in inputs:
            cid = i.get("channel", "")
            if cid.startswith(EXAMPLE_PREFIX):
                d = EXAMPLE_CHANNELS.get(cid)
                if d is None:
                    raise ChannelError(f"unknown example channel {cid!r}")
                before = len(_load()["channels"])
                cid = import_input(d)
                changed = changed or len(_load()["channels"]) != before
            out.append({"name": i["name"], "channel": cid})
        if changed:
            _save()
    return out


# ---- expanding references (the shared layer in front of the engine) --------------------------------------------------

def expand(inputs: list) -> list:
    """Inputs `{name, channel}` -> the full input dicts the live scene and the renderer use (name = the alias)."""
    out = []
    for i in inputs:
        c = get(i["channel"])
        if c is None or c.get("kind", "value") != "value":
            raise ChannelError(f"input '{i['name']}': the channel {i['channel']!r} does not exist"
                               + (" (take the example again from the list)" if str(i["channel"]).startswith(EXAMPLE_PREFIX) else ""))
        out.append({"name": i["name"], "channel": c["id"], **{k: c[k] for k in FIELDS}})
    return out


# ---- usage, merging ---------------------------------------------------------------------------------------------

def usage(formulas: list, instances: list) -> dict:
    """{channel id: {"scenes": [formula names], "effects": [keys of the stored effects]}}. A stored effect uses the channels
    of the formulas of its layers."""
    out: dict = {}
    refs = {f["name"]: {i["channel"] for i in f.get("inputs", [])} for f in formulas}
    for f in formulas:
        for cid in refs[f["name"]]:
            out.setdefault(cid, {"scenes": [], "effects": []})["scenes"].append(f["name"])
    for inst in instances:
        names = {str(ly.get("effect", ""))[7:] for ly in inst.get("layers", []) if str(ly.get("effect", "")).startswith("custom:")}
        for cid in set().union(*(refs.get(n, set()) for n in names)) if names else ():
            out.setdefault(cid, {"scenes": [], "effects": []})["effects"].append(inst["key"])
    return out


def describe(users: dict) -> list:
    """The channels for the UI: with the list of who uses them, the count and the "personal" mark (needed by one scene only)."""
    out = []
    for c in all_channels():
        u = users.get(c["id"], {"scenes": [], "effects": []})
        used = [{"type": "scene", "name": n} for n in sorted(u["scenes"])] + [{"type": "effect", "name": n} for n in sorted(u["effects"])]
        out.append({**c, "used_by": used, "count": len(used), "personal": len(u["scenes"]) == 1})
    return out


def merge_preview(src: str, dst: str, users: dict) -> dict:
    a, b = get(src), get(dst)
    if a is None or b is None or src == dst:
        raise ChannelError("pick two different channels")
    if a.get("kind", "value") != "value" or b.get("kind", "value") != "value":
        raise ChannelError("the system channels cannot be merged")
    u = users.get(src, {"scenes": [], "effects": []})
    diff = [{"field": k, "from": a[k], "into": b[k]} for k in FIELDS if a[k] != b[k]]
    return {"from": {"id": src, "name": a["name"]}, "into": {"id": dst, "name": b["name"]}, "diff": diff,
            "scenes": sorted(u["scenes"]), "effects": sorted(u["effects"]), "identical": not diff}


def merge(src: str, dst: str, formulas: list) -> list:
    """The formulas with every reference to `src` pointed at `dst` (the caller saves them, then deletes `src`)."""
    return [{**f, "inputs": [{**i, "channel": dst if i["channel"] == src else i["channel"]} for i in f.get("inputs", [])]} for f in formulas]


# ---- the theme channels -----------------------------------------------------------------------------------------

def theme_override() -> dict:
    """The fields of the theme ({"palette": name, "pace": x}) that a system channel fixes: source "fixed", or "ha" (the entity mapped
    onto the range of the pace / the list of the palettes; when the entity is not available the channel's own value). "random"
    fixes nothing (live:random picks it; a scene started by hand keeps the default theme)."""
    out = {}
    for cid, key in (("pace", "pace"), ("theme", "palette")):
        c = get(cid)
        if c is None or c["source"] == "random":
            continue
        val = c["fixed"]
        if c["source"] == "ha" and c["entity"]:
            try:
                _raw, norm = hadata.read_input(c)
            except hadata.HAError:
                norm = None
            if norm is not None:
                if key == "pace":
                    lo, hi = palettes.PACE_RANGE
                    val = round(math.exp(math.log(lo) + norm * (math.log(hi) - math.log(lo))), 2)
                else:
                    names = palettes.theme_names()
                    val = names[min(len(names) - 1, int(norm * len(names)))]
        out[key] = val
    return out


# ---- migration of the formulas of 0.21 and earlier --------------------------------------------------------------------

def needs_backup(formulas_exist: bool) -> bool:
    return formulas_exist and not exists_on_disk()


def backup(tag: str) -> Path:
    """A copy of DATA_DIR (without the scan dumps and without older backups) before the first start of a new data format."""
    dst = DATA_DIR / f"backup-{tag}-{time.strftime('%Y%m%d-%H%M%S')}"

    def skip(folder, names):
        return [n for n in names if Path(folder) == DATA_DIR and (n == "scans" or n.startswith("backup-"))]
    shutil.copytree(DATA_DIR, dst, ignore=skip)
    log.info("backup of %s made in %s", DATA_DIR, dst)
    return dst


def migrate_inputs(items: list) -> int:
    """Every inline input of the formulas becomes a reference to a channel (equal inputs share one channel). Changes `items` in
    place, writes channels.json (and returns the number of converted inputs); the caller saves the formulas afterwards."""
    n = 0
    with _lock:
        for it in items:
            if any("channel" not in i for i in it.get("inputs", [])):
                it["inputs"] = [i if "channel" in i else {"name": i["name"], "channel": import_input(i)} for i in it["inputs"]]
                n += 1
        if n or not exists_on_disk():
            _save()
    return n
