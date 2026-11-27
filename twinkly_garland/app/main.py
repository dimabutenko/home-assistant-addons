"""Twinkly Garland add-on: API + web UI."""
import asyncio
import base64
import io
import json
import logging
import os
import random
import re
import threading
import time
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import compose, device, effects, formula, hadata, live, mqtt_bridge, palettes, rounds, scan

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
        if dev["host"] in device.scanning_hosts:
            res.append({"device": dev["name"], "action": "skipped", "error": "a position scan is running"})
            continue
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


def _recover_rt():
    """If the add-on died while streaming, the device may be stuck in real-time mode: put it back to movies."""
    for dev in devices():
        try:
            with device.lock_for(dev["host"]):
                ci = device.connect(dev["host"])
                if device.retry(ci.get_mode).get("mode") == "rt" and dev["host"] not in device.live_hosts \
                        and dev["host"] not in device.scanning_hosts:
                    log.warning("%s was left in real-time mode: switching back to movie mode", dev["name"])
                    device.retry(ci.set_mode, "movie")
        except Exception as exc:
            log.info("startup check of %s skipped: %s", dev["name"], exc)


class _BridgeGlue:
    """What the MQTT bridge needs from this module."""

    def devices(self):
        return devices()

    def effect_names(self, dev: dict) -> list:
        keys = [i["key"] for i in load_instances()
                if i.get("on_device", True) and (not i.get("devices") or dev["name"] in i["devices"])]
        scenes = [f["name"] for f in formula.load() if f.get("inputs")]
        return ["random", "live:random"] + [f"live:{n}" for n in scenes] + keys

    def play(self, effect: str, names: list):
        return api_play(PlayReq(effect=effect, devices=names))

    def changed(self):
        _drop_status_cache()


bridge = None


def _changed():
    """Effects, formulas or devices changed: the MQTT discovery (effect list) is republished."""
    if bridge is not None:
        bridge.changed()


@asynccontextmanager
async def lifespan(_app):
    global bridge
    task = asyncio.create_task(_auto_loop())
    asyncio.get_running_loop().run_in_executor(None, _recover_rt)
    opts = options()
    if opts.get("mqtt_host"):
        try:
            bridge = mqtt_bridge.Bridge(_BridgeGlue(), opts)
            bridge.start()
        except Exception:
            log.exception("the MQTT bridge could not start")
            bridge = None
    else:
        log.info("MQTT is off (no mqtt_host in the options): the garlands are not shown in Home Assistant")
    yield
    task.cancel()
    if bridge is not None:
        bridge.stop()


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
    mapping: str = "plane"  # plane: as on a wall; apex: the centre of the effect on the tip of a tree


def _check_instance(i: Instance, allow_inline: bool = False) -> None:
    if not KEY_RE.match(i.key):
        raise HTTPException(400, f"bad name {i.key!r}: 1-32 letters, digits, space, _ or -")
    if not 1 <= len(i.layers) <= 4:
        raise HTTPException(400, "an effect needs 1-4 layers")
    if not 4 <= i.duration <= 30 or not 5 <= i.fps <= 15:
        raise HTTPException(400, "duration must be 4-30 s and fps 5-15")
    if not 1 <= i.weight <= 5:
        raise HTTPException(400, "weight must be 1-5")
    if i.mapping not in device.MAPPINGS:
        raise HTTPException(400, f"mapping must be one of {device.MAPPINGS}")
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
    inputs: list[dict] = []
    mapping: str = "plane"
    shape: str = "any"  # any / wall / tree: which garlands live:random may put the scene on


class FormulaCheck(BaseModel):
    code: str
    params: list[dict] = []
    inputs: list[dict] = []


@app.post("/api/formulas/check")
def api_formula_check(req: FormulaCheck):
    """Compile only (no render): quick feedback while typing."""
    try:
        defs = formula.clean_params(req.params)
        inputs = formula.clean_inputs(req.inputs, {d["name"] for d in defs})
        formula.compile_formula(req.code, formula.all_names(defs, inputs))
        return {"ok": True}
    except formula.FormulaError as exc:
        return {"ok": False, "error": exc.msg, "line": exc.line}


