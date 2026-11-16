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
a1 = smoothstep(0.1, 0, abs(dist(x, y, (hash(house_count, 1) - 0.5) * w, hash(house_count, 2)) - house_age * 0.45)) * max(1 - house_age / 5, 0) * (0.6 + 0.4 * step(0, house_dir))
a2 = smoothstep(0.1, 0, abs(dist(x, y, (hash(phb_count, 3) - 0.5) * w, hash(phb_count, 4)) - phb_age * 0.45)) * max(1 - phb_age / 5, 0) * (0.6 + 0.4 * step(0, phb_dir))
a3 = smoothstep(0.1, 0, abs(dist(x, y, (hash(vcpu_count, 5) - 0.5) * w, hash(vcpu_count, 6)) - vcpu_age * 0.45)) * max(1 - vcpu_age / 5, 0) * (0.6 + 0.4 * step(0, vcpu_dir))
a4 = smoothstep(0.1, 0, abs(dist(x, y, (hash(down_count, 7) - 0.5) * w, hash(down_count, 8)) - down_age * 0.45)) * max(1 - down_age / 5, 0) * (0.6 + 0.4 * step(0, down_dir))
a5 = smoothstep(0.1, 0, abs(dist(x, y, (hash(dpow_count, 9) - 0.5) * w, hash(dpow_count, 10)) - dpow_age * 0.45)) * max(1 - dpow_age / 5, 0) * (0.6 + 0.4 * step(0, dpow_dir))
idle = hsv(0.6 + 0.1 * sin(tau * (now * 0.03 + u)), 0.7, 0.07 + 0.05 * sin(tau * (y * 1.5 - now * 0.15)))
idle + 1.7 * (hsv(0.08 + hash(house_count, 11) * 0.25, 0.9, 1) * a1 + hsv(hash(phb_count, 12) * 0.2, 0.95, 1) * a2 + hsv(0.45 + hash(vcpu_count, 13) * 0.25, 0.8, 1) * a3 + hsv(0.25 + hash(down_count, 14) * 0.25, 0.8, 1) * a4 + hsv(0.72 + hash(dpow_count, 15) * 0.25, 0.8, 1) * a5)""", "params": [],
     "inputs": [_in("house", HOUSE, 300, 2300, 0.4, 0.4, kick=0.1), _in("phb", PHB, 200, 2200, 0.4, 0.4, kick=0.1), _in("vcpu", VCPU, 0, 100, 0.4, 0.4, kick=0.15),
                _in("down", DOWN, 0, 60, 0.4, 0.4, kick=0.18), _in("dpow", DPOW, 100, 450, 0.4, 0.4, kick=0.12)]},
    {"name": "Network comets live", "code": """# Comets fly along the window: they fall with the download and rise with the upload, every lane in its own colour
# (the upload comets in the opposite colour of their lane), on a dark background.
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
hsv(hash(lane, 6), 1, 1) * tail_d ** 2 * (1 - par) * (0.2 + 0.8 * down + 0.6 * down_kick) + hsv(fract(hash(lane, 6) + 0.5), 1, 1) * tail_u ** 2 * par * (0.2 + 0.8 * up + 0.6 * up_kick) + gray(0.02)""", "params": [],
     "inputs": [_in("down", DOWN, 0, 60, 0.4, 0.4, kick=0.15), _in("up", UP, 0, 40, 0.4, 0.4, kick=0.15)]},
    {"name": "Heartbeat live", "code": """# The window has a pulse: it beats faster the busier the two work PCs are (CPU of both), the beat spreads out from the middle.
# Every beat has its own colour (far from the previous one) and a spike of Veron's GPU adds a flash in the opposite colour;
# the house power warms the whole picture.
beat = vcpu_phase * 1.4 + dcpu_phase * 0.6 + now * 0.3
wave = beat - dist(x, y, 0, 0.45) * 1.7
tt = fract(wave)
g = min(exp(-((tt - 0.08) / 0.07) ** 2) + 0.75 * exp(-((tt - 0.3) / 0.09) ** 2), 1)
cycle = floor(wave)
pulse = hsv(fract(cycle * 0.382 + vcpu * 0.5), 1, 1) * (0.04 + 0.96 * g ** 1.15)
flash = hsv(fract(cycle * 0.382 + vcpu * 0.5 + 0.5), 0.7, vgpu_kick * 0.7 * smoothstep(0.6, 0, r))
(pulse + flash) * 1.7 * mix(rgb(0.9, 0.95, 1.1), rgb(1.15, 0.9, 0.8), house)""", "params": [],
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
    {"name": "Rings live", "code": """# Rings spreading from the centre, every ring in a different colour (neighbouring rings are far apart on the colour wheel) with
# dark gaps between them. More rings when the house draws more power, they spread faster with the network traffic,
# a spike of Veron's CPU flashes them and the sun shifts all the hues.
rings = 2 + house * 5
ph = down_phase * 1.2 + now * 0.12
z = r * rings - ph
rid = floor(z)
f = fract(z)
body = smoothstep(0, 0.2, f) * smoothstep(1, 0.5, f)
hsv(fract(rid * 0.382 + sun * 0.9 + vcpu_kick * 0.3), 1, 1) * body * (0.5 + 0.5 * house + vcpu_kick * 0.6)""", "params": [],
     "inputs": [_in("house", HOUSE, 300, 2300, 0.5, 0.4, kick=0.1), _in("down", DOWN, 0, 60, 0.6), _slow("sun", "sun.sun", -8, 40, 5, 0.4, "elevation"),
                _in("vcpu", VCPU, 0, 100, 0.3, 0.3, kick=0.15)]},
    {"name": "Kaleidoscope live", "code": """# A six-fold mirror of "stained glass": the picture is cut into regions and every region gets a hue far away from its
