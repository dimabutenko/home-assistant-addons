"""Live scenes shipped as examples. They follow the home: CPU / GPU / power of the two work PCs, the network, the house power, the
sun and the weather. Every fast signal uses an auto range (the last 30 minutes map to 0..1) so it moves over its whole range."""

DCPU = "sensor.dima_pc_satelite_cpuload"
DPOW = "sensor.cabinet_dima_pc_power"
VCPU = "sensor.veron_pc_satelite_cpuload"
VGPU = "sensor.veron_pc_satelite_gpuload"
VPOW = "sensor.cabinet_veron_pc_power"
DOWN = "sensor.keenetic_titan_wifistation_internal_downlink_speed"
UP = "sensor.keenetic_titan_wifistation_internal_uplink_speed"
HOUSE = "sensor.main_energy_sensor_power"
PHB = "sensor.main_energy_sensor_power_b"


def _in(name, entity, lo, hi, smooth=0.4, default=0.4, attribute="", auto=True, kick=0.12):
    return {"name": name, "entity": entity, "attribute": attribute, "min": lo, "max": hi, "smooth": smooth, "default": default,
            "auto": auto, "kick": kick}


def _slow(name, entity, lo, hi, smooth, default, attribute=""):
    return _in(name, entity, lo, hi, smooth, default, attribute, auto=False)


