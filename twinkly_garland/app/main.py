"""Twinkly Garland add-on: API + web UI."""
import asyncio
import base64
import json
import logging
import os
import random
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import device, effects

OPTIONS_PATH = Path(os.environ.get("OPTIONS_PATH", "/data/options.json"))
STATIC = Path(__file__).parent / "static"
KEY_RE = re.compile(r"^[A-Za-z0-9 _-]{1,32}$")

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


def load_instances() -> list:
    try:
        return json.loads(_instances_path().read_text())
    except (OSError, ValueError):
        return [{"key": "flame", "effect": "flame", "params": {}, "devices": []}]


def save_instances(items: list) -> None:
    p = _instances_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, indent=1))


def desired_for(dev: dict) -> list:
    return device.build_desired(dev, load_instances(), effects.render)


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
        opts = options()
        await asyncio.sleep(int(opts.get("ensure_interval_min", 60)) * 60)
        if options().get("auto_ensure"):
            await asyncio.get_running_loop().run_in_executor(None, ensure_all)


@asynccontextmanager
async def lifespan(_app):
    task = asyncio.create_task(_auto_loop())
    yield
    task.cancel()


app = FastAPI(title="Twinkly Garland", lifespan=lifespan)


# ---- API ----------------------------------------------------------------

def probe(dev: dict) -> dict:
    info = {"name": dev["name"], "host": dev["host"], "online": False}
    try:
        ci = device.connect(dev["host"])
        info["firmware"] = device.retry(ci.firmware_version)["version"]
        movies = device.retry(ci.get_movies)
        info["movies"] = [
            {"id": m["id"], "name": m["name"], "unique_id": m["unique_id"], "frames": m["frames_number"]}
            for m in movies["movies"]
        ]
        info["available_frames"] = movies["available_frames"]
        info["online"] = True
    except Exception as exc:
        info["error"] = type(exc).__name__
    return info


@app.get("/api/devices")
def api_devices():
    return [probe(d) for d in devices()]


@app.get("/api/effects")
def api_effects():
    return {k: {"title": v["title"], "params": v["params"]} for k, v in effects.GENERATORS.items()}


@app.get("/api/instances")
def api_instances():
    return load_instances()


class Instance(BaseModel):
    key: str
    effect: str
    params: dict = {}
    devices: list[str] = []


@app.put("/api/instances")
def api_save_instances(items: list[Instance]):
    keys = [i.key for i in items]
    if len(set(keys)) != len(keys):
        raise HTTPException(400, "duplicate keys")
    for i in items:
        if not KEY_RE.match(i.key):
            raise HTTPException(400, f"bad key {i.key!r}")
        if i.effect not in effects.GENERATORS:
            raise HTTPException(400, f"unknown effect {i.effect!r}")
    save_instances([i.model_dump() for i in items])
    return {"saved": len(items)}


class PreviewReq(BaseModel):
    effect: str
    params: dict = {}
    device: str


@app.post("/api/preview")
def api_preview(req: PreviewReq):
    """Render on the server, play in the browser against the real layout."""
    if req.effect not in effects.GENERATORS:
        raise HTTPException(400, "unknown effect")
    layout = device.get_layout(find_device(req.device))
    r = effects.render(req.effect, layout, req.params)
    return {
        "fps": r.fps,
        "layout": [[p["x"], p["y"]] for p in layout],
        "frames": [base64.b64encode(f).decode() for f in r.frames],
    }


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
    try:
        return device.ensure(dev, desired_for(dev))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/ensure")
def api_ensure_all():
    return ensure_all()


class PlayReq(BaseModel):
    effect: str  # instance key
    devices: list[str] = []  # empty = every configured device


@app.post("/api/play")
def api_play(req: PlayReq):
    """Play effect `key` on the given devices. Reconciles first when the device
    drifted (e.g. a firmware update wiped the movies), so playback never breaks."""
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
        # One key for every device, so garlands stay in sync with each other.
        common = None
        for desired in desired_by_dev.values():
            keys = {m["key"] for m in desired}
            common = keys if common is None else common & keys
        if not common:
            raise HTTPException(404, "no effect is configured for all of the target devices")
        key = random.choice(sorted(common))

    out = [{"device": n, "error": e} for n, e in errors.items()]
    for n, desired in desired_by_dev.items():
        dev = find_device(n)
        try:
            if not any(m["key"] == key for m in desired):
                raise KeyError(f"effect {key!r} is not configured for {n}")
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


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
