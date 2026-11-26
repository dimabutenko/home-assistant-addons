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

# signal quality: Wi-Fi / Bluetooth in dBm (about -95 weak .. -40 strong), Zigbee link quality 0..255
WIFI_LIVING = "sensor.livingroom_speaker_livingroom_speaker_wifi_signal"
WIFI_BED = "sensor.bedroom_speaker_bedroom_speaker_wifi_signal"
WIFI_DPC = "sensor.esp_32_dima_pc_wifi_signal_db"
WIFI_VPC = "sensor.esp_32_veron_pc_wifi_signal_db"
WIFI_METERS = "sensor.esp_32_meters_wifi_signal_db"
WIFI_DOOR = "sensor.domofon_wifi_signal"
WIFI_WATER = "sensor.esp32_c6_water_hot_water_rssi"
BLE_PLANT = "sensor.plant_sensor_436a_signal_strength"
ZB_CAB = "sensor.cabinet_radiator_linkquality"
ZB_BIG = "sensor.living_room_radiator_big_linkquality"
ZB_LIV = "sensor.living_room_radiator_linkquality"
ZB_BATH = "sensor.bath_room_radiator_linkquality"
ZB_BED = "sensor.bed_room_radiator_linkquality"


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
    {"name": "Signal towers live", "code": """# Eight towers, one per radio in the house (two speakers, the ESP boards of both PCs, the meters, the door phone, the hot water
# board, the plant sensor). The height and the colour are the signal quality: red and short is weak, green and tall is strong.
# A weak tower flickers like a bad connection, a strong one is steady and sends rings of radio waves over its top.
col = min(floor(u * 8), 7)
xf = fract(u * 8)
q = (living if col == 0 else (bed if col == 1 else (dpc if col == 2 else (vpc if col == 3 else (meters if col == 4 else (door if col == 5 else (water if col == 6 else plant)))))))
top = 0.1 + 0.8 * q
inside = step(0.14, xf) * step(xf, 0.86)
shake = 1 - (1 - q) * 0.85 * noise(col * 7.3, now * 7)
fill = step(y, top) * inside * shake
hue = 0.02 + 0.36 * q
body = hsv(hue, 1, 0.3 + 0.7 * min(y / max(top, 0.1), 1)) * fill
d = dist((xf - 0.5) * w / 8, y, 0, top)
f = fract(d * 7 - now * (0.3 + 0.9 * q))
ring = smoothstep(0, 0.25, f) * smoothstep(0.6, 0.25, f) * sat(1 - d * 3.5) * q * step(top, y)
body + hsv(fract(hue + 0.5), 0.8, 1) * ring * 1.8""", "params": [],
     "inputs": [_slow("living", WIFI_LIVING, -95, -40, 3, 0.7), _slow("bed", WIFI_BED, -95, -40, 3, 0.5), _slow("dpc", WIFI_DPC, -95, -40, 3, 0.5),
                _slow("vpc", WIFI_VPC, -95, -40, 3, 0.5), _slow("meters", WIFI_METERS, -95, -40, 3, 0.3), _slow("door", WIFI_DOOR, -95, -40, 3, 0.2),
                _slow("water", WIFI_WATER, -95, -40, 3, 0.7), _slow("plant", BLE_PLANT, -95, -40, 3, 0.5)]},
    {"name": "Zigbee mesh live", "code": """# Five radiators of the Zigbee mesh are five wave sources, like drops in a pond. The link quality of a radiator sets its colour
# (red is weak, green is strong), how bright and far its waves reach and how fast they run. Where the waves of two radiators meet they
# interfere and mix their colours, so a mesh with very different links makes a rich, uneven picture.
p1x = (0.12 - 0.5) * w
p2x = (0.32 - 0.5) * w
p3x = (0.52 - 0.5) * w
p4x = (0.72 - 0.5) * w
p5x = (0.9 - 0.5) * w
d1 = dist(x, y, p1x, 0.68)
d2 = dist(x, y, p2x, 0.28)
d3 = dist(x, y, p3x, 0.78)
d4 = dist(x, y, p4x, 0.3)
d5 = dist(x, y, p5x, 0.62)
w1 = (0.5 + 0.5 * sin(tau * (d1 * 4 - now * (0.15 + 0.7 * cab)))) ** 3 * (0.2 + 0.8 * cab) * exp(-d1 * 2.2)
w2 = (0.5 + 0.5 * sin(tau * (d2 * 4 - now * (0.15 + 0.7 * big)))) ** 3 * (0.2 + 0.8 * big) * exp(-d2 * 2.2)
w3 = (0.5 + 0.5 * sin(tau * (d3 * 4 - now * (0.15 + 0.7 * liv)))) ** 3 * (0.2 + 0.8 * liv) * exp(-d3 * 2.2)
w4 = (0.5 + 0.5 * sin(tau * (d4 * 4 - now * (0.15 + 0.7 * bath)))) ** 3 * (0.2 + 0.8 * bath) * exp(-d4 * 2.2)
w5 = (0.5 + 0.5 * sin(tau * (d5 * 4 - now * (0.15 + 0.7 * bed)))) ** 3 * (0.2 + 0.8 * bed) * exp(-d5 * 2.2)
waves = hsv(cab * 0.36, 1, 1) * w1 + hsv(big * 0.36, 1, 1) * w2 + hsv(liv * 0.36, 1, 1) * w3 + hsv(bath * 0.36, 1, 1) * w4 + hsv(bed * 0.36, 1, 1) * w5
core = gray(1) * (exp(-(d1 * 14) ** 2) + exp(-(d2 * 14) ** 2) + exp(-(d3 * 14) ** 2) + exp(-(d4 * 14) ** 2) + exp(-(d5 * 14) ** 2))
waves * 1.6 + core * 0.8""", "params": [],
     "inputs": [_slow("cab", ZB_CAB, 40, 255, 3, 0.5), _slow("big", ZB_BIG, 40, 255, 3, 0.2), _slow("liv", ZB_LIV, 40, 255, 3, 0.8),
                _slow("bath", ZB_BATH, 40, 255, 3, 0.4), _slow("bed", ZB_BED, 40, 255, 3, 0.3)]},
    {"name": "Signal stars live", "code": """# A night sky with eight stars, one per radio in the house. A strong signal is a big, steady, blue-white star; a weak one is a small
# red star that flickers hard, like a bad connection. The sky itself drifts slowly in deep blue.
q1 = living
q2 = bed
q3 = dpc
q4 = vpc
q5 = meters
q6 = door
q7 = water
q8 = plant
s1 = exp(-(dist(x, y, (0.1 - 0.5) * w, 0.8) / (0.025 + 0.05 * q1)) ** 2) * (1 - (1 - q1) * 0.9 * noise(1.1, now * 5))
s2 = exp(-(dist(x, y, (0.25 - 0.5) * w, 0.35) / (0.025 + 0.05 * q2)) ** 2) * (1 - (1 - q2) * 0.9 * noise(2.2, now * 5))
s3 = exp(-(dist(x, y, (0.38 - 0.5) * w, 0.7) / (0.025 + 0.05 * q3)) ** 2) * (1 - (1 - q3) * 0.9 * noise(3.3, now * 5))
s4 = exp(-(dist(x, y, (0.5 - 0.5) * w, 0.25) / (0.025 + 0.05 * q4)) ** 2) * (1 - (1 - q4) * 0.9 * noise(4.4, now * 5))
s5 = exp(-(dist(x, y, (0.62 - 0.5) * w, 0.85) / (0.025 + 0.05 * q5)) ** 2) * (1 - (1 - q5) * 0.9 * noise(5.5, now * 5))
s6 = exp(-(dist(x, y, (0.74 - 0.5) * w, 0.45) / (0.025 + 0.05 * q6)) ** 2) * (1 - (1 - q6) * 0.9 * noise(6.6, now * 5))
s7 = exp(-(dist(x, y, (0.86 - 0.5) * w, 0.75) / (0.025 + 0.05 * q7)) ** 2) * (1 - (1 - q7) * 0.9 * noise(7.7, now * 5))
s8 = exp(-(dist(x, y, (0.93 - 0.5) * w, 0.3) / (0.025 + 0.05 * q8)) ** 2) * (1 - (1 - q8) * 0.9 * noise(8.8, now * 5))
sky = hsv(0.62, 0.9, 0.04 + 0.1 * noise(x * 3 + now * 0.03, y * 3))
stars = hsv(q1 * 0.6, 1 - 0.55 * q1, 1) * s1 + hsv(q2 * 0.6, 1 - 0.55 * q2, 1) * s2 + hsv(q3 * 0.6, 1 - 0.55 * q3, 1) * s3 + hsv(q4 * 0.6, 1 - 0.55 * q4, 1) * s4
stars + hsv(q5 * 0.6, 1 - 0.55 * q5, 1) * s5 + hsv(q6 * 0.6, 1 - 0.55 * q6, 1) * s6 + hsv(q7 * 0.6, 1 - 0.55 * q7, 1) * s7 + hsv(q8 * 0.6, 1 - 0.55 * q8, 1) * s8 + sky""", "params": [],
     "inputs": [_slow("living", WIFI_LIVING, -95, -40, 3, 0.7), _slow("bed", WIFI_BED, -95, -40, 3, 0.5), _slow("dpc", WIFI_DPC, -95, -40, 3, 0.5),
                _slow("vpc", WIFI_VPC, -95, -40, 3, 0.5), _slow("meters", WIFI_METERS, -95, -40, 3, 0.3), _slow("door", WIFI_DOOR, -95, -40, 3, 0.2),
                _slow("water", WIFI_WATER, -95, -40, 3, 0.7), _slow("plant", BLE_PLANT, -95, -40, 3, 0.5)]},
    # ---- in the manner of the stored effects that look good on the tree: every LED on its own (Twinkle, Slow stars, Glitter) or stripes / streaks /
    # strands drawn on the front view (Candy stripes, Rain, Double helix). Nothing turns round a centre, so they suit a wall and a tree alike.
    {"name": "Live twinkle", "code": """# Twinkle with a pulse from the home: every LED blinks on its own (warm white). The house power sets how fast they blink and how many LEDs take part,
# the sun cools the colour by day (warm at night), a jump of the load of Dima's PC makes a burst of quick blinks over the whole tree.
ph = hash(i, 1)
fr = 1 + floor(hash(i, 2) * 3)
tt = now * 0.12 + house_phase * 0.4
alive = step(hash(i, 4), 0.45 + 0.55 * house)
s = (0.5 + 0.5 * sin(tau * (fr * tt + ph))) ** 5
c = hash(i, 3)
base = mix(palette("warm white", c), palette("ice", c), sun * 0.7)
burst = dcpu_kick * hash(i, floor(now * 7)) ** 2
base * (s * alive + burst)""", "params": [],
     "inputs": [_in("house", HOUSE, 300, 2300, 0.6), _slow("sun", "sun.sun", -8, 40, 5, 0.2, "elevation"), _in("dcpu", DCPU, 0, 30, 0.4, 0.3, kick=0.12)]},
    {"name": "Live stars", "code": """# Slow stars: a few LEDs pulse softly in starlight colours, more of them the more power the house draws. A jump of the load of Dima's PC sends
# a shooting star along the string of lights (it runs along the numbers of the LEDs, so it follows the wire round the tree).
ph = hash(i, 22)
fr = 1 + floor(hash(i, 24) * 2)
tt = now * 0.07 + house_phase * 0.15
star = step(hash(i, 21), 0.1 + 0.45 * house)
b = (0.5 + 0.5 * sin(tau * (fr * tt + ph))) ** 3
field = palette("starlight", hash(i, 23)) * b * star
d = hash(dcpu_count, 3) * n * 0.4 + dcpu_age * 120 - i
comet = exp(-d / 16) * step(0, d) * step(dcpu_age, 3.5)
field + rgb(0.75, 0.9, 1) * comet""", "params": [],
     "inputs": [_in("house", HOUSE, 300, 2300, 0.6), _in("dcpu", DCPU, 0, 30, 0.4, 0.3, kick=0.12)]},
    {"name": "Live glitter", "code": """# Glitter: LEDs flash sharply in neon colours, driven by the network. The more data comes down, the faster they flash; the upload decides how
# many LEDs take part. A jump of the house power flashes the whole tree for a moment.
on = step(hash(i, 41), 0.35 + 0.6 * up)
uu = fract(down_phase * 0.8 + now * 0.45 + hash(i, 42))
b = max(0, 1 - uu / 0.22) ** 2
c = cpalette("neon", hash(i, 43))
c * 2.6 * (on * b + house_kick * 0.6 * step(0.55, hash(i, floor(now * 9))))""", "params": [],
     "inputs": [_in("down", DOWN, 0, 60, 0.5), _in("up", UP, 0, 40, 0.5), _in("house", HOUSE, 300, 2300, 0.5, 0.4, kick=0.1)]},
    {"name": "Live candy", "code": """# Candy stripes that follow the wind: the stripes lie across the wind (the bearing of the wind from the weather), run with its speed and are
# narrower when the house draws more power; a jump of the power makes them flash. Two colours of the candy palette.
ang = wb * tau
k = 3 + 9 * house
s = fract((x * cos(ang) + y * sin(ang)) * k * 0.5 + ws_phase * 1.2 + now * 0.04)
w2 = smoothstep(0.42, 0.5, s) - smoothstep(0.92, 1, s)
mix(palette("candy", 0), palette("candy", 1), w2) * (0.85 + 0.35 * house_kick)""", "params": [],
     "inputs": [_slow("wb", "weather.forecast_home_2", 0, 360, 4, 0.18, "wind_bearing"), _slow("ws", "weather.forecast_home_2", 0, 30, 3, 0.15, "wind_speed"),
                _in("house", HOUSE, 300, 2300, 0.6, 0.4, kick=0.1)]},
    {"name": "Live rain", "code": """# Rain made of network traffic: the more data comes down, the denser the rain; the faster the upload, the faster it falls. Streaks in ice colours
# fall in columns across the tree; a jump of the house power is a flash of lightning.
lane = floor(u * 20)
dens = 1 + 2 * down
fall = now * 0.5 + up_phase * 1.5
uu = fract(y * dens + fall + hash(lane, 61))
b = max(0, 1 - uu / 0.5) ** 1.5
palette("ice", 0.55 + 0.45 * b) * b * (1.4 + 0.8 * down) + rgb(0.45, 0.6, 1) * house_kick * 0.5""", "params": [],
     "inputs": [_in("down", DOWN, 0, 60, 0.5), _in("up", UP, 0, 40, 0.5), _in("house", HOUSE, 300, 2300, 0.5, 0.4, kick=0.1)]},
    {"name": "Live helix", "code": """# A double helix: two strands twist round each other up the tree. The house power sets how many turns it has, the load of Dima's PC spins it,
# a jump of that load makes the strands fatter for a moment.
turns = 1 + 1.5 * house
ph = tau * (y * turns - dcpu_phase * 0.25 - now * 0.08)
xs = 0.5 + 0.38 * sin(ph)
wd = 0.1 + 0.1 * dcpu_kick
depth = cos(ph)
ba = exp(-((u - xs) ** 2) / (2 * wd * wd)) * (0.55 + 0.45 * depth)
bb = exp(-((u - (1 - xs)) ** 2) / (2 * wd * wd)) * (0.55 - 0.45 * depth)
palette("neon", 0.15) * ba if ba >= bb else palette("neon", 0.85) * bb""", "params": [],
     "inputs": [_in("house", HOUSE, 300, 2300, 0.6), _in("dcpu", DCPU, 0, 30, 0.4, 0.3, kick=0.12)]},
    # ---- round two: spirals, ribbons and candy; the whole tree is lit (no dark gaps). The far side of a tree is dimmed by the garland itself.
    {"name": 'Live triple helix', "mapping": 'plane', "code": """# Three strands braided round each other, the strand in front the brightest, on a soft colour that fills the whole tree.
# The house power sets the number of turns, the load of Dima's PC the spin.
turns = 0.8 + 1.4 * house
ph = tau * (y * turns - dcpu_phase * 0.2 - now * 0.06)
wd = 0.1 + 0.07 * dcpu_kick
x0 = 0.5 + 0.36 * sin(ph)
x1 = 0.5 + 0.36 * sin(ph + 2.0944)
x2 = 0.5 + 0.36 * sin(ph + 4.1888)
g0 = exp(-((u - x0) ** 2) / (2 * wd * wd)) * (0.55 + 0.45 * cos(ph))
g1 = exp(-((u - x1) ** 2) / (2 * wd * wd)) * (0.55 + 0.45 * cos(ph + 2.0944))
g2 = exp(-((u - x2) ** 2) / (2 * wd * wd)) * (0.55 + 0.45 * cos(ph + 4.1888))
w0 = step(g1, g0) * step(g2, g0)
w1 = (1 - w0) * step(g2, g1)
w2 = 1 - w0 - w1
gm = max(g0, max(g1, g2))
bg = palette("aurora", 0.55 + 0.3 * sin(tau * (v * 0.7 + now * 0.01))) * 0.3
rgb(1, 0.15, 0.3) * g0 * w0 + rgb(0.1, 0.9, 0.4) * g1 * w1 + rgb(0.2, 0.4, 1) * g2 * w2 + bg * (1 - min(gm * 1.5, 1))""", "params": [],
     "inputs": [{"name": "house", "entity": "sensor.main_energy_sensor_power", "attribute": "", "min": 300, "max": 2300, "smooth": 0.6, "default": 0.4, "auto": True, "kick": 0.1}, {"name": "dcpu", "entity": "sensor.dima_pc_satelite_cpuload", "attribute": "", "min": 0, "max": 30, "smooth": 0.4, "default": 0.3, "auto": True, "kick": 0.12}]},
    {"name": 'Live DNA ladder', "mapping": 'plane', "code": """# A double helix with rungs between the strands, on a soft two-colour glow that fills the tree. House power: turns, PC load: spin.
turns = 1 + 1.2 * house
ph = tau * (y * turns - dcpu_phase * 0.2 - now * 0.06)
xs = 0.5 + 0.36 * sin(ph)
wd = 0.09
ba = exp(-((u - xs) ** 2) / (2 * wd * wd)) * (0.55 + 0.45 * cos(ph))
bb = exp(-((u - (1 - xs)) ** 2) / (2 * wd * wd)) * (0.55 - 0.45 * cos(ph))
rung = smoothstep(0.3, 0.0, abs(cos(ph))) * step(abs(u - 0.5), 0.4 * abs(sin(ph)))
strand = palette("neon", 0.15) * ba if ba >= bb else palette("neon", 0.85) * bb
bg = mix(palette("neon", 0.1), palette("neon", 0.9), v) * 0.32
strand + rgb(1, 1, 1) * rung * 0.8 + bg * (1 - min(max(ba, bb) * 1.5 + rung, 1))""", "params": [],
     "inputs": [{"name": "house", "entity": "sensor.main_energy_sensor_power", "attribute": "", "min": 300, "max": 2300, "smooth": 0.6, "default": 0.4, "auto": True, "kick": 0.1}, {"name": "dcpu", "entity": "sensor.dima_pc_satelite_cpuload", "attribute": "", "min": 0, "max": 30, "smooth": 0.4, "default": 0.3, "auto": True, "kick": 0.12}]},
    {"name": 'Live ribbons', "mapping": 'plane', "code": """# Three ribbons of light sway up the tree and cross each other, where they meet the colours mix, on a deep colour that fills the tree.
# The speed follows the download.
a1 = 0.5 + 0.34 * sin(tau * (y * 0.9 - now * 0.05 - down_phase * 0.1))
a2 = 0.5 + 0.34 * sin(tau * (y * 1.3 - now * 0.07 - down_phase * 0.12) + 2)
a3 = 0.5 + 0.34 * sin(tau * (y * 1.7 + now * 0.04 + down_phase * 0.08) + 4)
wd = 0.1 + 0.05 * up
bg = palette("aurora", 0.3 + 0.25 * sin(tau * (v + now * 0.02))) * 0.3
palette("aurora", 0.1) * exp(-((u - a1) ** 2) / (2 * wd * wd)) + palette("aurora", 0.5) * exp(-((u - a2) ** 2) / (2 * wd * wd)) + palette("aurora", 0.9) * exp(-((u - a3) ** 2) / (2 * wd * wd)) + bg""", "params": [],
     "inputs": [{"name": "down", "entity": "sensor.keenetic_titan_wifistation_internal_downlink_speed", "attribute": "", "min": 0, "max": 60, "smooth": 0.5, "default": 0.4, "auto": True, "kick": 0.12}, {"name": "up", "entity": "sensor.keenetic_titan_wifistation_internal_uplink_speed", "attribute": "", "min": 0, "max": 40, "smooth": 0.5, "default": 0.4, "auto": True, "kick": 0.12}]},
    {"name": 'Live wavy candy', "mapping": 'plane', "code": """# Candy stripes that wave like a flag: the wind speed sets how strongly they sway, the wind bearing which way they lean.
ang = wb * tau
sway = 0.04 + 0.2 * ws
c = (x * cos(ang) + y * sin(ang)) * 4 + sway * 4 * sin(tau * (y * 2 + now * 0.1)) + ws_phase * 1.2 + now * 0.05
s = fract(c)
w2 = smoothstep(0.42, 0.5, s) - smoothstep(0.92, 1, s)
mix(palette("candy", 0), palette("candy", 1), w2)""", "params": [],
     "inputs": [{"name": "wb", "entity": "weather.forecast_home_2", "attribute": "wind_bearing", "min": 0, "max": 360, "smooth": 4, "default": 0.18, "auto": False, "kick": 0.12}, {"name": "ws", "entity": "weather.forecast_home_2", "attribute": "wind_speed", "min": 0, "max": 30, "smooth": 3, "default": 0.15, "auto": False, "kick": 0.12}]},
    {"name": 'Live frosted candy', "mapping": 'plane', "code": """# Candy stripes in white and ice blue with glitter sparkling in the stripes. The wind turns the stripes and drives them.
ang = wb * tau
s = fract((x * cos(ang) + y * sin(ang)) * 4 + ws_phase * 1.2 + now * 0.04)
w2 = smoothstep(0.42, 0.5, s) - smoothstep(0.92, 1, s)
sparkle = step(0.9, hash(i, floor(now * 6)))
mix(rgb(0.05, 0.2, 0.55), rgb(0.85, 0.95, 1), w2) * (0.85 + 0.15 * hash(i, 5)) + rgb(1, 1, 1) * sparkle * (0.4 + 0.6 * w2)""", "params": [],
     "inputs": [{"name": "wb", "entity": "weather.forecast_home_2", "attribute": "wind_bearing", "min": 0, "max": 360, "smooth": 4, "default": 0.18, "auto": False, "kick": 0.12}, {"name": "ws", "entity": "weather.forecast_home_2", "attribute": "wind_speed", "min": 0, "max": 30, "smooth": 3, "default": 0.15, "auto": False, "kick": 0.12}]},
    {"name": 'Live spiral candy', "mapping": 'wrap', "code": """# Candy stripes that wind round the tree like a ribbon round a candy cane (on a wall they are just slanted stripes). The house power sets
# how steep the spiral is, the wind drives it.
s = fract(u * 2 + v * (1.5 + 2 * house) - now * 0.05 - ws_phase * 1.0)
w2 = smoothstep(0.42, 0.5, s) - smoothstep(0.92, 1, s)
mix(palette("candy", 0), palette("candy", 1), w2)""", "params": [],
     "inputs": [{"name": "house", "entity": "sensor.main_energy_sensor_power", "attribute": "", "min": 300, "max": 2300, "smooth": 0.6, "default": 0.4, "auto": True, "kick": 0.1}, {"name": "ws", "entity": "weather.forecast_home_2", "attribute": "wind_speed", "min": 0, "max": 30, "smooth": 3, "default": 0.15, "auto": False, "kick": 0.12}]},
    {"name": 'Live christmas spiral', "mapping": 'wrap', "code": """# Three wide spirals, red, green and white, wind up the tree side by side and cover all of it. The load of Dima's PC drives them.
s = fract(u * 3 + v * 2.2 - now * 0.05 - dcpu_phase * 0.3)
f = fract(s * 3)
edge = smoothstep(0, 0.12, f) * smoothstep(1, 0.88, f)
i0 = 1 - step(0.3333, s)
i2 = step(0.6667, s)
i1 = 1 - i0 - i2
(rgb(0.95, 0.04, 0.06) * i0 + rgb(0.04, 0.8, 0.2) * i1 + rgb(1, 0.95, 0.85) * i2) * (0.35 + 0.65 * edge)""", "params": [],
     "inputs": [{"name": "dcpu", "entity": "sensor.dima_pc_satelite_cpuload", "attribute": "", "min": 0, "max": 30, "smooth": 0.4, "default": 0.3, "auto": True, "kick": 0.12}]},
    {"name": 'Live rainbow spiral', "mapping": 'wrap', "code": """# A rainbow that winds round the tree. The speed follows the network.
hue = fract(u * 2 + v * 1.5 - now * 0.04 - down_phase * 0.1)
hsv(hue, 0.95, 1)""", "params": [],
     "inputs": [{"name": "down", "entity": "sensor.keenetic_titan_wifistation_internal_downlink_speed", "attribute": "", "min": 0, "max": 60, "smooth": 0.5, "default": 0.4, "auto": True, "kick": 0.12}]},
    {"name": 'Live twisted candy', "mapping": 'wrap', "code": """# Candy stripes that twist: the stripes round the tree wobble up and down as they go round, and the wobble grows with the wind.
c = v * 4 + 0.4 * (0.4 + ws) * sin(tau * (u * 2 + now * 0.06)) + now * 0.06 + ws_phase * 0.8
s = fract(c)
w2 = smoothstep(0.42, 0.5, s) - smoothstep(0.92, 1, s)
mix(palette("candy", 0), palette("candy", 1), w2)""", "params": [],
     "inputs": [{"name": "ws", "entity": "weather.forecast_home_2", "attribute": "wind_speed", "min": 0, "max": 30, "smooth": 3, "default": 0.15, "auto": False, "kick": 0.12}]},
]
