"""Twinkly Garland add-on: API + web UI."""
import asyncio
import base64
import json
import logging
import os
import random
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import compose, device, effects, formula, palettes, scan

OPTIONS_PATH = Path(os.environ.get("OPTIONS_PATH", "/data/options.json"))
STATIC = Path(__file__).parent / "static"
KEY_RE = re.compile(r"^[A-Za-z0-9 _-]{1,32}$")
GALLERY_STEP = 3  # thumbnails use every 3rd frame

log = logging.getLogger("twinkly")
logging.basicConfig(level=logging.INFO)


def options() -> dict:
    try:
        return json.loads(OPTIONS_PATH.read_text())
    except (OSError, ValueError):
        return {}


def devices() -> list:
    return options().get("devices", [])


def find_device(name: str) -> dict:
    for d in devices():
        if d["name"] == name:
            return d
    raise HTTPException(404, f"unknown device {name!r}")


# ---- saved effect instances --------------------------------------------

def _instances_path() -> Path:
    return device.DATA_DIR / "instances.json"


def _seeded_path() -> Path:
    return device.DATA_DIR / "seeded.json"


def save_instances(items: list) -> None:
    p = _instances_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, indent=1))


def load_instances() -> list:
    """Saved instances (old single-effect ones converted to layers) plus one default
    instance per generator that was never seeded before, so new generators appear
    after an add-on update; a deleted instance is not brought back."""
    try:
        items = [compose.normalize(i) for i in json.loads(_instances_path().read_text())]
    except (OSError, ValueError):
        items = []
    try:
        seeded = set(json.loads(_seeded_path().read_text()))
    except (OSError, ValueError):
        seeded = set()
    new = [g for g in effects.GENERATORS if g not in seeded]
    if new:
        have = {i["key"] for i in items}
        for g in new:
            if g not in have:
                items.append(compose.default_instance(g))
        save_instances(items)
        _seeded_path().write_text(json.dumps(sorted(seeded | set(new))))
    return items


def desired_for(dev: dict) -> list:
    return device.build_desired(dev, load_instances(), compose.render_instance)


# ---- background reconcile ----------------------------------------------

def ensure_all() -> list:
    res = []
    for dev in devices():
        try:
            res.append(device.ensure(dev, desired_for(dev)))
        except Exception as exc:
            log.warning("ensure %s failed: %s", dev["name"], exc)
            res.append({"device": dev["name"], "action": "error", "error": str(exc)})
    return res


async def _auto_loop():
    while True:
        await asyncio.sleep(int(options().get("ensure_interval_min", 60)) * 60)
        if options().get("auto_ensure"):
            await asyncio.get_running_loop().run_in_executor(None, ensure_all)


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_auto_loop())
    yield
    task.cancel()