# ---- API: Home Assistant data and live scenes -------------------------------------------------

@app.get("/api/ha/status")
def api_ha_status():
    if not hadata.available():
        return {"available": False, "error": "no access token: enable homeassistant_api for the add-on"}
    try:
        hadata._get("/")
        return {"available": True}
    except hadata.HAError as exc:
        return {"available": False, "error": str(exc)}


@app.get("/api/ha/entities")
def api_ha_entities(q: str = ""):
    try:
        return hadata.search(q)
    except hadata.HAError as exc:
        raise HTTPException(502, str(exc))


class HAReadReq(BaseModel):
    inputs: list[dict]


@app.post("/api/ha/read")
def api_ha_read(req: HAReadReq):
    """Current value of each input binding (raw and mapped to 0..1)."""
    out = []
    try:
        clean = formula.clean_inputs(req.inputs, set())
    except formula.FormulaError as exc:
        raise HTTPException(400, str(exc))
    for inp in clean:
        try:
            raw, norm = hadata.read_input(inp)
            err = hadata.WATCHER.error(inp["entity"]) if raw is None else None
        except hadata.HAError as exc:
            raw, norm, err = None, None, str(exc)
        out.append({"name": inp["name"], "raw": raw, "value": None if norm is None else round(norm, 3), "error": err})
    return out


class HAHistoryReq(BaseModel):
    inputs: list[dict]
    minutes: float = 30.0


@app.post("/api/ha/history")
def api_ha_history(req: HAHistoryReq):
    """The recent course of each input (raw numbers, evenly spaced) for the charts of the editor."""
    minutes = max(5.0, min(1440.0, req.minutes))
    try:
        clean = formula.clean_inputs(req.inputs, set())
    except formula.FormulaError as exc:
        raise HTTPException(400, str(exc))
    out, t1 = [], time.time()
    for inp in clean:
        item = {"name": inp["name"], "t0": t1 - minutes * 60, "t1": t1}
        if inp.get("attribute"):
            item["error"] = "no history for attributes"
        else:
            try:
                pts = hadata.history_points(inp["entity"], minutes, inp.get("on_states", ()))
                vals = hadata.resample(pts, t1 - minutes * 60, t1, 900)
                item["values"] = [round(v, 4) for v in vals]
                if not vals:
                    item["error"] = "no history in this period"
            except hadata.HAError as exc:
                item["error"] = str(exc)
        out.append(item)
    return out


@app.get("/api/health")
def api_health():
    """Cheap check for the Supervisor watchdog (does not call Home Assistant or the garlands)."""
    return {"ok": True}


RANDOM_FOLLOW_S = 120  # a device that asks for live:random within this time after another one switched joins its round (theme, and the scene if it may play it)


def start_random(names: list, fps: float | None, restart: bool) -> list:
    """One `live:random` round: every garland gets a scene meant for its shape (wall: "wall" or "any", tree: "tree" or "any"),
    the same scene where the pools allow it, and ALL of them one theme (palette and pace, see app/rounds.py)."""
    live_scenes = [f for f in formula.load() if f.get("inputs")]
    if not live_scenes:
        raise HTTPException(404, "no live scene is saved yet: save a formula with inputs in the Formulas tab")
    running = {n: device.live_hosts.get(find_device(n)["host"]) for n in names}
    now = time.time()
    # a round that another garland (not in this call) started a moment ago: the garlands of one room change together even
    # when the automation asks for them one by one
    recent = sorted((st for st in device.live_hosts.values() if st.in_round and st.started and now - st.started < RANDOM_FOLLOW_S
                     and st.dev["name"] not in names and st.thread.is_alive()), key=lambda st: st.started, reverse=True)
    avoid = {st.scene.theme["palette"] for st in device.live_hosts.values()}
    rnd = rounds.plan(live_scenes, {n: device.device_shape(n) for n in names}, {n: running[n].name if running[n] else None for n in names},
                      [(st.name, st.scene.theme) for st in recent], avoid)
    out = []
    for g in rnd["groups"]:
        if g["error"]:
            out += [{"device": n, "error": g["error"]} for n in g["devices"]]
        elif g["kept"]:
            out += [{"device": n, "live": running[n].name, "fps": running[n].fps, "kept": True} for n in g["devices"] if running[n]]
        else:
            out += start_live(g["scene"], g["devices"], fps, restart, theme=rnd["theme"], in_round=True)
    return out


