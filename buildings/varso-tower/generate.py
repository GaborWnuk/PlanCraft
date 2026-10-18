"""Regenerate the Varso Tower model (building.yaml) from the measurements in sources.yaml.

Run from the repository root: python buildings\\varso-tower\\generate.py
Then: python -m building compile varso-tower (from tools\\building).

Plan coordinates are metres on the registered Foster + Partners plans (see trace.py): x grows
east and z south from the north-west corner of the tower, and cell (i, j) is the square metre
[i, i+1) x [j, j+1). Heights are whole metres above the plaza; a span lo..hi fills layers
lo..hi-1. Everything below is rasterised here, on the same cell-centre rule the compiler uses,
and written as grouped ``cells`` parts, so the facade grid, cores and fittings are cell-exact.
"""

import math
from collections import defaultdict, deque
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent
PARTS = []
PAINT = defaultdict(set)

# Footprints, metres (plan drawings 2, 4, 8 and 13).
BASE = [(0, 0), (37, 0), (55, 27), (55, 29), (48, 29), (48, 37),
        (55, 37), (55, 45), (20, 45), (17, 43), (0, 18), (0, 16), (6, 16), (6, 8), (0, 8)]
MID = [(6, 8), (34, 8), (47, 29), (48, 29), (48, 37),
       (55, 37), (55, 45), (20, 45), (17, 43), (0, 18), (0, 16), (6, 16)]
RIM = [(0, 16), (9, 16), (21, 35), (21, 36), (55, 36), (55, 45), (20, 45), (17, 43), (0, 18)]
URBAN = [(-16.5, 8), (6, 8), (6, 16), (0, 16), (0, 18), (11.9, 35.5), (-8, 36)]
GARDEN_PIT = [(18.5, 13.9), (31.3, 13.9), (39.2, 27.3), (26.5, 27.3)]

# Level 1 lobby, level 2 mezzanine, 3-43 offices to the 177 m setback, 44-49 to the 205 m
# garden, 50-53 to the 230 m viewing terrace (interpolated between the published heights).
FLOORS = [0, 7] + [14 + (n - 3) * 163 / 40 for n in range(3, 44)]
FLOORS += [177 + (n - 43) * 28 / 6 for n in range(44, 50)]
FLOORS += [205 + (n - 49) * 25 / 4 for n in range(50, 54)]
H = {n: round(v) for n, v in enumerate(FLOORS, 1)}

# The core is drawn in a frame rotated to the north-east facade diagonal: (s, t) -> C1 + t*A + s*B.
C1 = (16.8, 21.8)
A = (0.8321, -0.5547)
B = (0.5547, 0.8321)
TRI_A = [(13.3, 8.0), (29.0, 8.0), (14.6, 17.9), (13.3, 16.1)]
TRI_D = [(41.0, 26.9), (41.7, 27.6), (41.7, 37.1), (26.2, 37.1)]
OPEN = {"LAB", "LCD", "corrA", "corrB"}
LIFT_FRONT = {"A": (-4.8, 0), "B": (-4.8, 0), "C": (13.2, 17.7), "D": (13.2, 17.7)}

# Perimeter columns, about a metre inside the glass on 8.1 m bays (plans 2 and 4).
COLUMNS_BASE = [(4.9, 1.6), (13, 1.6), (21.1, 1.6), (29.1, 1.6), (37.3, 1.6),
                (42.2, 8.8), (46.5, 15.6), (50.8, 22.6),
                (26.8, 43.5), (35.0, 43.5), (43.1, 43.5), (51.2, 43.5),
                (4.8, 22.7), (8.9, 29.4), (13.3, 36.3), (16.5, 42.5)]
COLUMNS_MID = [(13, 9.4), (21.1, 9.4), (29.1, 9.4), (36.4, 12.6), (40.6, 19.4), (44.8, 26.2),
               (26.8, 43.5), (35.0, 43.5), (43.1, 43.5), (51.2, 43.5),
               (4.8, 22.7), (8.9, 29.4), (13.3, 36.3)]

N4 = [(1, 0), (-1, 0), (0, 1), (0, -1)]
N8 = N4 + [(1, 1), (1, -1), (-1, 1), (-1, -1)]
CARDINAL = {(1, 0): "east", (-1, 0): "west", (0, 1): "south", (0, -1): "north"}


# ---------------------------------------------------------------- output


def cm(value):
    return round(value * 100)


def part(kind, **kwargs):
    PARTS.append({"type": kind, **kwargs})


def slab(points, lo, hi, material, priority=10, name=""):
    part("box", polygon=[[cm(x), cm(z)] for x, z in points], bottom=cm(lo), top=cm(hi),
         material=material, priority=priority, name=name)


def room(name, points, floor, ceiling):
    part("room", name=name, polygon=[[cm(x), cm(z)] for x, z in points],
         floor=cm(floor), ceiling=cm(ceiling), camera=False)


def paint(cells, lo, hi, material, priority=60):
    if cells and hi > lo:
        PAINT[(priority, material, lo, hi)].update(cells)


def put(cell, y, material, priority=60):
    paint({cell}, y, y + 1, material, priority)


