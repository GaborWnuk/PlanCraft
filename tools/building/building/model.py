"""Compiling a building model (centimetres) into a voxel grid (one block per ``scale`` cm).

A model is plain data, usually loaded from ``building.yaml``::

    name: Example house
    scale: 100            # centimetres per block (100 = real size)
    margin: 2             # empty blocks kept around the building
    levels: {ground: 0, first: 367, roof_low: 717}
    parts:                # compiled in order; later parts overwrite earlier ones
      - {type: slab, material: concrete, polygon: [[0, 0], [1000, 0], [1000, 800], [0, 800]], bottom: -30, top: 0}
      - {type: wall, material: facade, path: [[0, 0], [1000, 0]], thickness: 47, bottom: 0, top: first,
         openings: [{at: 200, width: 100, bottom: 0, top: 210, kind: door}]}

Plan coordinates are ``[x, z]`` in centimetres with x growing east and z growing south,
which is also the direction page coordinates grow on a plan whose north is up. Heights
are elevations in centimetres, or names from ``levels`` optionally followed by an offset
(``first+20``).

Quantisation (``quantize``):

* ``ceil`` (default): the grid is warped per axis. Wall faces, the centre lines of thin
  partitions and the levels are breakpoints; every span between two of them gets
  ``ceil`` of its length in blocks (a wall at least one block), so walls sit exactly on
  block edges and no room, storey or walkway is ever smaller than in reality. The house
  grows by a fraction of a block per span instead of rooms clipping into each other.
* ``round``: one uniform grid, every boundary rounded on its own.

A cell belongs to a footprint when its centre (in centimetres) lies inside it. Interior
partitions no thicker than ``thin_wall`` become thin panels (open trapdoors) on the
block edge they stand on and take no cell; exterior walls thinner than ``glazed_below``
are glazing, with frame pillars at corners and between openings.
"""

from __future__ import annotations

import bisect
import math
import re
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from .grid import AIR, Grid, join_state, normalize_state, split_state

Point = tuple[float, float]

CARDINALS = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}
OPPOSITE = {"north": "south", "south": "north", "east": "west", "west": "east"}


class ModelError(ValueError):
    pass


# ---------------------------------------------------------------- geometry


def polygon_mask(polygon: list[Point], xs: np.ndarray, zs: np.ndarray) -> np.ndarray:
    """Even-odd test of every (xs[i], zs[k]) pair; returns a boolean array of shape (len(xs), len(zs))."""
    px = xs[:, None]
    pz = zs[None, :]
    inside = np.zeros((len(xs), len(zs)), dtype=bool)
    n = len(polygon)
    for i in range(n):
        x1, z1 = polygon[i]
        x2, z2 = polygon[(i + 1) % n]
        if z1 == z2:
            continue
        crosses = (z1 > pz) != (z2 > pz)
        x_at = x1 + (pz - z1) * (x2 - x1) / (z2 - z1)
        inside ^= crosses & (px < x_at)
    return inside


def segment_band(a: Point, b: Point, left: float, right: float | None = None, start_extra: float = 0.0, end_extra: float = 0.0) -> list[Point]:
    """The rectangle around segment a-b reaching ``left`` and ``right`` to each side, extended past each end.

    Left is the left of travel seen from above with north up (x east, z south).
    """
    if right is None:
        right = left
    (ax, az), (bx, bz) = a, b
    length = math.hypot(bx - ax, bz - az)
    if length == 0:
        raise ModelError(f"zero-length wall segment at {a}")
    ux, uz = (bx - ax) / length, (bz - az) / length
    nx, nz = uz, -ux  # left normal
    sx, sz = ax - ux * start_extra, az - uz * start_extra
    ex, ez = bx + ux * end_extra, bz + uz * end_extra
    return [
        (sx + nx * left, sz + nz * left),
        (ex + nx * left, ez + nz * left),
        (ex - nx * right, ez - nz * right),
        (sx - nx * right, sz - nz * right),
    ]


def facing_of(dx: float, dz: float) -> str:
    """The cardinal direction closest to a plan vector."""
    if abs(dx) >= abs(dz):
        return "east" if dx > 0 else "west"
    return "south" if dz > 0 else "north"


def rect(x0: float, z0: float, x1: float, z1: float) -> list[Point]:
    return [(x0, z0), (x1, z0), (x1, z1), (x0, z1)]


# ---------------------------------------------------------------- blocks

# Blocks that are not full cubes: panes and fences do not hide what is behind them,
# and nothing connects to them as if they were walls.
_PARTIAL = re.compile(
    r"(_slab|_stairs|_pane|_bars|_door|_trapdoor|_fence|_fence_gate|_wall|_carpet|torch|lantern|_bed|_button|"
    r"_pressure_plate|_sign|_banner|ladder|rail|flower_pot|_candle|candle|chain|_rod|scaffolding|snow|"
    r"_head|_skull|lever|_leaves|glass$|_glass$|grass$|fern|flower|bush|sapling|_plate|chest|barrel_x)"
)
_CONNECTING = re.compile(r"(_pane|_bars|_fence|_wall)$")


def is_full(state: str) -> bool:
    name = split_state(state)[0]
    if name == AIR:
        return False
    if name.endswith("_wall") and not name.endswith(("_wall_sign", "_wall_banner", "_wall_torch", "_wall_head", "_wall_skull")):
        return False
    return not _PARTIAL.search(name.split(":", 1)[1])


def connects(state: str) -> bool:
    return bool(_CONNECTING.search(split_state(state)[0]))


# ---------------------------------------------------------------- model


@dataclass
class Warp:
    """A monotonic, piecewise linear map from centimetres to block coordinates on one axis.

    Breakpoints are wall faces, wall centre lines and levels; each span between two of them
    gets a whole number of blocks, so walls land on block edges and spans never shrink.
    """

    cm: list[float]
    blk: list[float]
    scale: float

    @classmethod
    def uniform(cls, start: float, scale: float) -> "Warp":
        return cls([start, start + scale], [0.0, 1.0], scale)

    def fwd(self, v: float) -> float:
        cm, blk = self.cm, self.blk
        if v <= cm[0]:
            return blk[0] + (v - cm[0]) / self.scale
        if v >= cm[-1]:
            return blk[-1] + (v - cm[-1]) / self.scale
        k = bisect.bisect_right(cm, v) - 1
        span = cm[k + 1] - cm[k]
        return blk[k] + (v - cm[k]) / span * (blk[k + 1] - blk[k])

    def inv(self, b: float) -> float:
        cm, blk = self.cm, self.blk
        if b <= blk[0]:
            return cm[0] + (b - blk[0]) * self.scale
        if b >= blk[-1]:
            return cm[-1] + (b - blk[-1]) * self.scale
        k = bisect.bisect_right(blk, b) - 1
        while blk[k + 1] == blk[k]:  # collapsed spans hold no block
            k += 1
        return cm[k] + (b - blk[k]) / (blk[k + 1] - blk[k]) * (cm[k + 1] - cm[k])

    def table(self) -> list[list[float]]:
        return [[round(c, 2), round(b, 3)] for c, b in zip(self.cm, self.blk)]