def start_live(scene_name: str, names: list, fps: float | None = None, restart: bool = False,
               theme: dict | None = None, in_round: bool = False) -> list:
    """Start the formula `scene_name` as a live scene on the devices. A running one on the same device is replaced,
    unless it already plays the same scene (then it just keeps running, so a periodic call does not restart it).
    `fps` None = the setting of each device. `random` starts a round (start_random). `theme` is the palette and pace
    of the round (None = the default theme, as for a scene started by name)."""
    if scene_name == "random":
        return start_random(names, fps, restart)
    running = {n: device.live_hosts.get(find_device(n)["host"]) for n in names}
    spec = formula.get(scene_name)
    if spec is None:
        raise HTTPException(404, f"unknown formula {scene_name!r}: save it in the Formulas tab first")
    out = []
    for n in names:
        dev = find_device(n)
        dev_fps = fps if fps is not None else device.device_live_fps(n)
        if dev["host"] in device.scanning_hosts:
            out.append({"device": n, "error": "a position scan is running"})
            continue
        try:
            if running[n] is not None and running[n].name == scene_name and not restart:
                out.append({"device": n, "live": scene_name, "fps": running[n].fps, "kept": True})
                continue
            layout = device.render_layout(dev, spec.get("mapping", "plane"))
            scene = live.LiveScene(spec, layout, {}, theme=theme)  # built first (it fetches history), while the old scene keeps playing
            stream = live.LiveStream(dev, scene, scene_name, dev_fps, in_round)
            old = running[n]
            if old is not None and old.thread.is_alive():
                inherit = (old.prev_mode, old.prev_uid)
                old.stop(restore=False)  # hand over: the garland stays in real-time mode, no flash of the stored movie
                stream.start(inherit=inherit)
            else:
                live.stop_for(dev)
                stream.start()
            out.append({"device": n, "live": scene_name, "fps": stream.fps})
        except HTTPException:
            raise
        except (formula.FormulaError, ValueError) as exc:
            out.append({"device": n, "error": str(exc)})
        except Exception as exc:
            out.append({"device": n, "error": f"cannot start the live scene: {exc}"})
    _drop_status_cache()
    return out


class LivePlay(BaseModel):
    scene: str  # a saved formula name, or "random"
    devices: list[str] = []
    fps: float | None = None  # None = the "Live frames a second" setting of the device
    restart: bool = False  # start again even if this scene is already playing (e.g. after editing it)


@app.post("/api/live/play")
def api_live_play(req: LivePlay):
    names = req.devices or [d["name"] for d in devices()]
    out = start_live(req.scene, names, req.fps, req.restart)
    if not any("live" in o for o in out):
        raise HTTPException(502, out)
    return out


class LiveStop(BaseModel):
    devices: list[str] = []


@app.post("/api/live/stop")
def api_live_stop(req: LiveStop):
    names = req.devices or [d["name"] for d in devices()]
    stopped = [n for n in names if live.stop_for(find_device(n))]
    _drop_status_cache()
    return {"stopped": stopped}


@app.get("/api/live/status")
def api_live_status():
    return [st.status() for st in list(device.live_hosts.values())]


_live: dict = {}
_live_lock = threading.Lock()
LIVE_IDLE_S = 30


class LiveStart(BaseModel):
    device: str
    formula: dict
    params: dict = {}
    replay: dict | None = None  # {"hours": 24, "seconds": 90}: play the history back instead of the current values


