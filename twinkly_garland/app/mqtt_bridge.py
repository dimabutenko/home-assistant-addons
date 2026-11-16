"""MQTT bridge: shows every configured garland in Home Assistant as a light (MQTT discovery).

The add-on is the only client of the garlands (the device keeps a single login token, so a second client such as the
Home Assistant Twinkly integration makes both of them fight over it). Home Assistant talks to the add-on through the
MQTT broker instead:

  homeassistant/<component>/twinkly_<slug>_<what>/config   discovery (retained)
  twinkly/status                                           add-on availability (last will)
  twinkly/<slug>/available                                 device availability
  twinkly/<slug>/state                                     JSON state of the light + diagnostics (retained)
  twinkly/<slug>/set                                       JSON light commands from Home Assistant

The light uses the JSON schema: state, brightness (0..255) and effect. Effects are the effects of the library
(played from the garland itself), `random`, the live scenes `live:<name>` and `live:random`.
Nothing here is required: without `mqtt_host` in the options the bridge stays off.
"""
import json
import logging
import queue
import re
import threading
import time

from . import device, live

log = logging.getLogger("twinkly.mqtt")

STATUS_TOPIC = "twinkly/status"
POLL_S = 15          # how often an idle device is asked for its state
TICK_S = 1.0
HEARTBEAT_S = 60     # republish an unchanged state at least this often
DISCOVERY_S = 300    # and the discovery (the list of effects may have changed)


def slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_") or "garland"