app = FastAPI(title="Twinkly Garland", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ---- models -----------------------------------------------------------------

class Mask(BaseModel):
    type: str = "none"
    from_: float = Field(0.0, alias="from")
    to: float = 1.0
    invert: bool = False

    model_config = {"populate_by_name": True}


class Layer(BaseModel):
    effect: str
    params: dict = {}
    blend: str = "normal"
    opacity: float = 1.0
    mask: Mask = Mask()


class Instance(BaseModel):
    key: str
    layers: list[Layer]
    duration: int = 10
    fps: int = 10
    on_device: bool = True
    rotation: bool = True
    weight: int = 1
    devices: list[str] = []


def _check_instance(i: Instance, allow_inline: bool = False) -> None:
    if not KEY_RE.match(i.key):
        raise HTTPException(400, f"bad name {i.key!r}: 1-32 letters, digits, space, _ or -")
    if not 1 <= len(i.layers) <= 4:
        raise HTTPException(400, "an effect needs 1-4 layers")
    if not 4 <= i.duration <= 30 or not 5 <= i.fps <= 15:
        raise HTTPException(400, "duration must be 4-30 s and fps 5-15")
    if not 1 <= i.weight <= 5:
        raise HTTPException(400, "weight must be 1-5")
    for ly in i.layers:
        if ly.effect == "formula" and not allow_inline:
            raise HTTPException(400, "save the formula first, then use it as an effect layer")
        if not effects.known(ly.effect):
            raise HTTPException(400, f"unknown generator {ly.effect!r}")
        if ly.blend not in compose.BLENDS or ly.mask.type not in compose.MASKS:
            raise HTTPException(400, "bad blend or mask type")


def _dump(i: Instance) -> dict:
    return compose.normalize(i.model_dump(by_alias=True))


# ---- API: static data ---------------------------------------------------------

@app.get("/api/effects")
def api_effects():
    return effects.catalog()


# ---- API: formula effects ---------------------------------------------------------------------

@app.get("/api/formulas")
def api_formulas():
    return {"items": formula.load(), "examples": formula.EXAMPLES, "reference": formula.REFERENCE}


class FormulaIn(BaseModel):
    name: str
    code: str
    params: list[dict] = []


class FormulaCheck(BaseModel):
    code: str
    params: list[dict] = []


@app.post("/api/formulas/check")
def api_formula_check(req: FormulaCheck):
    """Compile only (no render): quick feedback while typing."""
    try:
        defs = formula.clean_params(req.params)
        formula.compile_formula(req.code, tuple(d["name"] for d in defs))
        return {"ok": True}
    except formula.FormulaError as exc:
        return {"ok": False, "error": exc.msg, "line": exc.line}


@app.put("/api/formulas")
def api_save_formulas(items: list[FormulaIn]):
    try:
        clean = [formula.validate_item(i.model_dump()) for i in items]
    except formula.FormulaError as exc:
        raise HTTPException(400, str(exc))
    names = {c["name"] for c in clean}
    used = sorted({f"{i['key']}" for i in load_instances() for ly in i["layers"]
                   if ly["effect"].startswith("custom:") and ly["effect"][7:] not in names})
    if used:
        raise HTTPException(400, f"a formula that is still used by effects cannot be removed or renamed: {', '.join(used)}")
    try:
        formula.save(clean)
    except formula.FormulaError as exc:
        raise HTTPException(400, str(exc))
    return {"saved": len(clean)}


@app.get("/api/palettes")
def api_palettes():
    return palettes.listing()


class PaletteIn(BaseModel):
    name: str
    stops: list[list]


@app.put("/api/palettes")
def api_save_palettes(items: list[PaletteIn]):
    try:
        palettes.save([i.model_dump() for i in items])
    except (ValueError, TypeError) as exc:
        raise HTTPException(400, str(exc))
    return {"saved": len(items)}


@app.get("/api/instances")
def api_instances():
    return load_instances()


@app.put("/api/instances")
def api_save_instances(items: list[Instance]):
    keys = [i.key for i in items]
    if len(set(keys)) != len(keys):
        raise HTTPException(400, "duplicate names")
    for i in items:
        _check_instance(i)
    save_instances([_dump(i) for i in items])
    return {"saved": len(items)}


# ---- API: preview / gallery ----------------------------------------------------

def _seam(frames: list) -> float:
    """Jump from the last frame to the first, relative to the usual change between frames (about 1 = seamless)."""
    def d(a, b):
        return sum(abs(x - y) for x, y in zip(a, b)) / len(a)
    if len(frames) < 3:
        return 0.0
    steps = [d(frames[i], frames[i + 1]) for i in range(len(frames) - 1)]
    avg = sum(steps) / len(steps)
    return round(d(frames[-1], frames[0]) / max(avg, 0.5), 2)


def _b64(frames: list, step: int = 1) -> list:
    return [base64.b64encode(f).decode() for f in frames[::step]]


class PreviewReq(BaseModel):
    instance: Instance
    device: str


@app.post("/api/preview")
def api_preview(req: PreviewReq):
    """Render on the server, play in the browser against the real layout."""
    _check_instance(req.instance, allow_inline=True)
    layout = device.render_layout(find_device(req.device))
    t0 = time.time()
    try:
        r = compose.render_instance(_dump(req.instance), layout)
    except (formula.FormulaError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return {"fps": r.fps, "layout": [[p["x"], p["y"]] for p in layout], "frames": _b64(r.frames),
            "render_ms": int((time.time() - t0) * 1000), "seam": _seam(r.frames)}


@app.get("/api/gallery")
def api_gallery(device_name: str = ""):
    """Small animated thumbnails of every saved effect on a device's layout."""
    dev = find_device(device_name) if device_name else (devices() or [None])[0]
    if dev is None:
        return {"layout": [], "items": []}
    layout = device.render_layout(dev)
    items = []
    for inst in load_instances():
        try:
            r = compose.render_instance(inst, layout)
        except Exception as exc:
            log.warning("gallery render %s failed: %s", inst["key"], exc)
            continue
        items.append({"key": inst["key"], "fps": r.fps / GALLERY_STEP, "frames": _b64(r.frames, GALLERY_STEP),
                      "frames_total": len(r.frames)})
    return {"layout": [[p["x"], p["y"]] for p in layout], "items": items}


# ---- API: devices ---------------------------------------------------------------

def probe(dev: dict) -> dict:
    info = {"name": dev["name"], "host": dev["host"], "online": False}
    if dev["host"] in device.scanning_hosts:
        return {**info, "online": True, "scanning": True, "aspect": device.device_aspect(dev["name"])}
    try:
        with device.lock_for(dev["host"]):
            return _probe_locked(dev, info)
    except Exception as exc:
        info["error"] = type(exc).__name__
    info["aspect"] = device.device_aspect(dev["name"])
    return info


def _probe_locked(dev: dict, info: dict) -> dict:
    try:
        ci = device.connect(dev["host"])
        info["firmware"] = device.retry(ci.firmware_version)["version"]
        movies = device.retry(ci.get_movies)
        info["_listing"] = movies
        info["movies"] = [
            {"id": m["id"], "name": m["name"], "unique_id": m["unique_id"], "frames": m["frames_number"]}
            for m in movies["movies"]
        ]
        info["available_frames"] = movies["available_frames"]
        info["capacity"] = movies["max_capacity"]
        info["mode"] = device.retry(ci.get_mode).get("mode")
        try:
            info["current_uid"] = (device.retry(ci.get_movies_current).get("unique_id") or "").upper()
        except Exception:
            info["current_uid"] = ""
        info["online"] = True
    except Exception as exc:
        info["error"] = type(exc).__name__
    info["aspect"] = device.device_aspect(dev["name"])
    return info


@app.get("/api/devices")
def api_devices():
    return [probe(d) for d in devices()]


_status_cache = {"t": 0.0, "data": None}
STATUS_TTL = 10  # s: the device is slow and polling it too often makes its logins collide


def _drop_status_cache():
    _status_cache["t"] = 0.0


@app.get("/api/status")
def api_status(fresh: bool = False):
    """Per device: what is stored, what is playing, what is wanted and whether they match."""
    if not fresh and _status_cache["data"] is not None and time.time() - _status_cache["t"] < STATUS_TTL:
        return _status_cache["data"]
    out = []
    for dev in devices():
        info = probe(dev)
        listing = info.pop("_listing", None)
        if info["online"] and listing is not None:
            try:
                desired = desired_for(dev)
                pl = device.plan(dev, desired, listing)
                by_uid = {m["uid"]: m["key"] for m in desired}
                info["stored"] = [{"key": by_uid.get(m["unique_id"].upper()), "name": m["name"], "frames": m["frames"]}
                                  for m in info["movies"]]
                info["playing_key"] = by_uid.get(info["current_uid"]) if info["mode"] == "movie" else None
                info["desired_frames"] = pl["frames_needed"]
                info["plan"] = {"action": pl["action"], "missing": pl["missing"], "extra": pl["extra"]}
                info["fits"] = pl["fits"]
            except Exception as exc:
                info["status_error"] = str(exc)
        out.append(info)
    _status_cache.update(t=time.time(), data=out)
    return out


class DevSettings(BaseModel):
    aspect: float | None = None  # real width / height of the area the garland covers


@app.put("/api/devices/{name}/settings")
def api_device_settings(name: str, req: DevSettings):
    find_device(name)
    if req.aspect is not None and not 0.2 <= req.aspect <= 6:
        raise HTTPException(400, "width / height must be between 0.2 and 6")
    device.save_device_aspect(name, req.aspect)
    _drop_status_cache()
    return {"aspect": req.aspect}


@app.post("/api/devices/{name}/layout/refresh")
def api_layout_refresh(name: str):
    return {"leds": len(device.get_layout(find_device(name), refresh=True))}


@app.get("/api/devices/{name}/plan")
def api_plan(name: str):
    dev = find_device(name)
    return device.plan(dev, desired_for(dev))


@app.post("/api/devices/{name}/ensure")
def api_ensure(name: str):
    dev = find_device(name)
    _drop_status_cache()
    try:
        return device.ensure(dev, desired_for(dev))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/ensure")
def api_ensure_all():
    return ensure_all()


class PlayReq(BaseModel):
    effect: str  # instance name, or "random"
    devices: list[str] = []  # empty = every configured device


@app.post("/api/play")
def api_play(req: PlayReq):
    """Play an effect on the given devices. Reconciles first when a device drifted
    (e.g. a firmware update wiped the movies), so playback never breaks.
    `random` picks one effect, common to all target devices, among those marked for rotation (weighted)."""
    _drop_status_cache()
    names = req.devices or [d["name"] for d in devices()]
    desired_by_dev = {}
    errors = {}
    for n in names:
        dev = find_device(n)
        try:
            desired_by_dev[n] = desired_for(dev)
        except Exception as exc:  # e.g. device offline and no cached layout
            errors[n] = str(exc)

    key = req.effect
    if key == "random":
        common = None
        weights = {}
        for desired in desired_by_dev.values():
            keys = set()
            for m in desired:
                if m["rotation"]:
                    keys.add(m["key"])
                    weights[m["key"]] = m["weight"]
            common = keys if common is None else common & keys
        if not common:
            raise HTTPException(404, "no effect is both on the garland and in the rotation for all target devices")
        pool = sorted(common)
        key = random.choices(pool, weights=[weights[k] for k in pool])[0]

    out = [{"device": n, "error": e} for n, e in errors.items()]
    for n, desired in desired_by_dev.items():
        dev = find_device(n)
        try:
            if not any(m["key"] == key for m in desired):
                raise KeyError(f"effect {key!r} is not enabled on {n}")
            res = device.ensure(dev, desired, play_key=key)
            if res["action"] == "ok":
                device.play(dev, desired, key)
            out.append({"device": n, "playing": key, "reconcile": res["action"]})
        except Exception as exc:
            out.append({"device": n, "error": str(exc)})
    if not any("playing" in o for o in out):
        # Lets callers (HA rest_command) detect failure and fall back.
        raise HTTPException(502, out)
    return out


# ---- API: position scan -----------------------------------------------------------------

@app.get("/api/devices/{name}/layout")
def api_layout(name: str):
    return [[p["x"], p["y"]] for p in device.get_layout(find_device(name))]


class ScanStart(BaseModel):
    device: str


@app.post("/api/scan/start")
def api_scan_start(req: ScanStart):
    try:
        return scan.start(find_device(req.device))
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"cannot start the scan: {exc}")


class ScanPattern(BaseModel):
    kind: str
    bit: int = 0
    leds: list[int] = []
    level: int = 200


@app.post("/api/scan/pattern")
def api_scan_pattern(req: ScanPattern):
    try:
        return scan.pattern(req.kind, req.bit, req.leds, req.level)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/scan/stop")
def api_scan_stop():
    return scan.stop()


@app.get("/api/scan/state")
def api_scan_state():
    return scan.state()


class ScanApply(BaseModel):
    device: str
    coordinates: list[dict]


@app.post("/api/scan/apply")
def api_scan_apply(req: ScanApply):
    try:
        return scan.apply_layout(find_device(req.device), req.coordinates)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"cannot write the layout: {exc}")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