def flush():
    for (priority, material, lo, hi), cells in sorted(PAINT.items(), key=lambda kv: (kv[0][0], kv[0][2], kv[0][3], kv[0][1])):
        part("cells", material=material, priority=priority, bottom=cm(lo), top=cm(hi),
             cells=[[cm(i + 0.5), cm(j + 0.5)] for i, j in sorted(cells)])


# ---------------------------------------------------------------- raster geometry


def inside(poly, x, z):
    """Even-odd test, the same rule as the compiler's polygon_mask."""
    result = False
    for (x1, z1), (x2, z2) in zip(poly, poly[1:] + poly[:1]):
        if z1 != z2 and (z1 > z) != (z2 > z) and x < x1 + (z - z1) * (x2 - x1) / (z2 - z1):
            result = not result
    return result


def cells_of(poly):
    xs, zs = [p[0] for p in poly], [p[1] for p in poly]
    return {(i, j) for i in range(math.floor(min(xs)), math.ceil(max(xs)))
            for j in range(math.floor(min(zs)), math.ceil(max(zs))) if inside(poly, i + 0.5, j + 0.5)}


def rim(cells):
    """Cells with an 8-neighbour outside: a 4-connected ring, so diagonal glass has no gaps."""
    return {c for c in cells if any((c[0] + dx, c[1] + dz) not in cells for dx, dz in N8)}


def rect(x0, z0, x1, z1):
    return {(i, j) for i in range(x0, x1) for j in range(z0, z1)}


def disc(cx, cz, r, r_in=-1.0):
    return {(i, j) for i in range(math.floor(cx - r) - 1, math.ceil(cx + r) + 1)
            for j in range(math.floor(cz - r) - 1, math.ceil(cz + r) + 1)
            if r_in < math.hypot(i + 0.5 - cx, j + 0.5 - cz) <= r}


def strip(a, b, width):
    """Cells whose centres lie within width/2 of segment a-b."""
    (ax, az), (bx, bz) = a, b
    length = math.dist(a, b)
    ux, uz = (bx - ax) / length, (bz - az) / length
    out = set()
    for i in range(math.floor(min(ax, bx) - width), math.ceil(max(ax, bx) + width)):
        for j in range(math.floor(min(az, bz) - width), math.ceil(max(az, bz) + width)):
            dx, dz = i + 0.5 - ax, j + 0.5 - az
            along = dx * ux + dz * uz
            if -0.01 <= along <= length + 0.01 and abs(dx * uz - dz * ux) <= width / 2:
                out.add((i, j))
    return out


def near(cells, others):
    return {c for c in cells if any((c[0] + dx, c[1] + dz) in others for dx, dz in N8)}


def st(x, z):
    dx, dz = x - C1[0], z - C1[1]
    return dx * B[0] + dz * B[1], dx * A[0] + dz * A[1]


def stc(cell):
    return st(cell[0] + 0.5, cell[1] + 0.5)


def floors_between(lo, hi):
    return [h for n, h in H.items() if lo < h <= hi]


# ---------------------------------------------------------------- facade


def nearest_edge(poly, x, z):
    best = None
    for a, b in zip(poly, poly[1:] + poly[:1]):
        length = math.dist(a, b)
        if length == 0:
            continue
        ux, uz = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        d = min(max((x - a[0]) * ux + (z - a[1]) * uz, 0), length)
        gap = math.hypot(a[0] + ux * d - x, a[1] + uz * d - z)
        if best is None or gap < best[0]:
            best = (gap, d, length)
    return best


def facade_pattern(poly, panel=3.0):
    """Ring cells split into corners, mullions (one per glass panel edge) and glass.

    The real panels are 2.7 m; every edge is divided evenly into panels of about three cells,
    so the grid reads regularly instead of alternating three- and two-cell panes.
    """
    ring = rim(cells_of(poly))
    corner, mullion, glass = set(), set(), set()
    for c in ring:
        x, z = c[0] + 0.5, c[1] + 0.5
        if min(math.dist((x, z), p) for p in poly) < 1.0:
            corner.add(c)
            continue
        _, d, length = nearest_edge(poly, x, z)
        step = length / max(1, round(length / panel))
        (mullion if abs(d - round(d / step) * step) < 0.55 else glass).add(c)
    return ring, corner, mullion, glass


def facade(poly, lo, hi, style="tower", skip=frozenset()):
    ring, corner, mullion, glass = facade_pattern(poly)
    corner, mullion, glass = corner - skip, mullion - skip, glass - skip
    if style == "tower":
        paint(glass, lo, hi, "glass", 30)
        for h in floors_between(lo, hi):
            paint(glass, h - 1, h, "floor_line", 31)
        paint(mullion, lo, hi, "mullion", 32)
        paint(corner, lo, hi, "fin", 33)
    else:  # the double-height lobby: clear glass on black steel, a transom at the mezzanine
        paint(glass, lo, hi, "lobby_glass", 30)
        for y in (lo + 6, hi - 1):
            paint(glass | mullion, y, y + 1, "lobby_mullion", 31)
        paint(mullion, lo, hi, "lobby_mullion", 32)
        paint(corner, lo, hi, "lobby_frame", 33)
    return ring, corner, mullion, glass


# ---------------------------------------------------------------- core


