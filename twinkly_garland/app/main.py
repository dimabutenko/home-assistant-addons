"""Twinkly Garland add-on: minimal service (scaffold)."""
import json
import logging
import os
import socket
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from xled import ControlInterface

OPTIONS_PATH = Path(os.environ.get("OPTIONS_PATH", "/data/options.json"))
STATIC = Path(__file__).parent / "static"

log = logging.getLogger("twinkly")
app = FastAPI(title="Twinkly Garland")
pool = ThreadPoolExecutor(max_workers=4)


def load_devices() -> list[dict]:
    try:
        return json.loads(OPTIONS_PATH.read_text()).get("devices", [])
    except (OSError, ValueError):
        return []


def probe(dev: dict) -> dict:
    """Read-only device status; never raises."""
    info = {"name": dev["name"], "host": dev["host"], "online": False}
    try:
        # xled has no default timeout; fail fast on an unreachable device
        socket.create_connection((dev["host"], 80), timeout=3).close()
        ci = ControlInterface(dev["host"])
        info["firmware"] = ci.firmware_version()["version"]
        movies = ci.get_movies()
        info["movies"] = [
            {"id": m["id"], "name": m["name"], "unique_id": m["unique_id"]}
            for m in movies["movies"]
        ]
        info["available_frames"] = movies["available_frames"]
        info["online"] = True
    except Exception as exc:  # device drops connections sometimes
        info["error"] = type(exc).__name__
        log.warning("probe %s failed: %s", dev["host"], exc)
    return info


@app.get("/api/devices")
def devices():
    return list(pool.map(probe, load_devices()))


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")
