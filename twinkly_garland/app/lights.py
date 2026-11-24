"""Room lights that the position scan may set (the page tries a few brightnesses / colour temperatures and keeps the one the camera
likes best) and puts back afterwards.

Only the lights listed in the add-on option `scan_lights` can be touched. The state a light had before the scan changed it is
saved (in memory and in /data) and written back when the scan session ends, also after a restart of the add-on.
"""
import json
import logging
import os
import threading
from pathlib import Path

import requests

from . import hadata

log = logging.getLogger("twinkly.lights")
_lock = threading.Lock()
_saved: dict = {}  # entity -> the state before the scan changed it
SAVED_PATH = Path(os.environ.get("DATA_DIR", "/data")) / "scan_lights_saved.json"
COLOUR_KEYS = {"color_temp": "color_temp_kelvin", "hs": "hs_color", "xy": "xy_color", "rgb": "rgb_color"}


def configured(options: dict) -> list:
    return [e for e in (options.get("scan_lights") or []) if isinstance(e, str) and e.startswith("light.")]


def _post(service: str, data: dict):
    if not hadata.available():
        raise hadata.HAError("Home Assistant access is not available")
    try:
        r = requests.post(f"{hadata.base_url()}/api/services/light/{service}", json=data,
                          headers={"Authorization": f"Bearer {hadata.token()}"}, timeout=8)
    except requests.RequestException as exc:
        raise hadata.HAError(f"cannot reach Home Assistant: {type(exc).__name__}") from None
    if r.status_code >= 400:
        raise hadata.HAError(f"light.{service} answered HTTP {r.status_code}")


def info(entities: list) -> list:
    """What the page needs to know about each configured light."""
    out = []
    for e in entities:
        try:
            st = hadata._get(f"/states/{e}")
        except hadata.HAError as exc:
            out.append({"entity": e, "error": str(exc)})
            continue
        a = st.get("attributes", {})
        modes = a.get("supported_color_modes") or []
        out.append({
            "entity": e, "name": a.get("friendly_name", e), "state": st.get("state"),
            "brightness": "brightness" in (a or {}) or any(m != "onoff" for m in modes),
            "color_temp": "color_temp" in modes,
            "kelvin": [a.get("min_color_temp_kelvin"), a.get("max_color_temp_kelvin")] if "color_temp" in modes else None,
            "colour": any(m in modes for m in ("hs", "xy", "rgb", "rgbw", "rgbww")),
        })
    return out


def _snapshot(entity: str) -> dict:
    st = hadata._get(f"/states/{entity}")
    a = st.get("attributes", {})
    snap = {"state": st.get("state"), "brightness": a.get("brightness"), "color_mode": a.get("color_mode")}
    for k in COLOUR_KEYS.values():
        if a.get(k) is not None:
            snap[k] = a.get(k)
    return snap


def _persist():
    try:
        SAVED_PATH.parent.mkdir(parents=True, exist_ok=True)
        if _saved:
            SAVED_PATH.write_text(json.dumps(_saved))
        elif SAVED_PATH.exists():
            SAVED_PATH.unlink()
    except OSError as exc:
        log.warning("cannot save the light state: %s", exc)


def set_light(options: dict, entity: str, on: bool, brightness_pct=None, kelvin=None) -> dict:
    if entity not in configured(options):
        raise ValueError("this light is not in the add-on option scan_lights")
    with _lock:
        if entity not in _saved:
            _saved[entity] = _snapshot(entity)
            _persist()
        if not on:
            _post("turn_off", {"entity_id": entity, "transition": 0})
        else:
            data = {"entity_id": entity, "transition": 0}
            if brightness_pct is not None:
                data["brightness_pct"] = max(1, min(100, int(brightness_pct)))
            if kelvin:
                data["color_temp_kelvin"] = int(kelvin)
            _post("turn_on", data)
    return {"entity": entity, "on": on}


def restore() -> list:
    """Puts every light back as it was before the scan touched it."""
    done = []
    with _lock:
        if not _saved and SAVED_PATH.exists():  # the add-on was restarted during a scan
            try:
                _saved.update(json.loads(SAVED_PATH.read_text()))
            except (OSError, ValueError):
                pass
        for entity, snap in list(_saved.items()):
            try:
                if snap.get("state") != "on":
                    _post("turn_off", {"entity_id": entity, "transition": 0})
                else:
                    data = {"entity_id": entity, "transition": 0}
                    if snap.get("brightness"):
                        data["brightness"] = snap["brightness"]
                    key = COLOUR_KEYS.get(snap.get("color_mode") or "")
                    if key and snap.get(key) is not None:
                        data[key] = snap[key]
                    _post("turn_on", data)
                done.append(entity)
                del _saved[entity]
            except hadata.HAError as exc:
                log.warning("cannot restore %s: %s", entity, exc)
        _persist()
    if done:
        log.info("lights put back: %s", ", ".join(done))
    return done