class Bridge:
    def __init__(self, ctl, opts: dict, client_factory=None):
        """`ctl` is the glue to the rest of the add-on: devices() -> list, effect_names(dev) -> list[str],
        play(effect, names), changed() (drops caches)."""
        self.ctl, self.opts = ctl, opts
        self.client = None
        self.factory = client_factory
        self.connected = False
        self.stop_evt = threading.Event()
        self.cmds: queue.Queue = queue.Queue()
        self.locks: dict = {}
        self.last: dict = {}       # slug -> (payload json, time)
        self.next_poll: dict = {}  # slug -> time of the next device query
        self.cache: dict = {}      # slug -> last state read from the device
        self.avail: dict = {}      # slug -> bool
        self.discovery_t = 0.0
        self.threads: list = []

    # -- lifecycle ----------------------------------------------------------------------------------------------
    def start(self):
        if self.factory is not None:
            self.client = self.factory()
        else:
            import paho.mqtt.client as mqtt
            self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="twinkly_garland")
        o = self.opts
        if o.get("mqtt_user"):
            self.client.username_pw_set(o["mqtt_user"], o.get("mqtt_password") or None)
        self.client.will_set(STATUS_TOPIC, "offline", retain=True)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect
        self.client.on_message = self._on_message
        self.client.reconnect_delay_set(1, 30)
        self.client.connect_async(o["mqtt_host"], int(o.get("mqtt_port", 1883)))
        self.client.loop_start()
        for target in (self._loop, self._worker):
            th = threading.Thread(target=target, daemon=True)
            th.start()
            self.threads.append(th)
        log.info("MQTT bridge started (%s:%s)", o["mqtt_host"], o.get("mqtt_port", 1883))

    def stop(self):
        self.stop_evt.set()
        self.cmds.put(None)
        try:
            if self.connected:
                self.client.publish(STATUS_TOPIC, "offline", retain=True)
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def changed(self):
        """Effects or devices changed: publish the discovery again soon."""
        self.discovery_t = 0.0

    # -- MQTT callbacks -------------------------------------------------------------------------------------------
    def _on_connect(self, client, _userdata, _flags, rc, *_a):
        ok = getattr(rc, "value", rc) == 0
        if not ok:
            log.warning("MQTT connect refused: %s", rc)
            return
        self.connected = True
        client.subscribe("twinkly/+/set")
        client.publish(STATUS_TOPIC, "online", retain=True)
        self.discovery_t = 0.0
        self.last.clear()
        log.info("MQTT connected")

    def _on_disconnect(self, *_a):
        self.connected = False
        log.warning("MQTT disconnected")

    def _on_message(self, _client, _userdata, msg):
        m = re.fullmatch(r"twinkly/([a-z0-9_]+)/set", msg.topic)
        if m:
            self.cmds.put((m.group(1), msg.payload))

    # -- discovery ------------------------------------------------------------------------------------------------------
    def _discovery(self):
        for dev in self.ctl.devices():
            s = slug(dev["name"])
            avail = [{"topic": STATUS_TOPIC}, {"topic": f"twinkly/{s}/available"}]
            dev_info = {"identifiers": [f"twinkly_garland_{s}"], "name": dev["name"], "manufacturer": "Twinkly",
                        "model": "Twinkly Gen2 (via Twinkly Garland add-on)"}
            light = {
                "name": None, "unique_id": f"twinkly_garland_{s}_light", "default_entity_id": f"light.{s}",
                "schema": "json", "state_topic": f"twinkly/{s}/state", "command_topic": f"twinkly/{s}/set",
                "brightness": True, "supported_color_modes": ["brightness"], "effect": True,
                "effect_list": self.ctl.effect_names(dev),
                "availability": avail, "availability_mode": "all", "device": dev_info,
            }
            self._pub(f"homeassistant/light/twinkly_{s}/config", light)
            for what, label, unit, tpl in (
                ("scene", "Live scene", None, "{{ value_json.scene }}"),
                ("fps", "Live fps", "fps", "{{ value_json.fps }}"),
                ("ping", "Live slowest ping", "ms", "{{ value_json.ping_max_ms }}"),
                ("relogins", "Live re-logins", None, "{{ value_json.relogins }}"),
            ):
                sensor = {
                    "name": label, "unique_id": f"twinkly_garland_{s}_{what}",
                    "default_entity_id": f"sensor.{s}_live_{what}", "state_topic": f"twinkly/{s}/state",
                    "value_template": tpl, "entity_category": "diagnostic", "availability": avail,
                    "availability_mode": "all", "device": dev_info,
                }
                if unit:
                    sensor["unit_of_measurement"] = unit
                self._pub(f"homeassistant/sensor/twinkly_{s}_{what}/config", sensor)
        self.discovery_t = time.time()

    def _pub(self, topic: str, payload, retain: bool = True):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload, ensure_ascii=False)
        self.client.publish(topic, payload, retain=retain)

    # -- state ------------------------------------------------------------------------------------------------------
    def _read_device(self, dev: dict) -> dict:
        """Ask the device (never while a live stream runs: that one already knows everything)."""
        with device.lock_for(dev["host"]):
            ci = device.connect(dev["host"])
            mode = device.retry(ci.get_mode).get("mode")
            br = device.retry(ci.get_brightness)
            pct = 100 if br.get("mode") == "disabled" else int(br.get("value", 100))
            effect = None
            if mode == "movie":
                uid = (device.retry(ci.get_movies_current).get("unique_id") or "").upper()
                for m in device.retry(ci.get_movies).get("movies", []):
                    if (m.get("unique_id") or "").upper() == uid:
                        effect = m.get("name")
        return {"mode": mode, "brightness": round(pct * 255 / 100), "effect": effect}

    def _state(self, dev: dict, force: bool = False):
        """The payload to publish, or None when the device cannot be reached."""
        s = slug(dev["name"])
        st = device.live_hosts.get(dev["host"])
        prev = self.cache.get(s, {})
        if st is not None:
            info = st.status()
            self.cache[s] = {**prev, "mode": "rt"}
            self.avail[s] = True
            return {"state": "ON", "brightness": prev.get("brightness", 255), "effect": f"live:{st.name}",
                    "scene": st.name, "fps": round(info["fps"]), "ping_max_ms": round(info["ping_max_ms"] / 10) * 10,
                    "relogins": info["relogins"]}
        if dev["host"] in device.scanning_hosts:
            return None
        if not force and time.time() < self.next_poll.get(s, 0):
            return {"_same": True}
        self.next_poll[s] = time.time() + POLL_S
        try:
            d = self._read_device(dev)
        except Exception as exc:
            if self.avail.get(s, True):
                log.info("%s is not reachable: %s", dev["name"], exc)
            self.avail[s] = False
            return None
        self.cache[s] = d
        self.avail[s] = True
        return {"state": "OFF" if d["mode"] == "off" else "ON", "brightness": d["brightness"],
                "effect": d["effect"] or "", "scene": "none", "fps": 0, "ping_max_ms": 0, "relogins": 0}

    def _publish_state(self, dev: dict, force: bool = False):
        s = slug(dev["name"])
        payload = self._state(dev, force)
        if payload is not None and payload.get("_same"):
            payload = self._from_cache(dev)
        if payload is None:
            self._pub(f"twinkly/{s}/available", "offline")
            return
        self._pub(f"twinkly/{s}/available", "online")
        text = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        old = self.last.get(s)
        if old is None or old[0] != text or time.time() - old[1] > HEARTBEAT_S:
            self._pub(f"twinkly/{s}/state", text)
            self.last[s] = (text, time.time())

    def _from_cache(self, dev: dict):
        d = self.cache.get(slug(dev["name"]))
        if not d:
            return None
        return {"state": "OFF" if d["mode"] == "off" else "ON", "brightness": d["brightness"],
                "effect": d["effect"] or "", "scene": "none", "fps": 0, "ping_max_ms": 0, "relogins": 0}

    def _loop(self):
        while not self.stop_evt.is_set():
            try:
                if self.connected:
                    if time.time() - self.discovery_t > DISCOVERY_S:
                        self._discovery()
                    for dev in self.ctl.devices():
                        self._publish_state(dev)
            except Exception:
                log.exception("MQTT state loop")
            self.stop_evt.wait(TICK_S)

    # -- commands ------------------------------------------------------------------------------------------------------
    def _worker(self):
        while not self.stop_evt.is_set():
            item = self.cmds.get()
            if item is None:
                break
            s, raw = item
            dev = next((d for d in self.ctl.devices() if slug(d["name"]) == s), None)
            if dev is None:
                continue
            lock = self.locks.setdefault(s, threading.Lock())
            threading.Thread(target=self._command, args=(dev, raw, lock), daemon=True).start()

    def _command(self, dev: dict, raw: bytes, lock: threading.Lock):
        try:
            cmd = json.loads(raw)
            if not isinstance(cmd, dict):
                return
        except ValueError:
            log.warning("bad command for %s: %r", dev["name"], raw[:80])
            return
        with lock:
            try:
                self.apply(dev, cmd)
            except Exception as exc:
                log.warning("command %s for %s failed: %s", cmd, dev["name"], exc)
            self.next_poll[slug(dev["name"])] = 0
            try:
                self.ctl.changed()
                self._publish_state(dev, force=True)
            except Exception:
                log.exception("state after the command")

    def apply(self, dev: dict, cmd: dict):
        """Turn a light command from Home Assistant into device calls."""
        host = dev["host"]
        state = str(cmd.get("state", "")).upper()
        if state == "OFF":
            live.stop_for(dev, restore=False)
            with device.lock_for(host):
                device.retry(device.connect(host).set_mode, "off")
            return
        if "brightness" in cmd:
            pct = max(1, min(100, round(float(cmd["brightness"]) * 100 / 255)))
            with device.lock_for(host):
                device.retry(device.connect(host).set_brightness, pct)
            self.cache.setdefault(slug(dev["name"]), {})["brightness"] = round(pct * 255 / 100)
        if cmd.get("effect"):
            self.ctl.play(str(cmd["effect"]), [dev["name"]])
        elif state == "ON" and host not in device.live_hosts:
            with device.lock_for(host):
                ci = device.connect(host)
                if device.retry(ci.get_mode).get("mode") == "off":
                    device.retry(ci.set_mode, "movie")