@dataclass
class Frame:
    """Where model centimetres land in the grid."""

    scale: float
    wx: Warp
    wy: Warp
    wz: Warp
    size: tuple[int, int, int]

    @property
    def x0(self) -> float:  # centimetres at grid x = 0 (west edge)
        return self.wx.inv(0)

    @property
    def z0(self) -> float:  # centimetres at grid z = 0 (north edge)
        return self.wz.inv(0)

    @property
    def y0(self) -> float:  # elevation at grid y = 0 (bottom)
        return self.wy.inv(0)

    def fx(self, x: float) -> float:
        return self.wx.fwd(x)

    def fz(self, z: float) -> float:
        return self.wz.fwd(z)

    def fy(self, elevation: float) -> float:
        return self.wy.fwd(elevation)

    def cx(self, x: float) -> int:
        return int(round(self.fx(x)))

    def cz(self, z: float) -> int:
        return int(round(self.fz(z)))

    def cy(self, elevation: float) -> int:
        return int(round(self.fy(elevation)))

    def centres_x(self) -> np.ndarray:
        return np.array([self.wx.inv(i + 0.5) for i in range(self.size[0])])

    def centres_z(self) -> np.ndarray:
        return np.array([self.wz.inv(i + 0.5) for i in range(self.size[2])])

    def cell_of(self, x: float, z: float) -> tuple[int, int]:
        return int(math.floor(self.fx(x))), int(math.floor(self.fz(z)))

    def layers(self, bottom: float, top: float) -> range:
        """Grid layers covering [bottom, top), with rounded boundaries.

        Anything thinner than that rounding (a 30 cm slab between block edges) still gets
        one layer: the one holding its middle.
        """
        a, b = self.cy(bottom), self.cy(top)
        if b <= a and top > bottom:
            a = int(math.floor(self.fy((bottom + top) / 2)))
            b = a + 1
        return range(a, b)

    def to_model(self, gx: float, gy: float, gz: float) -> tuple[float, float, float]:
        return self.wx.inv(gx), self.wy.inv(gy), self.wz.inv(gz)

    def warp_meta(self) -> dict:
        return {"x": self.wx.table(), "y": self.wy.table(), "z": self.wz.table()}

    @classmethod
    def from_meta(cls, meta: dict) -> "Frame":
        s = float(meta["scale"])
        size = tuple(meta["size"])
        if meta.get("warp"):
            w = {k: Warp([p[0] for p in v], [p[1] for p in v], s) for k, v in meta["warp"].items()}
            return cls(s, w["x"], w["y"], w["z"], size)
        x0, y0, z0 = meta["origin_cm"]
        return cls(s, Warp.uniform(x0, s), Warp.uniform(y0, s), Warp.uniform(z0, s), size)


@dataclass
class Compiled:
    grid: Grid
    frame: Frame
    ground_layer: int
    rooms: list[dict] = field(default_factory=list)
    room_masks: list[np.ndarray] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def meta(self) -> dict:
        f = self.frame
        return {
            "size": list(self.grid.shape),
            "scale": f.scale,
            "origin_cm": [f.x0, f.y0, f.z0],
            "warp": f.warp_meta(),
            "ground_layer": self.ground_layer,
            "rooms": self.rooms,
            "warnings": self.warnings,
            "blocks": sum(c for s, c in self.grid.counts().items() if s != AIR),
        }