# neighbours (about 137 degrees round the colour wheel), with dark seams between them. Contrast: full saturation, dark seams.
# It turns with the GPU of Veron's PC, gets finer with the house power, the sun and the CPU of Dima's PC shift all the hues,
# and a spike of Dima's CPU makes the picture flare.
spin = a + vgpu_phase * 0.06 + now * 0.01
m = mirror(spin, 6)
px = r * cos(m * tau)
py = r * sin(m * tau)
zoom = 3 + house * 5
q = noise(px * zoom + now * 0.25 + dcpu_phase * 0.5, py * zoom - now * 0.2)
z = q * 4 + r * 3 + m * 10
region = floor(z)
f = fract(z)
seam = smoothstep(0, 0.14, f) * smoothstep(1, 0.86, f)
hue = fract(region * 0.382 + sun * 0.6 + dcpu * 0.5 + now * 0.02)
hsv(hue, 1, 1) * seam * (0.55 + 0.45 * smoothstep(0.2, 0.8, q)) * (0.85 + dcpu_kick * 0.5)""", "params": [],
     "inputs": [_in("vgpu", VGPU, 0, 80, 0.4), _in("house", HOUSE, 300, 2300, 0.6), _slow("sun", "sun.sun", -8, 40, 5, 0.4, "elevation"),
                _in("dcpu", DCPU, 0, 30, 0.3, 0.3, kick=0.15)]},
    {"name": "Spiral live", "code": """# A three-armed spiral: every arm (and every turn of it) has its own colour, 120 degrees apart on the colour wheel, with dark gaps.
# It winds tighter with the house power, turns with the network traffic, the colours drift with the power of Dima's PC and the sun,
# and it flares when the house power jumps.
arms = 3
twist = 1 + house * 4
z = a * arms + r * twist - down_phase * 0.8 - now * 0.08
arm = floor(z)
f = fract(z)
band = smoothstep(0, 0.25, f) * smoothstep(1, 0.7, f)
hsv(fract(arm * 0.3333 + dpow * 0.8 + sun * 0.4 + now * 0.02), 1, 1) * band * (0.35 + 0.65 * (1 - r * 0.6)) * (0.8 + house_kick * 0.6)""", "params": [],
     "inputs": [_in("house", HOUSE, 300, 2300, 0.6, 0.4, kick=0.1), _in("down", DOWN, 0, 60, 0.6), _in("dpow", DPOW, 100, 450, 0.5),
                _slow("sun", "sun.sun", -8, 40, 5, 0.4, "elevation")]},
    {"name": "Tunnel live", "code": """# Feedback, like MilkDrop: the previous picture is pulled outward and faded, and a fresh ring is born in the middle in rhythm with
# the network traffic. Every ring gets a hue far away from the previous one, so rings of very different colours fly outward.
# When phase B (kettle, oven) jumps, a bright burst flies out of the centre. Needs live mode (stored it runs one warm-up loop).
zoom = 0.97 - down * 0.025
old = prev(x * zoom, (y - 0.5) * zoom + 0.5) * 0.93
beatn = now * 0.6 + down_phase * 0.4
beat = max(sin(tau * beatn), 0) ** 2
ring = smoothstep(0.07, 0, abs(r - 0.1)) * beat
burst = smoothstep(0.35, 0, abs(r - 0.1)) * phb_kick
hue = fract(floor(beatn) * 0.382 + sun + house * 0.3)
old + hsv(hue, 1, 1) * (ring * (1.8 + house * 0.7) + burst)""", "params": [],
     "inputs": [_in("down", DOWN, 0, 60, 0.5), _in("house", HOUSE, 300, 2300, 0.6), _slow("sun", "sun.sun", -8, 40, 5, 0.4, "elevation"),
                _in("phb", PHB, 200, 2200, 0.3, 0.3, kick=0.1)]},
    {"name": "Mandala live", "code": """# Two seven-petal flowers turning in opposite directions (outer: the CPU of Dima's PC, inner: the CPU of Veron's) plus a thin outer ring.
# The three parts use opposite colours (complementary and a third one), so the picture is contrasty. The sun and the loads
# move all the hues together, the inner flower glows with the house power, a spike of Veron's GPU makes the flowers breathe out.
petals = 7
breathe = 1 + 0.2 * vgpu_kick
big = (0.32 + 0.1 * cos(tau * (a * petals + dcpu_phase * 0.15))) * breathe
small = (0.16 + 0.06 * cos(tau * (a * petals - vcpu_phase * 0.2))) * breathe
g1 = smoothstep(0.1, 0, abs(r - big))
g2 = smoothstep(0.08, 0, abs(r - small))
g3 = smoothstep(0.05, 0, abs(r - 0.46 - 0.04 * sin(tau * now * 0.2))) * 0.8
h1 = fract(a * 0.5 + sun * 0.6 + dcpu * 0.5 + now * 0.03)
hsv(h1, 1, 1) * g1 + hsv(fract(h1 + 0.5), 1, 1) * g2 * (0.4 + 0.6 * house) + hsv(fract(h1 + 0.25), 1, 1) * g3""", "params": [],
     "inputs": [_in("dcpu", DCPU, 0, 30, 0.4), _in("vcpu", VCPU, 0, 100, 0.4), _slow("sun", "sun.sun", -8, 40, 5, 0.4, "elevation"),
                _in("house", HOUSE, 300, 2300, 0.6), _in("vgpu", VGPU, 0, 80, 0.3, 0.3, kick=0.15)]},
]
