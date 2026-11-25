"""Formula examples made for a garland that is a tree (the shape is set in the device card; every example says in which mapping it is meant to run).

The mappings (see device.py): "wrap" lays the surface of the tree out as a strip: u is the way round the trunk (0 to 1, the front in the middle,
the seam at the back), v the height (0 at the base, 1 at the tip). "apex" is a round window with the tip in the centre: r is the distance from the
tip (0 to 0.5 at the base), a the angle round the trunk. Every example loops by itself (whole numbers of cycles of t), so it can be stored on the
garland as a movie as well as run as a live scene. On a wall (or with the mapping "as on a wall") they run too, they just do not wrap round anything.
"""

TREE_EXAMPLES = [
    {"name": "Tree spiral", "mapping": "wrap", "code": """# A spiral that winds down the tree, with the colours following the height.
# On the unrolled surface (u round the trunk, v the height) a slanted stripe is a helix on the tree: 2 arms, 3 turns from the tip to the base.
arms = 2
ph = fract(u * arms + v * 3 - t)
band = smoothstep(0, 0.2, ph) * smoothstep(0.6, 0.3, ph)
cpalette("aurora", v * 0.7 + t) * (0.1 + 0.9 * band)""", "params": [], "inputs": []},

    {"name": "Tree lighthouse", "mapping": "apex", "code": """# Two beams of light turn round the trunk, brighter towards the base, a warm glow between them.
# a is the angle round the trunk (-0.5 to 0.5 turns), r the distance from the tip.
beams = 2
ang = fract(a * beams - t)
core = smoothstep(0.22, 0, abs(ang - 0.5))
mix(rgb(1, 0.78, 0.35), rgb(1, 1, 0.95), core) * (0.07 + core * (0.35 + 1.5 * r))""", "params": [], "inputs": []},

    {"name": "Tree baubles", "mapping": "wrap", "code": """# Glowing baubles at fixed places on the surface, each pulsing in its own time and colour.
# The surface is cut into cells; every cell holds one bauble (a hash gives its place, size, colour and phase).
cu = floor(u * 6)
cv = floor(v * 8)
bx = (cu + 0.25 + 0.5 * hash(cu, cv)) / 6
by = (cv + 0.25 + 0.5 * hash(cv, cu + 7)) / 8
du = abs(u - bx)
du = min(du, 1 - du)
dd = sqrt(du ** 2 + (v - by) ** 2)
size = 0.045 + 0.03 * hash(cu, cv + 3)
pulse = 0.5 + 0.5 * sin(tau * (t * 2 + hash(cu + 5, cv)))
cpalette("rainbow", hash(cu + 11, cv + 2)) * exp(-(dd / size) ** 2) * (0.2 + 0.8 * pulse)""", "params": [], "inputs": []},

    {"name": "Garland chase", "mapping": "plane", "code": """# Comets run along the string of lights itself (the number of the LED), so it looks right on any shape of tree and does not depend
# on how well the scan found the positions. The colours are fixed along the string, the comets reveal them.
comets = 5
tail = fract(t - i / n * comets)
cpalette("neon", i / n * 3) * (0.06 + 1.4 * exp(-tail * 7))""", "params": [], "inputs": []},

    {"name": "Star pulse", "mapping": "apex", "code": """# Rings of light leave the tip (where the star will be) and run down to the base.
ring = fract(r * 2.4 - t)
body = smoothstep(0, 0.25, ring) * smoothstep(1, 0.4, ring)
star = exp(-(r / 0.07) ** 2)
cpalette("sunset", ring * 0.6 + 0.1) * body * (0.35 + 0.65 * min(r * 3, 1)) + rgb(1, 0.85, 0.5) * star""", "params": [], "inputs": []},

    {"name": "Tree snow", "mapping": "wrap", "code": """# Snowflakes fall along the surface, brighter on the front of the tree than on the back.
cl = floor(u * 18)
spd = 1 + floor(2 * hash(cl, 1))
fy = fract(hash(cl, 2) - t * spd)
dy = abs(v - fy)
dy = min(dy, 1 - dy)
dx = fract(u * 18) - 0.5
g = exp(-(dy / 0.1) ** 2) * exp(-(dx * 1.6) ** 2)
front = 0.4 + 0.6 * (0.5 + 0.5 * cos(tau * (u - 0.5)))
mix(rgb(0.45, 0.7, 1), rgb(1, 1, 1), g) * (0.08 + 1.2 * g * front)""", "params": [], "inputs": []},

    {"name": "Tree aurora", "mapping": "wrap", "code": """# Soft curtains of colour drift round the tree, closing round the trunk without a seam.
w1 = sin(tau * (u * 2 + t + v * 0.6))
w2 = sin(tau * (u * 3 - t * 2 + v * 0.9))
s = 0.5 + 0.25 * w1 + 0.25 * w2
cpalette("aurora", s * 0.8 + v * 0.3) * (0.15 + 1.1 * s ** 2)""", "params": [], "inputs": []},

    {"name": "Tree sparkle", "mapping": "wrap", "code": """# Golden sparkles, more of them at the base than at the tip, a new set twelve times per loop.
rnd = hash(i, floor(t * 12))
p = 0.05 + 0.1 * (1 - v)
on = step(1 - p, rnd)
mix(rgb(1, 0.7, 0.25), rgb(1, 1, 1), hash(i, 99)) * on + rgb(0.025, 0.012, 0)""", "params": [], "inputs": []},

    {"name": "Tree climb", "mapping": "wrap", "code": """# Bands of colour climb up the tree and sway round it.
climb = v * 1.5 - t + 0.15 * sin(tau * (u * 2 + t))
cpalette("sunset", climb) * (0.5 + 0.5 * sin(tau * climb) ** 2)""", "params": [], "inputs": []},
]