def pick(value, cuts, names):
    for cut, name in zip(cuts, names):
        if value < cut:
            return name
    return names[-1]


def core_region(x, z, zone):
    """The core plan of each zone (plans 2, 4, 5, 7, 8) as regions of the rotated frame."""
    s, t = st(x, z)
    if zone != "high" and inside(TRI_A, x, z):
        return pick(t, [2.8, 6.0, 9.3, 12.8], ["Asvc", "A1", "A2", "A3", "Asvc"]) if s >= -7.6 else "Asvc"
    if inside(TRI_D, x, z):
        return pick(t, [4.0, 7.6, 11.4, 15.2], ["Dsvc", "D1", "D2", "D3", "Dsvc"]) if s < 20.5 else "Dsvc"
    if not 0 <= t < 17.5:
        return None
    if -4.8 <= s < 0:
        return "LAB" if zone == "typical" else None
    if 0 <= s < 3.25:
        return None if zone == "high" else pick(t, [1, 4, 7, 10, 13], ["Bsvc", "B1", "B2", "B3", "B4", "Bsvc"])
    if 3.25 <= s < 9.5:
        return pick(t, [4.8, 12.4], ["corrA", "S", "corrB"])
    if 9.5 <= s < 13.2:
        return pick(t, [2.7, 6.3, 9.9, 13.6, 17.2], ["Csvc", "C1", "C2", "C3", "C4", "Csvc"])
    if 13.2 <= s < 17.7:
        return None if zone == "ground" else "LCD"
    return None


DELTA = 0.69  # half the width of a 4-connected digital line across the core's rotated axes
PROBES = [(DELTA * A[0], DELTA * A[1]), (DELTA * B[0], DELTA * B[1]), (0.5, 0.0), (0.0, 0.5)]


def core_mouth(label, x, z):
    """Open lobbies and corridors are open at their ends, where they meet the office floor."""
    s, t = st(x, z)
    return (label in ("LAB", "LCD") or 5.5 <= s < 7.5) and not 1.0 <= t < 16.5


def core_layout(zone):
    """Regions, walls and voids. A cell is wall where the region changes across it along a core
    axis (or along x or z, for the triangles), so every wall is an unbroken 4-connected line
    one block thick, whatever the rotation."""
    region, walls = {}, set()
    for i in range(8, 46):
        for j in range(4, 42):
            x, z = i + 0.5, j + 0.5
            r = core_region(x, z, zone)
            if r:
                region[(i, j)] = r
            for dx, dz in PROBES:
                a, b = core_region(x - dx, z - dz, zone), core_region(x + dx, z + dz, zone)
                if a == b or (a in OPEN and b in OPEN):
                    continue
                if (a is None and b in OPEN and core_mouth(b, x, z)) or (b is None and a in OPEN and core_mouth(a, x, z)):
                    continue
                walls.add((i, j))
                region.setdefault((i, j), "wall")
                break
    voids = defaultdict(set)
    for c, r in region.items():
        if c not in walls and r not in OPEN:
            voids[r].add(c)
    return region, walls, voids