@app.post("/api/live/preview/start")
def api_live_preview_start(req: LiveStart):
    """A live preview in the browser: frames computed on request from the current Home Assistant values."""
    dev = find_device(req.device)
    layout = device.render_layout(dev, req.formula.get("mapping", "plane"))  # what the scene is computed on
    shown = device.render_layout(dev)                                       # where the LEDs really are: the picture is drawn there
    replay = None
    try:
        if req.replay is not None:
            spec = formula.validate_item({"name": "live", **req.formula})
            hours = max(1.0, min(168.0, float(req.replay.get("hours", 24))))
            replay = hadata.ReplaySource(spec["inputs"], hours, float(req.replay.get("seconds", 90)))
            scene = live.LiveScene(req.formula, layout, req.params, source=replay, history=replay.history)
        else:
            scene = live.LiveScene(req.formula, layout, req.params)
    except hadata.HAError as exc:
        raise HTTPException(502, str(exc))
    except (formula.FormulaError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    sid = uuid.uuid4().hex[:12]
    with _live_lock:
        for k in [k for k, v in _live.items() if time.time() - v["touched"] > LIVE_IDLE_S]:
            _live.pop(k, None)
        _live[sid] = {"scene": scene, "touched": time.time(), "lock": threading.Lock(), "replay": replay}
    return {"id": sid, "layout": [[p["x"], p["y"]] for p in shown], "ha": hadata.available(),
            "replay_missing": replay.missing if replay else []}


@app.get("/api/live/preview/{sid}/frame")
def api_live_preview_frame(sid: str):
    s = _live.get(sid)
    if s is None:
        raise HTTPException(404, "the live preview expired")
    s["touched"] = time.time()
    with s["lock"]:
        try:
            frame = s["scene"].frame()
        except formula.FormulaError as exc:
            raise HTTPException(400, str(exc))
        out = {"frame": base64.b64encode(frame).decode(), "values": s["scene"].values()}
        if s.get("replay") is not None:
            out["replay"] = {"pos": round(s["replay"].pos(), 4), "at": round(s["replay"].at())}
        return out


class LiveManual(BaseModel):
    name: str
    value: float | None = None  # 0..1 by hand, null = back to the sensor
    kick: bool = False          # fire an event of this input


@app.post("/api/live/preview/{sid}/manual")
def api_live_preview_manual(sid: str, req: LiveManual):
    s = _live.get(sid)
    if s is None:
        raise HTTPException(404, "the live preview expired")
    s["touched"] = time.time()
    scene = s["scene"]
    if req.name not in scene.trk:
        raise HTTPException(404, f"unknown input {req.name!r}")
    with s["lock"]:
        if req.kick:
            scene.fire(req.name)
        else:
            scene.set_manual(req.name, req.value)
    return {"ok": True}


@app.post("/api/live/preview/{sid}/stop")
def api_live_preview_stop(sid: str):
    with _live_lock:
        _live.pop(sid, None)
    return {"stopped": True}


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
    _changed()
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
    _changed()
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
    dev = find_device(req.device)
    layout = device.render_layout(dev, req.instance.mapping)  # the layout the effect is computed on
    shown = device.render_layout(dev)                         # where the LEDs really are: the picture is drawn there
    t0 = time.time()
    try:
        r = compose.render_instance(_dump(req.instance), layout)
    except (formula.FormulaError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    return {"fps": r.fps, "layout": [[p["x"], p["y"]] for p in shown], "frames": _b64(r.frames),
            "render_ms": int((time.time() - t0) * 1000), "seam": _seam(r.frames)}


@app.get("/api/gallery")
def api_gallery(device_name: str = ""):
    """Small animated thumbnails of every saved effect on a device's layout."""
    dev = find_device(device_name) if device_name else (devices() or [None])[0]
    if dev is None:
        return {"layout": [], "items": []}
    layouts = {}
    items = []
    for inst in load_instances():
        try:
            mp = inst.get("mapping", "plane")
            layout = layouts.get(mp) or layouts.setdefault(mp, device.render_layout(dev, mp))
            r = compose.render_instance(inst, layout)
        except Exception as exc:
            log.warning("gallery render %s failed: %s", inst["key"], exc)
            continue
        items.append({"key": inst["key"], "fps": r.fps / GALLERY_STEP, "frames": _b64(r.frames, GALLERY_STEP),
                      "frames_total": len(r.frames)})
    layout = layouts.get("plane") or device.render_layout(dev)
    return {"layout": [[p["x"], p["y"]] for p in layout], "items": items}


# ---- API: devices ---------------------------------------------------------------

def probe(dev: dict) -> dict:
    return {**_probe(dev), "shape": device.device_shape(dev["name"]), "shade": device.device_shade(dev["name"]), "live_fps": device.device_live_fps(dev["name"])}


def _probe(dev: dict) -> dict:
    info = {"name": dev["name"], "host": dev["host"], "online": False}
    if dev["host"] in device.scanning_hosts:
        return {**info, "online": True, "scanning": True, "aspect": device.device_aspect(dev["name"])}
    st = device.live_hosts.get(dev["host"])
    if st is not None:  # streaming: asking the device would only disturb the stream
        return {**info, "online": True, "mode": "rt", "live": st.status(), "aspect": device.device_aspect(dev["name"])}
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
    shape: str | None = None     # "wall" or "tree"
    shade: float | None = None   # tree: how much the far side is dimmed, 0..1
    live_fps: float | None = None  # frames a second of a live scene, 2..25


@app.put("/api/devices/{name}/settings")
def api_device_settings(name: str, req: DevSettings):
    find_device(name)
    if req.aspect is not None and not 0.2 <= req.aspect <= 6:
        raise HTTPException(400, "width / height must be between 0.2 and 6")
    if req.shape is not None and req.shape not in ("wall", "tree"):
        raise HTTPException(400, "shape must be wall or tree")
    changes = {}
    if "aspect" in req.model_fields_set:
        changes["aspect"] = req.aspect
    if req.shape is not None:
        changes["shape"] = req.shape
    if req.shade is not None:
        if not 0 <= req.shade <= 1:
            raise HTTPException(400, "shade must be between 0 and 1")
        changes["shade"] = req.shade
    if req.live_fps is not None:
        if not 2 <= req.live_fps <= 25:
            raise HTTPException(400, "frames a second must be between 2 and 25")
        changes["live_fps"] = req.live_fps
    device.save_device_settings(name, **changes)
    st = device.live_hosts.get(find_device(name)["host"])
    if st is not None and "live_fps" in changes:
        st.set_fps(changes["live_fps"])  # a running scene takes the new rate at once
    _drop_status_cache()
    return {"aspect": req.aspect, "shape": device.device_shape(name)}


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
    except RuntimeError as exc:
        raise HTTPException(409, str(exc))


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
    busy = [n for n in names if find_device(n)["host"] in device.scanning_hosts]  # a position scan owns the device
    names = [n for n in names if n not in busy]
    if not names:
        raise HTTPException(409, f"a position scan is running on {', '.join(busy)}")
    if req.effect.startswith("live:"):
        out = start_live(req.effect[5:], names)
        if not any("live" in o for o in out):
            raise HTTPException(502, out)
        return out
    kept = []
    if req.effect == "random":
        # the automation calls random every few minutes: it must not cut a live scene short
        kept = [{"device": n, "playing": f"live:{device.live_hosts[find_device(n)['host']].name}", "reconcile": "kept"}
                for n in names if find_device(n)["host"] in device.live_hosts]
        names = [n for n in names if find_device(n)["host"] not in device.live_hosts]
        if not names:
            return kept
    else:
        for n in names:
            live.stop_for(find_device(n))
    desired_by_dev = {}
    errors = {n: "a position scan is running" for n in busy}
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

    out = kept + [{"device": n, "error": e} for n, e in errors.items()]
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

DUMP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,40}$")
DUMP_NAME_RE = re.compile(r"^[a-z0-9_]{1,40}\.(png|json)$")
DUMP_KEEP = 4  # scans whose photos are kept


def _dump_dir(sid: str) -> Path:
    if not DUMP_ID_RE.match(sid):
        raise HTTPException(400, "bad scan id")
    return device.DATA_DIR / "scans" / sid


@app.put("/api/scan/dump/{sid}/{fname}")
async def api_scan_dump_put(sid: str, fname: str, request: Request):
    """Photos (and a small meta file) of a scan, kept so that a scan that went wrong can be examined."""
    if not DUMP_NAME_RE.match(fname):
        raise HTTPException(400, "bad file name")
    body = await request.body()
    if len(body) > 12_000_000:
        raise HTTPException(413, "file too large")
    d = _dump_dir(sid)
    d.mkdir(parents=True, exist_ok=True)
    (d / fname).write_bytes(body)
    root = d.parent
    for old in sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)[DUMP_KEEP:]:
        for f in old.iterdir():
            f.unlink()
        old.rmdir()
    return {"saved": fname, "bytes": len(body)}