LIVE_EXAMPLES = [
    {"name": "Spectrum live", "code": """# Eight bars like a music spectrum analyser, but the "music" is the home:
# CPU and power of Dima's PC, CPU / GPU / power of Veron's PC, network down and up, house power.
# Each input uses its own last-30-minutes range; the root lifts small values so idle bars still show.
# The caps fall slowly because prev() drags the previous picture down a little.
col = min(floor(u * 8), 7)
xf = fract(u * 8)
lvl = (dcpu if col == 0 else (dpow if col == 1 else (vcpu if col == 2 else (vgpu if col == 3 else (vpow if col == 4 else (down if col == 5 else (up if col == 6 else house)))))))
top = 0.1 + 0.85 * sqrt(lvl)
inside = step(0.1, xf) * step(xf, 0.9)
fill = step(y, top) * inside
body = hsv(col * 0.11 + 0.02, 0.9, 0.3 + 0.7 * min(y / max(top, 0.1), 1)) * fill
cap = smoothstep(top - 0.07, top, y) * step(y, top + 0.02) * inside
ghost = prev(x, y + 0.035) * 0.9 * inside
body + ghost * (1 - fill) + gray(1) * cap""", "params": [],
     "inputs": [_in("dcpu", DCPU, 0, 30, 0.3), _in("dpow", DPOW, 100, 450, 0.3), _in("vcpu", VCPU, 0, 100, 0.3), _in("vgpu", VGPU, 0, 80, 0.3),
                _in("vpow", VPOW, 50, 300, 0.3), _in("down", DOWN, 0, 60, 0.3), _in("up", UP, 0, 40, 0.3), _in("house", HOUSE, 300, 2300, 0.4)]},
    {"name": "Pulse rings live", "code": """# Every time one of five signals JUMPS, a ring is born at a random place of the window and spreads out.
# house power = orange, phase B (kettle, oven) = red, Veron's CPU = cyan, network = green, Dima's PC = violet.
# <input>_count seeds the random place, <input>_age is the ring's age in seconds, <input>_dir is +1 for a rise and -1 for a fall.
a1 = smoothstep(0.1, 0, abs(dist(x, y, (hash(house_count, 1) - 0.5) * w, hash(house_count, 2)) - house_age * 0.45)) * max(1 - house_age / 3.5, 0) * (0.6 + 0.4 * step(0, house_dir))
a2 = smoothstep(0.1, 0, abs(dist(x, y, (hash(phb_count, 3) - 0.5) * w, hash(phb_count, 4)) - phb_age * 0.45)) * max(1 - phb_age / 3.5, 0) * (0.6 + 0.4 * step(0, phb_dir))
a3 = smoothstep(0.1, 0, abs(dist(x, y, (hash(vcpu_count, 5) - 0.5) * w, hash(vcpu_count, 6)) - vcpu_age * 0.45)) * max(1 - vcpu_age / 3.5, 0) * (0.6 + 0.4 * step(0, vcpu_dir))
a4 = smoothstep(0.1, 0, abs(dist(x, y, (hash(down_count, 7) - 0.5) * w, hash(down_count, 8)) - down_age * 0.45)) * max(1 - down_age / 3.5, 0) * (0.6 + 0.4 * step(0, down_dir))
a5 = smoothstep(0.1, 0, abs(dist(x, y, (hash(dpow_count, 9) - 0.5) * w, hash(dpow_count, 10)) - dpow_age * 0.45)) * max(1 - dpow_age / 3.5, 0) * (0.6 + 0.4 * step(0, dpow_dir))
idle = hsv(0.6 + 0.1 * sin(tau * (now * 0.03 + u)), 0.7, 0.07 + 0.05 * sin(tau * (y * 1.5 - now * 0.15)))
idle + hsv(0.08, 0.9, 1) * a1 + hsv(0.0, 0.95, 1) * a2 + hsv(0.5, 0.8, 1) * a3 + hsv(0.33, 0.8, 1) * a4 + hsv(0.78, 0.8, 1) * a5""", "params": [],
     "inputs": [_in("house", HOUSE, 300, 2300, 0.4, 0.4, kick=0.1), _in("phb", PHB, 200, 2200, 0.4, 0.4, kick=0.1), _in("vcpu", VCPU, 0, 100, 0.4, 0.4, kick=0.15),
                _in("down", DOWN, 0, 60, 0.4, 0.4, kick=0.18), _in("dpow", DPOW, 100, 450, 0.4, 0.4, kick=0.12)]},
    {"name": "Network comets live", "code": """# Comets fly along the window: light blue ones fall with the download, magenta ones rise with the upload.
# The faster the traffic, the faster and brighter they are; a burst of traffic makes them flash.
lane = floor(u * 14)
par = lane % 2
off = hash(lane, 5)
yd = 1 - fract(down_phase * 0.5 + now * 0.05 + off)
dd = y - yd
tail_d = max(1 - dd / 0.4, 0) * step(0, dd)
yu = fract(up_phase * 0.5 + now * 0.05 + off)
du = yu - y
tail_u = max(1 - du / 0.4, 0) * step(0, du)
hsv(0.5, 0.7, 1) * tail_d ** 2 * (1 - par) * (0.2 + 0.8 * down + 0.6 * down_kick) + hsv(0.85, 0.7, 1) * tail_u ** 2 * par * (0.2 + 0.8 * up + 0.6 * up_kick) + gray(0.02)""", "params": [],
     "inputs": [_in("down", DOWN, 0, 60, 0.4, 0.4, kick=0.15), _in("up", UP, 0, 40, 0.4, 0.4, kick=0.15)]},
    {"name": "Heartbeat live", "code": """# The window has a pulse: it beats faster the busier the two work PCs are (CPU of both),
# the beat spreads out from the middle, a spike of Veron's GPU adds a flash, the house power warms the colour.
beat = vcpu_phase * 1.4 + dcpu_phase * 0.6 + now * 0.3
tt = fract(beat - dist(x, y, 0, 0.45) * 0.6)
g = min(exp(-((tt - 0.08) / 0.07) ** 2) + 0.75 * exp(-((tt - 0.3) / 0.09) ** 2), 1)
pulse = palette("lava", 0.15 + 0.85 * g) * (0.05 + 0.95 * g)
flash = hsv(0.55, 0.5, vgpu_kick * 0.6 * smoothstep(0.6, 0, r))
(pulse + flash) * mix(rgb(0.9, 0.95, 1.1), rgb(1.15, 0.9, 0.8), house)""", "params": [],
     "inputs": [_in("vcpu", VCPU, 0, 100, 0.5), _in("dcpu", DCPU, 0, 30, 0.5), _in("vgpu", VGPU, 0, 80, 0.4, 0.3, kick=0.15), _in("house", HOUSE, 300, 2300, 1.0)]},
    {"name": "House live", "code": """# The home as a living picture. Sky follows the sun (night blue, orange dusk, blue day); clouds thicken with cloud cover
# and drift faster with network traffic; a warm glow rises from the bottom as far as the radiator valve is open and
# flares when the house power jumps; the left half twinkles with Dima's CPU, the right half with Veron's (more load, more
# sparkles, faster); the whole picture warms up with the power draw of the house.
night = palette("ocean", 0.3) * 0.3
dusk = palette("sunset", 0.6)
day = palette("ocean", 0.6)
sky = mix(mix(night, dusk, smoothstep(0.05, 0.3, sun)), day, smoothstep(0.3, 0.6, sun))
drift = noise(x * 2.2 + now * 0.05 + down_phase * 0.5, y * 2.5 - now * 0.03)
cover = smoothstep(0.75 - clouds * 0.5, 0.95 - clouds * 0.5, drift)
base = mix(sky, gray(0.35 + 0.5 * sun), cover * (0.3 + 0.5 * clouds))
glow = min(smoothstep(valve * 0.9 + house_kick * 0.5, 0, y) * (valve + house_kick * 0.8), 1)
warm = palette("fire", 0.35 + 0.5 * glow) * glow
side = step(0, x)
load = mix(dcpu, vcpu, side)
s = hash(i, seed)
lit = step(hash(i, seed + 1), 0.08 + load * 0.8)
tw = max(1 - fract(now * (1.5 + load * 3) + s) * 3.5, 0) ** 2
spark = hsv(0.55 + side * 0.25, 0.5, tw * lit * 1.8)
(base + warm + spark) * mix(rgb(0.85, 1.0, 1.2), rgb(1.2, 1.0, 0.8), house)""", "params": [],
     "inputs": [_slow("sun", "sun.sun", -8, 40, 5, 0.4, "elevation"), _slow("clouds", "weather.forecast_home_2", 0, 100, 10, 0.5, "cloud_coverage"),
                _slow("valve", "sensor.living_room_radiator_position", 0, 100, 8, 0.25), _in("house", HOUSE, 300, 2300, 0.5, 0.4, kick=0.1),
                _in("dcpu", DCPU, 0, 30, 0.4), _in("vcpu", VCPU, 0, 100, 0.4), _in("down", DOWN, 0, 60, 1.0)]},
    {"name": "Rings live", "code": """# Rings spreading from the centre (like the old music visualisers).
# More rings when the house draws more power, they spread faster with the network traffic,
# a spike of Veron's CPU flashes them and shifts the colours, the sun sets the base colour.
rings = 2 + house * 5
ph = down_phase * 1.2 + now * 0.12
wave = 0.5 + 0.5 * sin(tau * (r * rings - ph))
hue = r * 0.8 + sun * 0.9 - ph * 0.1 + vcpu_kick * 0.3
cpalette("rainbow", hue) * smoothstep(0.3, 0.95, wave) * (0.5 + 0.5 * house + vcpu_kick * 0.6)""", "params": [],
     "inputs": [_in("house", HOUSE, 300, 2300, 0.5, 0.4, kick=0.1), _in("down", DOWN, 0, 60, 0.6), _slow("sun", "sun.sun", -8, 40, 5, 0.4, "elevation"),
                _in("vcpu", VCPU, 0, 100, 0.3, 0.3, kick=0.15)]},
    {"name": "Kaleidoscope live", "code": """# A six-fold mirror: one wedge of drifting noise repeated around the centre.
# It turns with the GPU of Veron's PC, gets finer with the house power, the colours follow the sun
# and the CPU of Dima's PC shifts the hue; a spike of it makes the picture flare.
spin = a + vgpu_phase * 0.06 + now * 0.01
m = mirror(spin, 6)
px = r * cos(m * tau)
py = r * sin(m * tau)
zoom = 3 + house * 5
q = noise(px * zoom + now * 0.25 + dcpu_phase * 0.5, py * zoom - now * 0.2)
cpalette("neon", q * 0.8 + sun * 0.6 + r * 0.5 + dcpu * 0.3) * (0.25 + 0.75 * smoothstep(0.2, 0.8, q)) * (0.8 + dcpu_kick * 0.5)""", "params": [],
     "inputs": [_in("vgpu", VGPU, 0, 80, 0.4), _in("house", HOUSE, 300, 2300, 0.6), _slow("sun", "sun.sun", -8, 40, 5, 0.4, "elevation"),
                _in("dcpu", DCPU, 0, 30, 0.3, 0.3, kick=0.15)]},
    {"name": "Spiral live", "code": """# A spiral with three arms. It winds tighter with the house power, turns with the network traffic,
# the colour follows the power of Dima's PC and the sun, and it flares when the house power jumps.
arms = 3
twist = 1 + house * 4
s = fract(a * arms + r * twist - down_phase * 0.8 - now * 0.08)
band = smoothstep(0, 0.35, s) * smoothstep(1, 0.65, s)
cpalette("aurora", r * 0.6 + dpow * 0.5 + sun * 0.3) * band * (0.3 + 0.7 * (1 - r * 0.6)) * (0.8 + house_kick * 0.6)""", "params": [],
     "inputs": [_in("house", HOUSE, 300, 2300, 0.6, 0.4, kick=0.1), _in("down", DOWN, 0, 60, 0.6), _in("dpow", DPOW, 100, 450, 0.5),
                _slow("sun", "sun.sun", -8, 40, 5, 0.4, "elevation")]},
    {"name": "Tunnel live", "code": """# Feedback, like MilkDrop: the previous picture is pulled outward and faded, and a fresh ring is born in the middle.
# Rings are born in the middle in rhythm with the network traffic; the more traffic, the faster the tunnel.
# When phase B (kettle, oven) jumps, a bright burst flies out of the centre.
# Needs live mode (stored it runs one warm-up loop).
zoom = 0.97 - down * 0.025
old = prev(x * zoom, (y - 0.5) * zoom + 0.5) * 0.95
beat = 0.5 + 0.5 * sin(tau * (now * 0.6 + down_phase * 0.4))
ring = smoothstep(0.08, 0, abs(r - 0.1)) * beat
burst = smoothstep(0.35, 0, abs(r - 0.1)) * phb_kick
old + cpalette("rainbow", sun + now * 0.08 + house * 0.5) * (ring * (0.5 + house * 0.7) + burst)""", "params": [],
     "inputs": [_in("down", DOWN, 0, 60, 0.5), _in("house", HOUSE, 300, 2300, 0.6), _slow("sun", "sun.sun", -8, 40, 5, 0.4, "elevation"),
                _in("phb", PHB, 200, 2200, 0.3, 0.3, kick=0.1)]},
    {"name": "Mandala live", "code": """# Two seven-petal flowers turning in opposite directions: the outer one with the CPU load of Dima's PC, the inner one
# with the CPU of Veron's. Sunset colours follow the sun, the inner flower glows with the house power,
# and a spike of Veron's GPU makes both flowers breathe out.
petals = 7
breathe = 1 + 0.2 * vgpu_kick
big = (0.32 + 0.1 * cos(tau * (a * petals + dcpu_phase * 0.15))) * breathe
small = (0.16 + 0.06 * cos(tau * (a * petals - vcpu_phase * 0.2))) * breathe
g1 = smoothstep(0.1, 0, abs(r - big))
g2 = smoothstep(0.08, 0, abs(r - small))
palette("sunset", 0.5 + 0.4 * sun) * g1 + palette("ocean", 0.4 + 0.5 * house) * g2 * (0.4 + 0.6 * house)""", "params": [],
     "inputs": [_in("dcpu", DCPU, 0, 30, 0.4), _in("vcpu", VCPU, 0, 100, 0.4), _slow("sun", "sun.sun", -8, 40, 5, 0.4, "elevation"),
                _in("house", HOUSE, 300, 2300, 0.6), _in("vgpu", VGPU, 0, 80, 0.3, 0.3, kick=0.15)]},
]