def lift_doors(region, walls, voids, label, front):
    """The middle wall cell between a lift and its lobby, with the way it opens."""
    lo, hi = front
    found = []
    for c in walls:
        for d in N4:
            back, ahead = (c[0] - d[0], c[1] - d[1]), (c[0] + d[0], c[1] + d[1])
            if back in voids[label] and ahead not in walls and region.get(ahead) in OPEN | {None} \
                    and lo <= stc(ahead)[0] < hi:
                found.append((stc(c)[1], c, d))
    if not found:
        return None
    found.sort()
    _, cell, d = found[len(found) // 2]
    return cell, CARDINAL[d]


def door(cell, y, facing, material="minecraft:iron_door", priority=46, hinge="left"):
    props = f"facing={facing},hinge={hinge},open=false,powered=false"
    put(cell, y, f"{material}[{props},half=lower]", priority)
    put(cell, y + 1, f"{material}[{props},half=upper]", priority)


STAIR = "minecraft:polished_andesite_stairs"


def ring_of(cells):
    """The cells round the largest axis-aligned rectangle in a shaft, in walking order, and its well."""
    best = None
    xs, zs = sorted({c[0] for c in cells}), sorted({c[1] for c in cells})
    for x0 in xs:
        for z0 in zs:
            for x1 in (x for x in xs if x >= x0 + 2):
                for z1 in (z for z in zs if z >= z0 + 2):
                    box = rect(x0, z0, x1 + 1, z1 + 1)
                    if box <= cells and (best is None or (len(box), -x0, -z0) > best[0]):
                        best = ((len(box), -x0, -z0), (x0, z0, x1, z1))
    x0, z0, x1, z1 = best[1]
    ring = ([(x, z0) for x in range(x0, x1)] + [(x1, z) for z in range(z0, z1)]
            + [(x, z1) for x in range(x1, x0, -1)] + [(x0, z) for z in range(z1, z0, -1)])
    return ring, rect(x0 + 1, z0 + 1, x1, z1)


def flights(ring, entry, floors, landing, priority):
    """A stair winding round a ring of cells that arrives back at the entry cell exactly on each
    floor: one step up per cell, and the rest of the last lap is a landing at the next floor."""
    n = len(ring)
    k = ring.index(entry)
    order = ring[k:] + ring[:k]
    supports = defaultdict(list)

    def lay(cell, y, state):
        put(cell, y, state, priority)
        supports[cell].append(y)

    for h, up in zip(floors, floors[1:]):
        rise = up - h
        moves = -(-(rise + 1) // n) * n
        # A flight that fits one lap climbs first and lands after; a longer one spreads its steps
        # over the laps so each cell keeps headroom below the step above it.
        feet = ([h + min(i, rise) for i in range(moves + 1)] if moves == n else
                [h + round(rise * i / moves) for i in range(moves + 1)])
        lay(order[0], h - 1, landing)
        for i in range(1, moves):
            cell = order[i % n]
            if feet[i] > feet[i - 1]:
                nxt = order[(i + 1) % n]
                facing = CARDINAL[(nxt[0] - cell[0], nxt[1] - cell[1])]
                lay(cell, feet[i] - 1, f"{STAIR}[facing={facing},half=bottom,shape=straight]")
            else:
                lay(cell, feet[i] - 1, landing)
    lay(order[0], floors[-1] - 1, landing)
    for cell, ys in supports.items():  # feet, head and the step-up clearance stay open
        ys.sort()
        assert all(b - a >= 3 for a, b in zip(ys, ys[1:])), (cell, ys)


def stair_core(layouts, floors):
    """The scissor stair: one shaft between the two corridors, with a landing door on each floor."""
    region, walls, voids = layouts["typical"]
    shaft = voids["S"]
    assert all(layout[2]["S"] == shaft for layout in layouts.values())
    ring, well = ring_of(shaft)

    def corridor(c):
        return all(layout[0].get(c) in ("corrA", "corrB") and c not in layout[1] for layout in layouts.values())

    trail = {c: [c] for c in ring}
    queue = deque(sorted(ring))
    found = None
    while queue and not found:
        c = queue.popleft()
        for d in N4:
            w, o = (c[0] + d[0], c[1] + d[1]), (c[0] + 2 * d[0], c[1] + 2 * d[1])
            if w in walls and corridor(o):
                found = trail[c], w
                break
        else:
            for d in N4:
                nb = (c[0] + d[0], c[1] + d[1])
                if nb in shaft and nb not in trail:
                    trail[nb] = trail[c] + [nb]
                    queue.append(nb)
    path, doorway = found
    flights(ring, path[0], floors, "floor", 44)
    for h in floors:
        paint(set(path[1:]), h - 1, h, "floor", 44)
        paint({doorway}, h, h + 2, "minecraft:air", 45)
    if len(well) == 1:
        paint(well, floors[0], floors[-1] + 4, "core", 44)


ZONES = [("ground", 0, 14), ("typical", 14, H[38]), ("high", H[38], 205)]
SERVED = {"ground": [0], "typical": [H[n] for n in range(3, 38)], "high": [H[n] for n in range(38, 49)]}


def core():
    layouts = {zone: core_layout(zone) for zone, _, _ in ZONES}
    for k, (zone, lo, hi) in enumerate(ZONES):
        region, walls, voids = layouts[zone]
        above = layouts[ZONES[k + 1][0]][2] if k + 1 < len(ZONES) else {}
        material = "lobby_core" if zone == "ground" else "core"
        paint(walls, lo, hi, material, 40)
        for label, cells in sorted(voids.items()):
            if label.endswith("svc"):  # service rooms keep their floors
                continue
            paint(cells, lo, hi, "minecraft:air", 41)
            if label not in above:  # the shaft ends here: cap it under the next slab
                paint(cells, hi - 1, hi, material, 42)
            if label[0] in LIFT_FRONT:
                found = lift_doors(region, walls, voids, label, LIFT_FRONT[label[0]])
                if found:
                    cell, facing = found
                    for h in SERVED[zone]:
                        door(cell, h, facing)
                floors = SERVED[zone]
                seed = sum(ord(ch) * (i + 3) for i, ch in enumerate(label))
                y = floors[seed % len(floors)]
                paint(cells, y - 1, y, "car_floor", 43)
                paint(cells, y + 3, y + 4, "car_roof", 43)
    stair_core(layouts, [0] + [H[n] for n in range(3, 49)])
    return layouts


# ---------------------------------------------------------------- fittings


AVOID = set()  # cells canopies must not grow into: glass and columns
CORE_AVOID = set()  # core cells, which canopies avoid only below the top of the core
CORE_TOP = 205


def tree(x, z, y, height, radius, leaves="leaves", trunk="trunk", spread=0.45):
    cell = (math.floor(x), math.floor(z))
    cx, cz = cell[0] + 0.5, cell[1] + 0.5
    profile = [radius - 1, radius, radius, radius, radius - 1, max(0, radius - 2)]
    top = y + height
    for k, r in enumerate(profile):
        layer = top - len(profile) + k
        if layer > y + 1:
            blocked = AVOID | (CORE_AVOID if layer < CORE_TOP else set())
            paint(disc(cx, cz, r + spread) - blocked, layer, layer + 1, leaves, 62)
    paint({cell}, y, top - 1, trunk, 63)
    return cell


def bench_ring(x, z, y, r_in, r_out, half=None):
    cells = disc(x, z, r_out, r_in)
    if half:
        cells = {c for c in cells if (c[1] + 0.5 - z) * half >= 0}
    paint(cells, y, y + 1, "bench", 58)


def revolving_door(cell, y=0):
    i, j = cell
    paint(rect(i - 1, j - 1, i + 2, j + 2), y, y + 3, "minecraft:air", 70)
    paint({(i - 1, j - 1), (i + 1, j - 1), (i - 1, j + 1), (i + 1, j + 1)}, y, y + 3, "lobby_glass", 71)
    paint({cell}, y, y + 3, "minecraft:iron_bars", 71)
    paint(rect(i - 1, j - 1, i + 2, j + 2), y + 3, y + 4, "lobby_frame", 71)


def escalator(z, x0, x1, lo, rise, rails=()):
    """Half a metre of rise per cell, rising east: slabs and stairs over a dark truss."""
    for k, x in enumerate(range(x0, x1)):
        halves = k + 1
        y = lo + (halves - 1) // 2
        if y > lo:
            paint({(x, z)}, lo, y, "escalator", 55)
        state = ("minecraft:polished_blackstone_slab[type=bottom]" if halves % 2 else
                 "minecraft:polished_blackstone_stairs[facing=east,half=bottom,shape=straight]")
        put((x, z), y, state, 56)
        for side in rails:
            put((x, side), y + 1, "lobby_glass", 54)
            paint({(x, side)}, lo, y + 1, "escalator", 55)
        if halves // 2 >= rise:
            break


# ---------------------------------------------------------------- the building

base_cells, mid_cells, rim_cells, urban_cells = (cells_of(p) for p in (BASE, MID, RIM, URBAN))
WEST_SHAFT = rect(3, 8, 6, 16)
EAST_SHAFT = rect(48, 29, 55, 37)

# Plaza, street paving and ground floors.
slab([(-24, -8), (66, -8), (66, 56), (-24, 56)], -1, 0, "plaza", 5, "Plaza")
for x in range(-22, 66, 8):
    paint(rect(x, -8, x + 1, 56), -1, 0, "plaza_line", 6)
slab(BASE, -1, 0, "lobby_floor", 8, "Lobby floor")
slab(URBAN, -1, 0, "lobby_floor", 8, "Urban room floor")

# Floor plates. Level 43 is the 177 m terrace, 49 the 205 m garden and 53 the 230 m roof.
for n in range(3, 54):
    h = H[n]
    outline = BASE if h <= 177 else MID if h <= 205 else RIM
    slab(outline, h - 1, h, "floor", 10, f"Level {n:02d} floor")
    if n < 53:
        room(f"Level {n:02d}", outline, h, H[n + 1] - 1)

# Facades. The urban room and the lobby share their ground floor, so the glass between them is left out.
open_ground = near(base_cells, urban_cells) | near(urban_cells, base_cells)
base_ring = facade(BASE, 0, 14, "lobby", skip=open_ground)[0]
facade(URBAN, 0, 14, "lobby", skip=open_ground)
slab(URBAN, 13, 14, "urban_roof", 12, "Urban room roof")
paint(strip((-15.4, 9.5), (-7.6, 34.5), 2.2) & urban_cells, 13, 14, "skylight", 13)
facade(BASE, 14, 177)
mid_ring = facade(MID, 177, 205)[0]
rim_ring, rim_corner, rim_mullion, rim_glass = facade(RIM, 205, 230)

# Louvred plant floors: the crown all round, the south strip below it, and one band at level 25.
paint(rim_glass | rim_mullion, 214, 229, "louvre", 34)
paint((mid_ring & rim_cells) - facade_pattern(MID)[1], 192, 205, "louvre", 34)
east_band = {c for c in facade_pattern(BASE)[3] | facade_pattern(BASE)[2] if c[0] >= 44 and 25 <= c[1] <= 40}
paint(east_band, H[25], H[26], "louvre", 34)

# Perimeter columns.
for x, z in COLUMNS_BASE:
    cell = (math.floor(x), math.floor(z))
    paint({cell}, 0, 14, "lobby_core", 35)
    paint({cell}, 14, 176, "column", 35)
for x, z in COLUMNS_MID:
    paint({(math.floor(x), math.floor(z))}, 177, 204, "column", 35)

layouts = core()
core_cells = set().union(*(set(layout[0]) for layout in layouts.values()))
column_cells = {(math.floor(x), math.floor(z)) for x, z in COLUMNS_BASE + COLUMNS_MID}
assert max(hi for _, _, hi in ZONES) == CORE_TOP
CORE_AVOID |= core_cells
AVOID |= base_ring | rim(urban_cells) | column_cells

# Ceiling lights and a few fitted-out office floors.
for n in range(3, 51):
    h, up = H[n], H[n + 1]
    plate = base_cells if h < 177 else mid_cells if h < 205 else rim_cells
    above = base_cells if up <= 177 else mid_cells if up <= 205 else rim_cells
    region = layouts["ground" if h < 14 else "typical" if h < H[38] else "high"][0]
    office = (plate & above) - rim(plate) - set(region)
    paint({c for c in office if c[0] % 6 == 3 and c[1] % 6 == 3}, up - 1, up, "light", 36)
    if n in (6, 12, 19, 27, 34, 40, 45):
        free = office - near(office, set(region)) - rim(plate - rim(plate)) - near(office, column_cells) - column_cells
        desks = {c for c in free if c[0] % 6 in (1, 2) and c[1] % 4 == 1}
        paint(desks, h, h + 1, "office_desk", 37)
        paint({(i, j - 1) for i, j in desks if (i, j - 1) in free}, h, h + 1,
              "minecraft:dark_oak_stairs[facing=south,half=bottom,shape=straight]", 37)

# Glazed lift shafts in the west and east notches, with the cars parked at different heights.
paint(rect(3, 8, 6, 9) | rect(3, 15, 6, 16), 0, 206, "shaft_end", 50)
paint(rect(3, 9, 4, 15), 0, 205, "lift_glass", 50)
for (z0, y) in ((9, 62), (12, 141)):
    paint(rect(4, z0, 6, z0 + 3), y - 1, y, "car_floor", 51)
    paint(rect(4, z0, 6, z0 + 3), y + 3, y + 4, "car_roof", 51)
paint(rect(48, 29, 55, 30) | rect(48, 36, 55, 37), 0, 206, "shaft_end", 50)
paint(rect(54, 30, 55, 36) | rect(50, 30, 51, 36), 0, 205, "lift_glass", 50)
paint(rect(48, 30, 50, 36), 0, 205, "minecraft:air", 50)
paint(rect(48, 29, 55, 37), 205, 206, "shaft_end", 50)
for (z0, y) in ((30, 98), (33, 170)):
    paint(rect(51, z0, 54, z0 + 3), y - 1, y, "car_floor", 51)
    paint(rect(51, z0, 54, z0 + 3), y + 3, y + 4, "car_roof", 51)

# Ground floor lobby: 14 m high, light stone, trees in oak benches, reception, escalators.
for x, z in [(6.9, 25.6), (14.3, 25.6), (32.5, 4), (49.5, 25.6)]:
    tree(x, z, 0, 12, 2)
    bench_ring(x, z, 0, 1.6, 2.6, half=1)
paint(strip((36.0, 3.0), (38.6, 7.0), 1.3), 0, 1, "desk", 57)
for z, rails in ((38, (37,)), (39, (40,))):
    escalator(z, 27, 41, 0, 7, rails)
for k, z in enumerate(range(26, 33)):
    paint(rect(44, z, 46, z + 1), 0, k, "escalator", 55)
    paint(rect(44, z, 46, z + 1), k, k + 1, "minecraft:polished_andesite_stairs[facing=south,half=bottom,shape=straight]", 56)
mezzanine = (rect(21, 40, 47, 44) | rect(41, 37, 47, 40) | rect(42, 33, 47, 37)) & base_cells
paint(mezzanine - base_ring, 6, 7, "floor", 52)
paint((rect(21, 40, 41, 41) | rect(41, 36, 42, 40) | rect(42, 33, 44, 34) | rect(46, 33, 47, 34)) & mezzanine,
      7, 8, "balustrade", 53)
paint(rect(41, 38, 42, 40), 7, 8, "minecraft:air", 54)
room("Lobby mezzanine", [(21, 40), (47, 40), (47, 44), (21, 44)], 7, 13)
for x in (24, 28, 32, 36):
    put((x, 42), 0, "minecraft:spruce_fence", 57)
    put((x, 42), 1, "minecraft:spruce_pressure_plate", 57)
    put((x - 1, 42), 0, "minecraft:spruce_stairs[facing=west,half=bottom,shape=straight]", 57)
    put((x + 1, 42), 0, "minecraft:spruce_stairs[facing=east,half=bottom,shape=straight]", 57)
region, walls, _ = layouts["ground"]
mosaic = sorted(c for c in walls if region[c].startswith("B") and stc(c)[1] < 1.6)
for c in mosaic:
    tile = ["mosaic_blue", "mosaic_teal", "mosaic_orange", "mosaic_red"][(c[0] * 2 + c[1]) % 4]
    paint({c}, 1, 12, tile, 47)

# Urban room: a glazed winter garden of trees round a circular bench.
for x, z in [(-10.1, 11.4), (-4.4, 12.2), (-9.5, 18.2), (-2.2, 18.8), (-6.7, 25.6),
             (-1, 25.6), (-6.1, 31.8), (1.3, 31.8), (4.1, 25)]:
    tree(x, z, 0, 12, 2)
bench_ring(-5, 21.9, 0, 1.4, 2.4)
paint(strip((1.0, 10.2), (1.0, 13.8), 1.0), 0, 1, "desk", 57)

# Entrances: revolving doors, the main south doors and the black cantilevered canopy.
for cell in [(44, 11), (-9, 8), (6, 35)]:
    revolving_door(cell)
paint(rect(44, 44, 48, 45), 0, 3, "minecraft:air", 70)
paint(rect(43, 44, 44, 45) | rect(48, 44, 49, 45), 0, 3, "lobby_frame", 70)
canopy = rect(39, 45, 54, 53)
paint(canopy, 13, 14, "lobby_frame", 70)
paint(canopy - rim(canopy), 12, 13, "canopy_soffit", 70)
paint(rim(canopy) - rect(39, 45, 54, 46), 12, 13, "lobby_frame", 70)

# 177 m private terrace on the north strip and the north-east diagonal.
terrace = base_cells - mid_cells
paint(terrace, 176, 177, "terrace_floor", 20)
paint((base_ring & terrace) - facade_pattern(BASE)[1], 177, 179, "balustrade", 60)
paint(facade_pattern(BASE)[1] & terrace, 177, 179, "fin", 60)
for x in (10, 18, 26):
    paint(rect(x, 4, x + 3, 6), 177, 178, "soil", 61)
    paint(rect(x, 4, x + 3, 6), 178, 179, "hedge", 61)
room("Private terrace 177m", [(6, 1), (33, 1), (33, 7), (6, 7)], 177, 186)

# 205 m public garden: sixteen trees in a sunken grove ringed by a seating step.
garden = mid_cells - rim_cells - WEST_SHAFT - EAST_SHAFT
paint(garden, 204, 205, "terrace_floor", 20)
paint((mid_ring & garden) - facade_pattern(MID)[1], 205, 207, "balustrade", 60)
paint(facade_pattern(MID)[1] & garden, 205, 207, "fin", 60)
pit = cells_of(GARDEN_PIT)  # one step down, so it stays clear of the level 48 ceiling
step = {c for c in garden - pit if any((c[0] + dx, c[1] + dz) in pit for dx, dz in N8)}
paint(pit, 203, 204, "soil", 65)
paint(pit, 204, 205, "minecraft:air", 65)
paint({c for c in step if (c[0] + c[1]) % 3 == 0}, 205, 206, "bench", 66)
for r in range(4):
    z = 15.3 + 3.3 * r
    left = 18.5 + (z - 13.9) * 0.597
    for col in range(4):
        # Small rounded crowns of mixed height, so the grove reads as separate trees.
        tree(left + 2.2 + 3.0 * col, z, 204, 7 + (r + col) % 3, 1, "garden_leaves", spread=0.2)
pavilion = rect(3, 8, 9, 16)  # the west lifts arrive in a glass pavilion on the garden
paint(rim(pavilion), 205, 208, "lift_glass", 67)
paint(rect(8, 11, 9, 13), 205, 207, "minecraft:air", 68)
paint(pavilion - rim(pavilion), 205, 208, "minecraft:air", 68)
paint(pavilion, 208, 209, "car_roof", 68)
room("Garden 205m", [(10, 9), (33, 9), (44, 27), (22, 34), (12, 18)], 205, 214)

# South-west lift and stair node rising to the spire base.
node = rect(16, 40, 21, 45)
paint(node, 177, 233, "lift_glass", 72)
paint({(16, 40), (20, 40), (16, 44), (20, 44)}, 177, 234, "fin", 73)
paint(node - rim(node), 177, 233, "minecraft:air", 73)
paint(node, 232, 233, "fin", 73)
ring, well = ring_of(node - rim(node))
node_floors = [H[n] for n in range(43, 54)]
flights(ring, (18, 41), node_floors, "floor", 74)
paint(well, 177, 233, "fin", 74)
for h in node_floors:  # the landing door faces north into each floor
    assert (18, 39) in (mid_cells if h <= 205 else rim_cells) and (18, 39) not in core_cells | column_cells
    paint({(18, 40)}, h, h + 2, "minecraft:air", 75)
# Doors out of the glass: level 43 onto the 177 m terrace, the crown onto the 205 m garden.
paint({(20, 8)}, 177, 179, "minecraft:air", 75)
garden_door = sorted((c for c in rim_ring if (c[0], c[1] - 1) in garden and (c[0], c[1] + 1) in rim_cells
                      and (c[0], c[1] + 1) not in rim_ring), key=lambda c: abs(c[0] - 28))[0]
paint({garden_door}, 205, 207, "minecraft:air", 75)
junction = rect(20, 34, 24, 39) & rim_cells  # glazed stair head where the two arms meet
paint(junction, 230, 232, "lift_glass", 72)
paint(junction - rim(junction), 230, 232, "minecraft:air", 73)
paint(junction, 232, 233, "car_roof", 73)

# 230 m viewing terrace: glass balustrade, black end walls, hipped roof lights and stair wells.
paint(rim_cells, 229, 230, "terrace_floor", 20)
ends = rect(0, 16, 9, 17) | rect(47, 36, 55, 37)
paint((rim_ring - ends) - rim_corner, 230, 232, "balustrade", 60)
paint(rim_corner - ends, 230, 232, "fin", 60)
paint(ends & rim_cells, 230, 233, "lobby_frame", 61)
west_light = strip((10.7, 26.5), (14.9, 33.0), 2.4) & rim_cells
paint(west_light, 230, 231, "skylight", 62)
paint(strip((10.7, 26.5), (14.9, 33.0), 0.9) & west_light, 231, 232, "skylight", 62)
paint(rect(28, 39, 40, 42), 230, 231, "skylight", 62)
paint(rect(28, 40, 40, 41), 231, 232, "skylight", 62)
paint(rect(40, 39, 43, 42), 230, 232, "lobby_glass", 62)
paint(rect(40, 39, 43, 42), 232, 233, "lobby_frame", 62)
for k, z in enumerate(range(19, 25)):  # west arm stair, rising north
    paint(rect(7, z, 9, z + 1), 224 + 5 - k, 230, "minecraft:air", 63)
    paint(rect(7, z, 9, z + 1), 224 + 5 - k, 225 + 5 - k,
          "minecraft:polished_andesite_stairs[facing=north,half=bottom,shape=straight]", 64)
paint(rect(6, 19, 7, 25) | rect(9, 19, 10, 25), 230, 231, "balustrade", 63)
for k, x in enumerate(range(43, 49)):  # south arm stair, rising east
    paint(rect(x, 40, x + 1, 42), 224 + k, 230, "minecraft:air", 63)
    paint(rect(x, 40, x + 1, 42), 224 + k, 225 + k,
          "minecraft:polished_andesite_stairs[facing=east,half=bottom,shape=straight]", 64)
paint(rect(43, 39, 49, 40) | rect(43, 42, 49, 43), 230, 231, "balustrade", 63)
room("Viewing terrace 230m", [(22, 37), (54, 37), (54, 44), (22, 44)], 230, 240)

# The spire: an A-frame on the node, a square lattice with dishes and three ring platforms,
# a mast of paired panel antennas with a large disc, and a slim top mast to 310 m.
cx, cz = 18.5, 42.5
lattice = rect(16, 40, 21, 45)
posts = {(16, 40), (20, 40), (16, 44), (20, 44)}
paint(posts, 233, 259, "spire", 80)
for e, y0 in ((-1, 233), (1, 233), (0, 235)):  # inverted-V bracing on each face of the base
    faces = {(18 + e, 40), (18 + e, 44), (16, 42 + e), (20, 42 + e)}
    paint(faces, y0, y0 + 2, "spire", 80)
paint(rim(lattice) - posts, 237, 259, "lattice", 79)
paint({(18, 42)}, 233, 292, "spire", 81)
for y in (237, 247, 258):
    paint(disc(cx, cz, 4.2) - (lattice - rim(lattice)) - posts, y, y + 1, "ring", 82)
for k, y in enumerate((240, 244, 250, 254)):
    side = k % 2
    for dx, dz in ((0, -1), (0, 1)) if side else ((-1, 0), (1, 0)):
        c0 = (18 + dx * 3, 42 + dz * 3)
        plate = {(c0[0] + (0 if dx else e), c0[1] + (0 if dz else e)) for e in (-1, 0, 1)}
        paint(plate, y, y + 2, "spire_white", 82)
for y in range(260, 290, 4):
    paint({(17, 42), (19, 42)}, y, y + 3, "spire_white", 82)
paint(disc(cx, cz, 4.5) - {(18, 42)}, 271, 272, "ring", 82)
paint(disc(cx, cz, 2.4) - {(18, 42)}, 291, 292, "ring", 82)
paint({(18, 42)}, 292, 309, "minecraft:end_rod[facing=up]", 83)
put((18, 42), 309, "minecraft:red_stained_glass", 83)

# Street trees on the plaza.
for x, z in [(-20, -4), (-20, 50), (60, -4), (62, 50), (30, 52)]:
    tree(x, z, 0, 8, 2, "garden_leaves")

flush()

MODEL = {
    "name": "Varso Tower, Warsaw",
    "scale": 100,
    "quantize": "round",
    "margin": 2,
    "ground": 0,
    "terrain": {"material": "minecraft:stone", "depth": 1},
    "levels": {"ground": 0, "private_terrace": 17700, "garden": 20500,
               "viewing_terrace": 23000, "spire_tip": 31000},
    "parts": PARTS,
    "cameras": [
        {"name": "lobby-trees", "at": [500, 3600], "elevation": 0, "look_at": [-900, 1700, 500]},
        {"name": "lobby-escalators", "at": [2400, 4100], "elevation": 0, "look_at": [4200, 3850, 500]},
        {"name": "urban-room", "at": [-300, 3000], "elevation": 0, "look_at": [-700, 1200, 500]},
        {"name": "main-entrance", "at": [4650, 6200], "elevation": 0, "look_at": [4600, 4400, 900]},
        {"name": "office-level-12", "at": [600, 400], "elevation": H[12] * 100, "look_at": [3000, 2000, H[12] * 100 + 100]},
        {"name": "terrace-177", "at": [700, 250], "elevation": 17700, "look_at": [3300, 250, 17850]},
        {"name": "garden-205", "at": [1200, 1100], "elevation": 20500, "look_at": [3200, 2200, 20400]},
        {"name": "viewing-terrace-230", "at": [5200, 4000], "elevation": 23000, "look_at": [1000, 2600, 23300]},
        {"name": "crown-and-spire", "at": [6000, 2000], "elevation": 23200, "look_at": [1850, 4250, 27000]},
    ],
}
(ROOT / "building.yaml").write_text(yaml.safe_dump(MODEL, sort_keys=False, width=120), encoding="utf-8")
print(f"{len(PARTS)} parts; {len(FLOORS)} levels; 310 m architectural height")