@app.get("/api/scan/dump")
def api_scan_dump_list():
    root = device.DATA_DIR / "scans"
    if not root.exists():
        return []
    out = []
    for p in sorted(root.iterdir(), reverse=True):
        if p.is_dir():
            fs = [f for f in p.iterdir() if f.is_file()]
            out.append({"id": p.name, "files": sorted(f.name for f in fs), "bytes": sum(f.stat().st_size for f in fs),
                        "time": datetime.fromtimestamp(max((f.stat().st_mtime for f in fs), default=p.stat().st_mtime)).strftime("%Y-%m-%d %H:%M:%S")})
    return out


@app.get("/api/scan/dump/{sid}/{fname}")
def api_scan_dump_get(sid: str, fname: str):
    if not DUMP_NAME_RE.match(fname):
        raise HTTPException(400, "bad file name")
    f = _dump_dir(sid) / fname
    if not f.is_file():
        raise HTTPException(404, "no such file")
    return FileResponse(f)


@app.get("/api/scan/dump/{zipname}")
def api_scan_dump_zip(zipname: str):
    """All files of one kept scan as a zip (open it in the browser to save it)."""
    if not zipname.endswith(".zip"):
        raise HTTPException(404, "no such file")
    d = _dump_dir(zipname[:-4])
    if not d.is_dir():
        raise HTTPException(404, "no such scan")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:  # the PNGs are compressed already
        for f in sorted(d.iterdir()):
            if f.is_file():
                z.write(f, f.name)
    return Response(buf.getvalue(), media_type="application/zip", headers={"Content-Disposition": f'attachment; filename="{zipname}"'})


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
    channels: list[list[int]] = []  # kind "rgb": LEDs lit in red, green, blue