class Model:
    def __init__(self, data: dict, palette: dict | None = None):
        self.data = data
        self.palette = palette or {}
        self.scale = float(data.get("scale", 100))
        self.margin = int(data.get("margin", 2))
        self.levels: dict[str, float] = {}
        for name, value in (data.get("levels") or {}).items():
            self.levels[name] = self.elevation(value)
        self.parts: list[dict] = list(data.get("parts") or [])
        self.ground = self.elevation(data.get("ground", 0))
        self.quantize = str(data.get("quantize", "ceil"))
        q = data.get("quantization") or {}
        self.thin_wall = float(q.get("thin_wall", 15))  # interior walls up to this thick become edge panels
        self.glazed_below = float(q.get("glazed_below", 25))  # exterior walls thinner than this are glazing
        self.merge_tol = float(q.get("merge", 8))  # wall faces closer than this are one grid line
        self.snap_tol = float(q.get("snap", 15))  # partitions this close to a wall face stand on it
        self.collapse_below = float(q.get("collapse", 30))  # open spans shorter than this get no block
        self.ceil_tol = float(q.get("tolerance", 0.1))  # blocks = ceil(length / scale - tolerance)
        self.panel = q.get("panel", "minecraft:pale_oak_trapdoor")

    # -- values

    def elevation(self, value: Any) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        if not isinstance(value, str):
            raise ModelError(f"not an elevation: {value!r}")
        m = re.fullmatch(r"\s*([A-Za-z_][\w]*)\s*(?:([+-])\s*(\d+(?:\.\d+)?))?\s*", value)
        if not m:
            try:
                return float(value)
            except ValueError:
                raise ModelError(f"not an elevation: {value!r}") from None
        name, sign, offset = m.groups()
        if name not in self.levels:
            raise ModelError(f"unknown level {name!r}")
        base = self.levels[name]
        if offset:
            base += float(offset) if sign == "+" else -float(offset)
        return base

    def material(self, name: str | None, role: str = "block") -> str | None:
        """A block state for a palette name, or the name itself when it is already a block."""
        if name is None or name == "air":
            return None
        entry = self.palette.get(name)
        if entry is None:
            if ":" in name or re.fullmatch(r"[a-z0-9_]+(\[.*\])?", name):
                return normalize_state(name)
            raise ModelError(f"unknown material {name!r}")
        if isinstance(entry, str):
            return normalize_state(entry)
        state = entry.get(role) or entry.get("block")
        if state is None:
            raise ModelError(f"material {name!r} has no {role!r} block")
        return normalize_state(state)

    def material_variant(self, name: str, role: str) -> str | None:
        """A shaped variant (stairs, slab, pane) of a material: palette entry, or derived from the name."""
        entry = self.palette.get(name)
        if isinstance(entry, dict) and entry.get(role):
            return normalize_state(entry[role])
        base = self.material(name)
        if base is None:
            return None
        block = split_state(base)[0]
        stem = block
        for suffix in ("_planks", "_block"):
            stem = stem.removesuffix(suffix)
        if stem.endswith(("bricks", "tiles")):
            stem = stem[:-1]
        candidates = [stem + "_" + role, block + "_" + role] if role in ("slab", "stairs") else []
        from . import registry

        known = registry.blocks()
        for c in candidates:
            if c in known:
                return c
        return None

    # -- extent

    def _points(self) -> list[Point]:
        pts: list[Point] = []
        for part in self.parts:
            for key in ("polygon", "path"):
                if key in part:
                    pts.extend((float(p[0]), float(p[1])) for p in part[key])
            if "at" in part and isinstance(part["at"], (list, tuple)) and len(part["at"]) >= 2:
                pts.append((float(part["at"][0]), float(part["at"][1])))
            if part.get("type") == "spiral_stair":
                cx, cz = part["center"]
                r = float(part["radius"])
                pts += [(cx - r, cz - r), (cx + r, cz + r)]
        if not pts:
            raise ModelError("the model has no geometry")
        return pts

    def _heights(self) -> list[float]:
        hs = [self.ground]
        for part in self.parts:
            for key in ("bottom", "top", "from", "to", "elevation", "low", "high"):
                if key in part and not isinstance(part[key], (list, dict)):
                    hs.append(self.elevation(part[key]))
            if part.get("type") == "roof":
                hs.append(self._roof_peak(part))
        return hs

    def frame(self) -> Frame:
        s = self.scale
        pts = self._points()
        xs = [p[0] for p in pts]
        zs = [p[1] for p in pts]
        hs = self._heights()
        bounds = self.data.get("bounds")
        if bounds:  # explicit [[x0, z0], [x1, z1]] keeps the grid stable while editing
            (bx0, bz0), (bx1, bz1) = bounds
            xs += [bx0, bx1]
            zs += [bz0, bz1]
        pad = self.margin * s
        x0 = math.floor((min(xs) - pad) / s) * s
        z0 = math.floor((min(zs) - pad) / s) * s
        x1 = math.ceil((max(xs) + pad) / s) * s
        z1 = math.ceil((max(zs) + pad) / s) * s
        terrain = self.data.get("terrain") or {}
        below = float(terrain.get("depth", 0)) * s if terrain else 0
        lowest = min(min(hs), self.ground - below)
        # The ground sits on a block edge, so every height is rounded relative to it.
        y0 = self.ground - math.ceil((self.ground - lowest) / s - 1e-9) * s
        y1 = math.ceil((max(hs) + self.margin * s) / s) * s
        if self.quantize == "round":
            size = (int(round((x1 - x0) / s)), int(round((y1 - y0) / s)), int(round((z1 - z0) / s)))
            return Frame(s, Warp.uniform(x0, s), Warp.uniform(y0, s), Warp.uniform(z0, s), size)
        if self.quantize != "ceil":
            raise ModelError(f"unknown quantize {self.quantize!r} (ceil or round)")
        lines = self._grid_lines()
        wx = self._warp(x0, x1, lines["x"])
        wz = self._warp(z0, z1, lines["z"])
        everywhere = (-math.inf, math.inf, -math.inf, math.inf)
        heights = [{"lo": h, "hi": h, "solid": False, "boxes": [everywhere]} for h in sorted({self.ground, *self.levels.values()})]
        wy = self._warp(y0, max(y1, heights[-1]["hi"] + s), heights)
        size = (int(round(wx.blk[-1])), int(round(wy.blk[-1])), int(round(wz.blk[-1])))
        return Frame(s, wx, wy, wz, size)

    # -- ceil quantisation

    def _is_edge(self, part: dict) -> bool:
        """A thin interior partition drawn as panels on a block edge."""
        if part.get("type") != "wall" or self.quantize != "ceil":
            return False
        if "edge" in part:
            return bool(part["edge"])
        if part.get("outside") or float(part["thickness"]) > self.thin_wall:
            return False
        path = part["path"]
        return all(abs(a[0] - b[0]) < 0.5 or abs(a[1] - b[1]) < 0.5 for a, b in zip(path, path[1:]))

    def _is_glazed(self, part: dict) -> bool:
        if "glazed" in part:
            return bool(part["glazed"])
        return bool(part.get("outside")) and float(part["thickness"]) < self.glazed_below and "pane" not in (self.material(part.get("material")) or "")

    def _grid_lines(self) -> dict[str, list[dict]]:
        """Per axis, every axis-aligned wall segment as a line item.

        An item has its faces ``lo``/``hi`` on this axis (equal for a thin partition),
        whether it is ``solid`` (takes blocks) and ``boxes``: where it stands, as
        (from, to) along the other axis and (bottom, top) in elevation. Two lines only
        bound a space between them where their boxes overlap.
        """
        out: dict[str, list[dict]] = {"x": [], "z": []}
        for part in self.parts:
            if part.get("type") != "wall":
                continue
            path = [(float(x), float(z)) for x, z in part["path"]]
            if part.get("closed"):
                path.append(path[0])
            edge = self._is_edge(part)
            t = float(part["thickness"])
            bottom, top = self.elevation(part["bottom"]), self.elevation(part["top"])
            for a, b in zip(path, path[1:]):
                if abs(a[0] - b[0]) < 0.5:
                    axis, c, span = "x", a[0], sorted((a[1], b[1]))
                elif abs(a[1] - b[1]) < 0.5:
                    axis, c, span = "z", a[1], sorted((a[0], b[0]))
                else:
                    continue
                ext = 0.0 if edge else t / 2
                lo, hi = (c, c) if edge else (c - t / 2, c + t / 2)
                out[axis].append({"lo": lo, "hi": hi, "solid": not edge, "boxes": [(span[0] - ext, span[1] + ext, bottom, top)]})
        for axis in ("x", "z"):
            for v in (self.data.get("grid_lines") or {}).get(axis, []):
                out[axis].append({"lo": float(v), "hi": float(v), "solid": False, "boxes": []})
        return out

    @staticmethod
    def _overlap(p: tuple, q: tuple, margin: float = 10.0) -> tuple | None:
        a0, a1 = max(p[0], q[0]), min(p[1], q[1])
        b0, b1 = max(p[2], q[2]), min(p[3], q[3])
        if a1 - a0 > margin and b1 - b0 > margin:
            return (a0, a1, b0, b1)
        return None

    def _warp(self, start: float, end: float, items: list[dict]) -> Warp:
        """Block coordinates for the lines of one axis.

        Constraints, solved in one pass from low to high (a longest path):

        * a wall band gets at least one block (``round`` of its thickness);
        * two lines facing each other (their boxes overlap, nothing in between) get
          ``ceil(gap / scale - tolerance)`` blocks between them, so no room shrinks;
        * any other span keeps ``floor`` of its length, so nothing grows without need.
        """
        s = self.scale
        merge, snap, collapse, tol = self.merge_tol, self.snap_tol, self.collapse_below, self.ceil_tol
        # Overlapping or nearly touching wall bands (a railing on top of a wall, walls of two
        # storeys a few cm apart) are one solid band.
        lines: list[dict] = []
        for it in sorted((i for i in items if i["solid"]), key=lambda i: i["lo"]):
            if lines and it["lo"] <= lines[-1]["hi"] + merge:
                lines[-1]["hi"] = max(lines[-1]["hi"], it["hi"])
                lines[-1]["boxes"] = lines[-1]["boxes"] + it["boxes"]
            else:
                lines.append(dict(it))
        faces = sorted({v for line in lines for v in (line["lo"], line["hi"])})
        for it in items:
            if it["solid"]:
                continue
            it = dict(it)
            near = min(faces, key=lambda f: abs(f - it["lo"])) if faces else None
            if near is not None and abs(near - it["lo"]) < snap:
                it["lo"] = it["hi"] = near  # a partition meeting a wall face stands on it
            lines.append(it)
        values = sorted({start, end, *(v for line in lines for v in (line["lo"], line["hi"]) if start < v < end)})
        pts: list[float] = []
        for v in values:
            if pts and v - pts[-1] < merge and v != end:
                continue
            pts.append(v)

        def idx(v: float) -> int:
            return min(range(len(pts)), key=lambda i: abs(pts[i] - v))

        cons: dict[int, list[tuple[int, int]]] = {j: [(j - 1, math.floor((pts[j] - pts[j - 1]) / s + 1e-9))] for j in range(1, len(pts))}
        for line in lines:
            i, j = idx(line["lo"]), idx(line["hi"])
            if line["solid"] and j > i:
                cons[j].append((i, max(1, round((line["hi"] - line["lo"]) / s))))
        ordered = sorted(lines, key=lambda line: (line["lo"], line["hi"]))
        for ai, A in enumerate(ordered):
            for B in ordered[ai + 1 :]:
                gap = B["lo"] - A["hi"]
                if gap <= 0:
                    continue
                need = 0 if gap < collapse else math.ceil(gap / s - tol)
                if need == 0:
                    continue
                for pa in A["boxes"]:
                    for pb in B["boxes"]:
                        common = self._overlap(pa, pb)
                        if common is None:
                            continue
                        # only neighbours: no other line stands between them in the shared region
                        if any(
                            C is not A and C is not B and A["hi"] <= C["lo"] and C["hi"] <= B["lo"]
                            and any(self._overlap(common, pc) for pc in C["boxes"])
                            for C in ordered
                        ):
                            continue
                        cons[idx(B["lo"])].append((idx(A["hi"]), need))
        blk = [0.0] * len(pts)
        for j in range(1, len(pts)):
            blk[j] = max(blk[j - 1], *(blk[i] + n for i, n in cons[j]))
        return Warp(pts, blk, s)

    # -- compile

    def compile(self) -> Compiled:
        frame = self.frame()
        grid = Grid(*frame.size)
        out = Compiled(grid, frame, frame.cy(self.ground))
        self._terrain(out)
        ordered = sorted(enumerate(self.parts), key=lambda item: (self._priority(item[1]), item[0]))
        for index, part in ordered:
            kind = part.get("type")
            handler: Callable[[Compiled, dict], None] | None = getattr(self, f"_part_{kind}", None)
            if handler is None:
                raise ModelError(f"part {index}: unknown type {kind!r}")
            try:
                handler(out, part)
            except ModelError as e:
                raise ModelError(f"part {index} ({kind} {part.get('name', '')}): {e}") from None
        connect(grid)
        return out

    # Parts are compiled by priority, then in file order, so floors never cut through walls
    # and roofs and fixtures always win; ``priority`` on a part overrides its type's default.
    PRIORITY = {"slab": 10, "box": 10, "room": 20, "clear": 25, "wall": 30, "stair": 40, "spiral_stair": 40, "roof": 50, "block": 60, "bed": 60}

    def _priority(self, part: dict) -> float:
        if "priority" in part:
            return float(part["priority"])
        return self.PRIORITY.get(part.get("type"), 30)

    def _footprint(self, out: Compiled, polygon: list) -> np.ndarray:
        f = out.frame
        return polygon_mask([(float(x), float(z)) for x, z in polygon], f.centres_x(), f.centres_z())

    def _thin_footprint(self, out: Compiled, polygon: list) -> np.ndarray:
        """Cells for a solid narrower than a block: along each axis, the cells whose centres
        it covers, or else the one cell holding its middle, so thin solids never vanish."""
        f = out.frame
        mask = np.zeros((out.grid.size_x, out.grid.size_z), dtype=bool)
        xs = [float(p[0]) for p in polygon]
        zs = [float(p[1]) for p in polygon]

        def cells(fwd: Callable[[float], float], lo: float, hi: float, size: int) -> range:
            a, b = fwd(lo), fwd(hi)
            r = range(max(0, math.ceil(a - 0.5)), min(size, math.floor(b - 0.5) + 1))
            if len(r) == 0:
                m = math.floor((a + b) / 2)
                r = range(m, m + 1) if 0 <= m < size else range(0)
            return r

        rx = cells(f.fx, min(xs), max(xs), out.grid.size_x)
        rz = cells(f.fz, min(zs), max(zs), out.grid.size_z)
        if len(rx) and len(rz):
            mask[rx.start : rx.stop, rz.start : rz.stop] = True
        return mask

    def _fill_columns(self, out: Compiled, mask: np.ndarray, layers: range, state: str | None) -> None:
        g = out.grid
        sid = g.state_id(state)
        for y in layers:
            if 0 <= y < g.size_y:
                g.cells[:, y, :][mask] = sid

    def _terrain(self, out: Compiled) -> None:
        terrain = self.data.get("terrain")
        if not terrain:
            return
        g, f = out.grid, out.frame
        depth = int(terrain.get("depth", 1))
        top = out.ground_layer - 1
        mask = np.ones((g.size_x, g.size_z), dtype=bool)
        if terrain.get("polygon"):
            mask = self._footprint(out, terrain["polygon"])
        surface = self.material(terrain.get("material", "minecraft:grass_block"))
        below = self.material(terrain.get("below", "minecraft:dirt"))
        self._fill_columns(out, mask, range(top - depth + 1, top), below)
        self._fill_columns(out, mask, range(top, top + 1), surface)

    # A box or slab: any footprint between two heights.
    def _part_slab(self, out: Compiled, part: dict) -> None:
        mask = self._footprint(out, part["polygon"])
        if not mask.any():
            mask = self._thin_footprint(out, part["polygon"])
        layers = out.frame.layers(self.elevation(part["bottom"]), self.elevation(part["top"]))
        self._fill_columns(out, mask, layers, self.material(part.get("material")))

    _part_box = _part_slab

    def _part_clear(self, out: Compiled, part: dict) -> None:
        mask = self._footprint(out, part["polygon"])
        layers = out.frame.layers(self.elevation(part["bottom"]), self.elevation(part["top"]))
        self._fill_columns(out, mask, layers, None)

    def _part_room(self, out: Compiled, part: dict) -> None:
        """Clears a room's air space and lays its floor finish in the layer under the floor."""
        f = out.frame
        mask = self._footprint(out, part["polygon"])
        floor = self.elevation(part["floor"])
        ceiling = self.elevation(part["ceiling"]) if "ceiling" in part else None
        if part.get("clear", False):
            self._fill_columns(out, mask, f.layers(floor, ceiling), None)
        if part.get("finish"):
            fy = f.cy(floor) - 1
            self._fill_columns(out, mask, range(fy, fy + 1), self.material(part["finish"]))
        if part.get("ceiling_finish") and ceiling is not None:
            cy = f.cy(ceiling)
            self._fill_columns(out, mask, range(cy, cy + 1), self.material(part["ceiling_finish"]))
        cells = np.argwhere(mask)
        info = {
            "name": part.get("name", f"room {len(out.rooms) + 1}"),
            "floor_layer": f.cy(floor),
            "ceiling_layer": f.cy(ceiling) if ceiling is not None else None,
            "cells": int(mask.sum()),
        }
        if len(cells):
            info["min"] = [int(cells[:, 0].min()), int(cells[:, 1].min())]
            info["max"] = [int(cells[:, 0].max()), int(cells[:, 1].max())]
        else:
            out.warnings.append(f"room {info['name']!r} covers no cell centre")
        if part.get("camera") is not None:
            info["camera"] = part["camera"]
        if part.get("reachable") is not None:
            info["reachable"] = part["reachable"]
        out.rooms.append(info)
        out.room_masks.append(mask)

    def _wall_extents(self, part: dict, scale: float) -> tuple[float, float]:
        """How far a wall reaches to the left and right of its path.

        With ``round`` quantisation a wall thinner than a block is widened to one block;
        when the wall knows its outside, the outer face stays put and the wall grows
        inwards, so the building's outside dimensions stay true. With ``ceil`` the warp
        already gives every wall band its own block, so the true thickness is kept.
        """
        t = float(part["thickness"])
        width = t if self.quantize == "ceil" else max(t, scale)
        outside = part.get("outside")
        if outside == "left":
            return t / 2, width - t / 2
        if outside == "right":
            return width - t / 2, t / 2
        return width / 2, width / 2

    def _line_cells(self, out: Compiled, a: Point, b: Point) -> np.ndarray:
        f = out.frame
        mask = np.zeros((out.grid.size_x, out.grid.size_z), dtype=bool)
        steps = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) / 5) + 1)
        for t in np.linspace(0, 1, steps):
            x, z = f.cell_of(a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t)
            if 0 <= x < mask.shape[0] and 0 <= z < mask.shape[1]:
                mask[x, z] = True
        return mask

    def _segment_mask(self, out: Compiled, part: dict, a: Point, b: Point) -> np.ndarray:
        f = out.frame
        left, right = self._wall_extents(part, f.scale)
        extra = float(part["thickness"]) / 2
        # Each segment runs on past its ends so corners close.
        band = segment_band(a, b, left, right, start_extra=extra, end_extra=extra)
        mask = polygon_mask(band, f.centres_x(), f.centres_z())
        if not mask.any():  # a band between cell centres keeps the cells its centre line crosses
            mask = self._line_cells(out, a, b)
        return mask

    def _wall_mask(self, out: Compiled, part: dict, path: list[Point]) -> np.ndarray:
        mask = np.zeros((out.grid.size_x, out.grid.size_z), dtype=bool)
        for a, b in zip(path, path[1:]):
            mask |= self._segment_mask(out, part, a, b)
        return mask

    def _part_wall(self, out: Compiled, part: dict) -> None:
        f = out.frame
        path = [(float(x), float(z)) for x, z in part["path"]]
        if part.get("closed"):
            path.append(path[0])
        if self._is_edge(part):
            self._edge_wall(out, part, path)
            return
        layers = f.layers(self.elevation(part["bottom"]), self.elevation(part["top"]))
        material = self.material(part.get("material"))
        glazed = self._is_glazed(part)
        body = self.material(part.get("glass", "glass_pane")) if glazed else material
        seg_masks = [self._segment_mask(out, part, a, b) for a, b in zip(path, path[1:])]
        mask = np.logical_or.reduce(seg_masks)
        self._fill_columns(out, mask, layers, body)
        plans, pillars = self._plan_openings(out, part, path, seg_masks)
        if glazed:
            # frame pillars at the corners and between openings; the rest is glass
            cells = np.argwhere(mask)
            for p in path:
                px, pz = f.fx(p[0]), f.fz(p[1])
                d = (cells[:, 0] + 0.5 - px) ** 2 + (cells[:, 1] + 0.5 - pz) ** 2
                x, z = cells[int(d.argmin())]
                pillars[x, z] = True
            self._fill_columns(out, pillars & mask, layers, material)
        for opening, cut in plans:
            self._opening(out, part, path, opening, cut)

    def _plan_openings(self, out: Compiled, wall: dict, path: list[Point], seg_masks: list[np.ndarray]) -> tuple[list, np.ndarray]:
        """The cells of every opening, keeping a pillar wherever the plan has wall between them.

        Openings on an axis-aligned segment are mapped through the warp; when rounding
        would make two neighbouring openings touch although the plan has a pier between
        them, the wider one gives up a block, so piers and corner posts never vanish.
        """
        f = out.frame
        size = (out.grid.size_x, out.grid.size_z)
        pillars = np.zeros(size, dtype=bool)
        items = []
        for opening in wall.get("openings") or []:
            seg, start = self._locate(path, float(opening["at"]))
            items.append({"o": opening, "seg": seg, "d0": start, "d1": start + float(opening["width"])})
        result = []
        for seg in sorted({it["seg"] for it in items}):
            a, b = path[seg], path[seg + 1]
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            ux, uz = (b[0] - a[0]) / length, (b[1] - a[1]) / length
            its = [it for it in items if it["seg"] == seg]
            if abs(uz) < 1e-6 or abs(ux) < 1e-6:
                k = 0 if abs(uz) < 1e-6 else 1
                fwd = f.fx if k == 0 else f.fz
                u = ux if k == 0 else uz
                lo_v, hi_v = sorted((a[k], b[k]))
                first, last = math.floor(fwd(lo_v)), math.ceil(fwd(hi_v) - 1e-9) - 1
                for it in its:
                    v0, v1 = sorted((a[k] + u * it["d0"], a[k] + u * it["d1"]))
                    i0, i1 = round(fwd(v0)), round(fwd(v1))
                    if i1 <= i0:
                        i0 = math.floor(fwd((v0 + v1) / 2))
                        i1 = i0 + 1
                    if v0 > lo_v + 1 and i0 <= first and i1 - i0 > 1:
                        i0 = first + 1
                    if v1 < hi_v - 1 and i1 > last and i1 - i0 > 1:
                        i1 = last
                    it.update(v0=v0, v1=v1, r=[i0, i1])
                ordered = sorted(its, key=lambda it: (it["v0"], -it["v1"]))
                seg_pillars = np.zeros(size, dtype=bool)
                prev = None
                floor_at = first + 1  # lowest cell an opening may take: corner post / last pier kept
                for n, it in enumerate(ordered):
                    if prev is not None and it["v0"] - prev["v1"] > 1:
                        A, B = prev["r"], it["r"]
                        nxt = ordered[n + 1]["r"][0] - 1 if n + 1 < len(ordered) else last
                        need = A[1] + 1 - B[0]
                        while need > 0:
                            if A[1] - A[0] >= B[1] - B[0] and A[1] - A[0] > 1:
                                A[1] -= 1
                            elif B[1] - B[0] > 1:
                                B[0] += 1
                            elif A[0] - 1 >= floor_at:  # both one block wide: slide one aside
                                A[0] -= 1
                                A[1] -= 1
                            elif B[1] + 1 <= nxt:
                                B[0] += 1
                                B[1] += 1
                            else:
                                out.warnings.append(f"wall {wall.get('name', '')!r}: no room for the pier at {round(prev['v1'])}-{round(it['v0'])} cm")
                                break
                            need -= 1
                        if k == 0:
                            seg_pillars[A[1] : B[0], :] = True
                        else:
                            seg_pillars[:, A[1] : B[0]] = True
                    if prev is None or it["v1"] > prev["v1"]:
                        if prev is not None:
                            floor_at = max(floor_at, prev["r"][1] + 1)
                        prev = it
                for it in its:
                    along = np.zeros(size, dtype=bool)
                    if k == 0:
                        along[it["r"][0] : it["r"][1], :] = True
                    else:
                        along[:, it["r"][0] : it["r"][1]] = True
                    result.append((it["o"], seg_masks[seg] & along))
                pillars |= seg_pillars & seg_masks[seg]
            else:
                left, right = self._wall_extents(wall, f.scale)
                for it in its:
                    p0 = (a[0] + ux * it["d0"], a[1] + uz * it["d0"])
                    p1 = (a[0] + ux * it["d1"], a[1] + uz * it["d1"])
                    cut = polygon_mask(segment_band(p0, p1, left + 1, right + 1), f.centres_x(), f.centres_z())
                    if it["d1"] - it["d0"] < f.scale:  # never lose a narrow opening
                        mx, mz = f.cell_of((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2)
                        if 0 <= mx < size[0] and 0 <= mz < size[1]:
                            cut[mx, mz] = True
                    result.append((it["o"], cut & seg_masks[seg]))
        return result, pillars

    def _edge_wall(self, out: Compiled, part: dict, path: list[Point]) -> None:
        """A thin partition as open trapdoors against the block edge it stands on.

        The panel goes in the cell on the east / south of the line (``side`` picks the
        other one), or on the other side where that cell is already solid. Doors hang in
        the same plane, so a partition takes no block from either room.
        """
        f, g = out.frame, out.grid
        bottom, top = self.elevation(part["bottom"]), self.elevation(part["top"])
        layers = f.layers(bottom, top)
        panel = split_state(self.material(part.get("panel", self.panel)))[0]
        door_default = part.get("door", "door")
        openings = []
        for o in part.get("openings") or []:
            seg, start = self._locate(path, float(o["at"]))
            openings.append((seg, start, start + float(o["width"]), o))
        prefer = part.get("side")
        for si, (a, b) in enumerate(zip(path, path[1:])):
            vertical = abs(a[0] - b[0]) < 0.5
            if vertical:
                line, fwd, va, vb = f.cx(a[0]), f.fz, a[1], b[1]
                sides = [("east", line), ("west", line - 1)]
            else:
                line, fwd, va, vb = f.cz(a[1]), f.fx, a[0], b[0]
                sides = [("south", line), ("north", line - 1)]
            if prefer in ("west", "north"):
                sides.reverse()
            sign = 1 if vb >= va else -1
            lo, hi = sorted((va, vb))
            i0, i1 = round(fwd(lo)), round(fwd(hi))
            at_cell: dict[int, dict] = {}
            hinge_of: dict[int, str] = {}
            for seg, d0, d1, o in openings:
                if seg != si:
                    continue
                w0, w1 = sorted((va + sign * d0, va + sign * d1))
                o0, o1 = round(fwd(w0)), round(fwd(w1))
                if o1 <= o0:
                    o0 = math.floor(fwd((w0 + w1) / 2))
                    o1 = o0 + 1
                for n, kk in enumerate(range(o0, o1)):
                    at_cell[kk] = o
                    hinge_of[kk] = "left" if n % 2 == 0 else "right"
            for kk in range(i0, i1):
                choice = None
                for facing, across in sides:
                    x, z = (across, kk) if vertical else (kk, across)
                    if not g.in_bounds(x, layers.start, z):
                        continue
                    if choice is None:
                        choice = (facing, x, z)
                    if not is_full(g.get(x, layers.start, z)):
                        choice = (facing, x, z)
                        break
                if choice is None:
                    continue
                facing, x, z = choice
                o = at_cell.get(kk)
                o_layers = f.layers(self.elevation(o.get("bottom", part["bottom"])), self.elevation(o["top"])) if o else range(0)
                kind = o.get("kind", "window") if o else None
                for y in layers:
                    current = g.get(x, y, z)
                    if is_full(current) or not (current == AIR or current.split("[")[0].endswith(("_trapdoor", "_door"))):
                        continue
                    if y in o_layers:
                        if kind == "door" and y < o_layers.start + 2:
                            door = split_state(self.material(o.get("material", door_default)))[0]
                            half = "lower" if y == o_layers.start else "upper"
                            g.set(x, y, z, join_state(door, {"facing": facing, "half": half, "hinge": hinge_of[kk], "open": "false", "powered": "false"}))
                            continue
                        if kind == "hole":
                            continue
                        if kind != "door":
                            g.set(x, y, z, self.material(o.get("material", "glass_pane")))
                            continue
                    g.set(x, y, z, join_state(panel, {"facing": facing, "half": "bottom", "open": "true", "powered": "false", "waterlogged": "false"}))

    def _locate(self, path: list[Point], distance: float) -> tuple[int, float]:
        run = 0.0
        for i, (a, b) in enumerate(zip(path, path[1:])):
            length = math.hypot(b[0] - a[0], b[1] - a[1])
            if distance <= run + length + 1e-6:
                return i, distance - run
            run += length
        raise ModelError(f"opening at {distance} cm is past the end of the wall ({run} cm)")

    def _opening(self, out: Compiled, wall: dict, path: list[Point], opening: dict, cut: np.ndarray) -> None:
        f, g = out.frame, out.grid
        seg, _ = self._locate(path, float(opening["at"]))
        a, b = path[seg], path[seg + 1]
        length = math.hypot(b[0] - a[0], b[1] - a[1])
        ux, uz = (b[0] - a[0]) / length, (b[1] - a[1]) / length
        bottom, top = self.elevation(opening.get("bottom", wall["bottom"])), self.elevation(opening["top"])
        layers = f.layers(bottom, top)
        kind = opening.get("kind", "window")
        # Seen from above with north up, the left of travel is (uz, -ux); "outside" names that side.
        normal = (uz, -ux)
        outside = opening.get("outside", wall.get("outside", "left"))
        if outside == "right":
            normal = (-uz, ux)
        face_out = facing_of(*normal)
        self._fill_columns(out, cut, layers, None)
        if kind == "hole":
            return
        cells = np.argwhere(cut)
        if not len(cells):
            out.warnings.append(f"opening at {opening['at']} in wall {wall.get('name', '')!r} covers no cell")
            return
        # The plane the glass or door sits in: the wall layer at the chosen side.
        along_x = abs(ux) >= abs(uz)
        depth_values = cells[:, 1] if along_x else cells[:, 0]
        plane = opening.get("plane", "center")
        if plane == "center":
            target = sorted(set(depth_values))[len(set(depth_values)) // 2]
        else:
            side = 1 if (normal[1] if along_x else normal[0]) > 0 else -1
            if plane == "inside":
                side = -side
            target = max(depth_values) if side > 0 else min(depth_values)
        cells = cells[depth_values == target]
        lo, hi = layers.start, layers.stop
        if kind == "door":
            material = opening.get("material", wall.get("door", "door"))
            door = split_state(self.material(material))[0]
            ordered = sorted(cells.tolist(), key=lambda c: (c[0] * ux + c[1] * uz))
            for i, (x, z) in enumerate(ordered):
                hinge = "left" if (i % 2 == 0) else "right"
                props = {"facing": opening.get("facing", OPPOSITE[face_out] if opening.get("swing", "in") == "in" else face_out), "open": "false", "powered": "false"}
                g.set(x, lo, z, join_state(door, {**props, "half": "lower", "hinge": hinge}))
                g.set(x, lo + 1, z, join_state(door, {**props, "half": "upper", "hinge": hinge}))
                for y in range(lo + 2, hi):
                    g.set(x, y, z, self.material(opening.get("transom", wall.get("glass", "glass_pane"))))
            return
        if kind == "garage":
            material = self.material(opening.get("material", wall.get("garage", "garage_door")))
            for x, z in cells.tolist():
                for y in range(lo, hi):
                    g.set(x, y, z, material)
            return
        glass = self.material(opening.get("material", wall.get("glass", "glass_pane")))
        for x, z in cells.tolist():
            for y in range(lo, hi):
                g.set(x, y, z, glass)
        if opening.get("sill"):
            sill = self.material(opening["sill"])
            for x, z in cells.tolist():
                g.set(x, lo - 1, z, sill)

    # Mono-pitch (shed) roof: the surface rises from the ``low`` edge at ``slope`` (rise/run).
    def _roof_surface(self, part: dict, x: np.ndarray, z: np.ndarray) -> np.ndarray:
        dx, dz = CARDINALS[part["rises"]]
        poly = part["polygon"]
        # distance from the low edge measured along the rise direction
        along = [p[0] * dx + p[1] * dz for p in poly]
        start = min(along)
        d = x[:, None] * dx + z[None, :] * dz - start
        slope = float(part.get("slope", 0))
        return self.elevation(part["low"]) + d * slope

    def _roof_peak(self, part: dict) -> float:
        dx, dz = CARDINALS[part["rises"]]
        along = [p[0] * dx + p[1] * dz for p in part["polygon"]]
        return self.elevation(part["low"]) + (max(along) - min(along)) * float(part.get("slope", 0))

    def _part_roof(self, out: Compiled, part: dict) -> None:
        f, g = out.frame, out.grid
        mask = self._footprint(out, part["polygon"])
        surface = self._roof_surface(part, f.centres_x(), f.centres_z())
        thickness = float(part.get("thickness", f.scale))
        material = part.get("material")
        block = self.material(material)
        smooth = part.get("smooth", "slabs")
        slab = self.material_variant(material, "slab") if smooth == "slabs" else None
        stairs = self.material_variant(material, "stairs") if smooth == "stairs" else None
        if smooth == "stairs" and not stairs:
            raise ModelError(f"smooth: stairs needs a stairs variant of {material!r} in the palette")
        under = self.material(part["underside"]) if part.get("underside") else block
        cover = self.material(part["cover"]) if part.get("cover") and part.get("underside") else None
        # ``down_to`` fills the roof body down to a fixed elevation (a flat ceiling under a sloped roof)
        down_to = f.cy(self.elevation(part["down_to"])) if part.get("down_to") is not None else None
        tops: dict[tuple[int, int], int] = {}
        for x, z in np.argwhere(mask):
            x, z = int(x), int(z)
            t = f.fy(surface[x, z])  # roof surface, in layers
            n = math.floor(t)
            frac = t - n
            top_full = n + 1 if frac >= 0.75 else n
            bottom = down_to if down_to is not None else f.cy(surface[x, z] - thickness)
            bottom = min(bottom, top_full - 1)
            # A one-layer roof is ceiling and roofing at once: the underside shows indoors and a
            # thin ``cover`` (a carpet) gives the roof its colour from outside.
            single = cover is not None and bottom == top_full - 1
            for y in range(bottom, top_full):
                g.set(x, y, z, block if y == top_full - 1 and not single else under)
            if single and g.in_bounds(x, top_full, z) and g.get(x, top_full, z) == AIR:
                g.set(x, top_full, z, cover)
            elif slab and 0.25 <= frac < 0.75:
                g.set(x, top_full, z, join_state(split_state(slab)[0], {"type": "bottom"}))
            tops[(x, z)] = top_full
        if stairs:
            # each step of a sloped roof becomes a stair facing uphill, so the slope reads
            # as a slope rather than as flat terraces
            rises = part["rises"]
            dx, dz = CARDINALS[rises]
            stair = join_state(split_state(stairs)[0], {"facing": rises, "half": "bottom", "shape": "straight"})
            for (x, z), top in tops.items():
                up = tops.get((x + dx, z + dz))
                if up is not None and up > top and g.in_bounds(x, top, z) and g.get(x, top, z) in (AIR, cover):
                    g.set(x, top, z, stair)

    def _part_stair(self, out: Compiled, part: dict) -> None:
        """A straight flight starting at ``at`` (the first riser's centre) climbing ``direction``."""
        f, g = out.frame, out.grid
        direction = part["direction"]
        dx, dz = CARDINALS[direction]
        lo, hi = self.elevation(part["from"]), self.elevation(part["to"])
        steps = f.cy(hi) - f.cy(lo)
        if steps <= 0:
            raise ModelError("a stair must climb")
        x0, z0 = (float(v) for v in part["at"])
        width = max(1, int(round(float(part.get("width", 100)) / f.scale)))
        material = part.get("material")
        stairs = self.material_variant(material, "stairs") or self.material(material)
        support = self.material(part["support"]) if part.get("support") else None
        sx, sz = f.cell_of(x0, z0)
        px, pz = -dz, dx  # across the flight
        offset = -(width // 2) if part.get("align", "center") == "center" else 0
        base = f.cy(lo)
        headroom = int(part.get("headroom", 3))
        for i in range(steps):
            for w in range(width):
                x = sx + dx * i + px * (w + offset)
                z = sz + dz * i + pz * (w + offset)
                y = base + i
                g.set(x, y, z, join_state(split_state(stairs)[0], {"facing": direction, "half": "bottom", "shape": "straight"}) if "_stairs" in stairs else stairs)
                for h in range(1, headroom + 1):
                    g.set(x, y + h, z, None)
                if support:
                    for yy in range(base, y):
                        g.set(x, yy, z, support)
        # Landing: a game flight is shorter than the real one (one block of rise per block of
        # run), so floor the rest of the well until it meets the storey floor.
        top = base + steps - 1
        for w in range(width):
            for k in range(steps, steps + 16):
                x = sx + dx * k + px * (w + offset)
                z = sz + dz * k + pz * (w + offset)
                if not g.in_bounds(x, top, z) or g.get(x, top, z) != AIR:
                    break
                g.set(x, top, z, self.material(material))

    def _part_spiral_stair(self, out: Compiled, part: dict) -> None:
        """A spiral stair around a centre column, one step per block of rise."""
        f, g = out.frame, out.grid
        cx, cz = (float(v) for v in part["center"])
        radius = float(part["radius"])
        lo, hi = self.elevation(part["from"]), self.elevation(part["to"])
        steps = f.cy(hi) - f.cy(lo)
        start = math.radians(float(part.get("start_angle", 0)))  # 0 = east, 90 = south
        turn = 1 if part.get("turn", "clockwise") == "clockwise" else -1
        material = part.get("material")
        stair_block = self.material_variant(material, "stairs") or self.material(material)
        slab_block = self.material_variant(material, "slab")
        column = self.material(part.get("column", material))
        mx, mz = f.cell_of(cx, cz)
        base = f.cy(lo)
        mask = polygon_mask(
            [(cx + radius * math.cos(a), cz + radius * math.sin(a)) for a in np.linspace(0, 2 * math.pi, 48, endpoint=False)],
            f.centres_x(),
            f.centres_z(),
        )
        # clear the shaft
        self._fill_columns(out, mask, range(base, f.cy(hi)), None)
        cells = [(int(x), int(z)) for x, z in np.argwhere(mask) if (int(x), int(z)) != (mx, mz)]
        angle_of = {c: (turn * (math.atan2(f.wz.inv(c[1] + 0.5) - cz, f.wx.inv(c[0] + 0.5) - cx) - start)) % (2 * math.pi) for c in cells}
        order = sorted(cells, key=lambda c: angle_of[c])
        if len(order) < 3:
            raise ModelError(f"spiral stair radius {radius} cm leaves {len(order)} step cells around the column; at least 3 are needed")
        per_turn = len(order)
        for i in range(steps):
            y = base + i
            c = order[i % per_turn]
            nxt = order[(i + 1) % per_turn]
            facing = facing_of(nxt[0] - c[0], nxt[1] - c[1])
            if "_stairs" in stair_block:
                g.set(c[0], y, c[1], join_state(split_state(stair_block)[0], {"facing": facing, "half": "bottom", "shape": "straight"}))
            else:
                g.set(c[0], y, c[1], stair_block)
            if slab_block and i > 0:
                prev = order[(i - 1) % per_turn]
                if g.get(prev[0], y, prev[1]) == AIR:
                    g.set(prev[0], y, prev[1], join_state(split_state(slab_block)[0], {"type": "top"}))
        for y in range(base, f.cy(hi)):
            g.set(mx, y, mz, column)

    def _part_block(self, out: Compiled, part: dict) -> None:
        """One block (or a line of them) at a plan point and elevation."""
        f, g = out.frame, out.grid
        x, z = f.cell_of(float(part["at"][0]), float(part["at"][1]))
        y = f.cy(self.elevation(part.get("elevation", 0)))
        state = self.material(part.get("material", part.get("state")))
        count = int(part.get("count", 1))
        dx, dz = CARDINALS.get(part.get("direction", "east"), (1, 0))
        height = int(part.get("height", 1))
        for i in range(count):
            for h in range(height):
                g.set(x + dx * i, y + h, z + dz * i, state)

    def _part_bed(self, out: Compiled, part: dict) -> None:
        """A bed whose head is at ``at``, with the sleeper's head towards ``facing``."""
        f, g = out.frame, out.grid
        x, z = f.cell_of(float(part["at"][0]), float(part["at"][1]))
        y = f.cy(self.elevation(part.get("elevation", 0)))
        facing = part["facing"]
        dx, dz = CARDINALS[facing]
        block = split_state(self.material(part.get("material", "minecraft:white_bed")))[0]
        width = int(part.get("width", 1))
        px, pz = -dz, dx
        for w in range(width):
            hx, hz = x + px * w, z + pz * w
            g.set(hx, y, hz, join_state(block, {"facing": facing, "part": "head", "occupied": "false"}))
            g.set(hx - dx, y, hz - dz, join_state(block, {"facing": facing, "part": "foot", "occupied": "false"}))


def connect(grid: Grid) -> None:
    """Sets the side properties of panes, bars, fences and walls from their neighbours.

    Pasting does not update neighbours, so connections must already be in the states.
    """
    sides = {"north": (0, 0, -1), "south": (0, 0, 1), "east": (1, 0, 0), "west": (-1, 0, 0)}
    connecting_ids = [i for i, s in enumerate(grid.palette) if connects(s)]
    if not connecting_ids:
        return
    full = np.array([is_full(s) for s in grid.palette])
    joins = np.array([connects(s) for s in grid.palette])
    glassy = np.array([split_state(s)[0].endswith("glass") for s in grid.palette])
    cells = grid.cells
    updates = []
    for x, y, z in np.argwhere(np.isin(cells, connecting_ids)):
        state = grid.palette[int(cells[x, y, z])]
        name, props = split_state(state)
        for side, (dx, _, dz) in sides.items():
            nx, nz = x + dx, z + dz
            other = int(cells[nx, y, nz]) if 0 <= nx < grid.size_x and 0 <= nz < grid.size_z else 0
            on = bool(full[other] or joins[other] or glassy[other])
            if name.endswith("_wall"):
                props[side] = "low" if on else "none"
            else:
                props[side] = "true" if on else "false"
        if name.endswith("_wall"):
            above = int(cells[x, y + 1, z]) if y + 1 < grid.size_y else 0
            straight = (props["north"] != "none") == (props["south"] != "none") and (props["east"] != "none") == (props["west"] != "none") and (props["north"] != "none") != (props["east"] != "none")
            props["up"] = "false" if straight and not full[above] else "true"
        updates.append((x, y, z, join_state(name, props)))
    for x, y, z, state in updates:
        grid.cells[x, y, z] = grid.state_id(state)