@app.post("/api/scan/pattern")
def api_scan_pattern(req: ScanPattern):
    try:
        return scan.pattern(req.kind, req.bit, req.leds, req.level, req.channels)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc))


class ScanSequence(BaseModel):
    steps: list[ScanPattern]
    slot_ms: int = 240
    lead_ms: int = 700


@app.post("/api/scan/sequence")
def api_scan_sequence(req: ScanSequence):
    """Plays patterns one after the other by itself (the page films them): every `slot_ms`, the first after `lead_ms`."""
    try:
        return scan.play([st.model_dump() for st in req.steps], req.slot_ms, req.lead_ms)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(409, str(exc))


@app.post("/api/scan/stop")
def api_scan_stop():
    return scan.stop()


@app.get("/api/scan/state")
def api_scan_state():
    return scan.state()


@app.get("/api/devices/{name}/layout/backups")
def api_layout_backups(name: str):
    return scan.list_backups(find_device(name))


class ScanRestore(BaseModel):
    device: str
    backup: str


@app.post("/api/scan/restore")
def api_scan_restore(req: ScanRestore):
    try:
        return scan.restore_layout(find_device(req.device), req.backup)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"cannot write the layout: {exc}")


class ScanNote(BaseModel):
    text: str


@app.post("/api/scan/note")
def api_scan_note(req: ScanNote):
    """A line from the page into the add-on log (what the camera measured), so that it can be read without the phone."""
    scan.log.info("page: %s", " ".join(req.text[:900].split()))
    return {"ok": True}


class ScanApply(BaseModel):
    device: str
    coordinates: list[dict]
    scan_type: str = "flat"  # flat | tree | tree-fb
    hidden: list[int] = []     # a tree seen from one side: the LEDs the camera did not see (so on the far side)


@app.post("/api/scan/apply")
def api_scan_apply(req: ScanApply):
    try:
        return scan.apply_layout(find_device(req.device), req.coordinates, req.scan_type, req.hidden)
    except (RuntimeError, ValueError) as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        raise HTTPException(502, f"cannot write the layout: {exc}")


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
