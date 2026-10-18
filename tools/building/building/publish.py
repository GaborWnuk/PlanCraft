"""Getting a finished build out of the tools: buildpaste.net uploads and server pastes.

* ``plan_sections`` splits a build into stacked, lossless layer ranges whose upload
  payload stays under the server's limit (about 16 MB fails, 8.5 MB is known to work).
* ``verify_upload`` fetches an uploaded build back and compares it, cell by cell, with
  the matching part of the local build.
* ``fit`` says whether a paste from a given height stays inside the world.
* ``height_pack`` writes a datapack that raises the overworld build limit, generated
  from the version's own dimension type so no game data is kept in the repository.
"""

from __future__ import annotations

import json
import math
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

import numpy as np

from . import buildpaste, registry
from .grid import Grid

API_ROOT = "https://us-central1-buildpastemod.cloudfunctions.net/v1"
DEFAULT_LIMIT = 8_500_000
DEFAULT_TOP = 319
OVERWORLD_MIN_Y = -64
_AIR_TOKENS = {"0", '"minecraft:air"', '"air"'}


def _wire_ids() -> dict[str, int]:
    names, _ = buildpaste.block_table()
    ids: dict[str, int] = {}
    for i, name in enumerate(names):
        ids.setdefault(name, i)
    return ids


def _block_token(value, ids: dict[str, int]) -> str:
    """The block as the mod sends it: a table id, or the namespaced name when untabled."""
    if isinstance(value, (int, float)):
        return str(round(value))
    name = value.removeprefix("minecraft:")
    return str(ids[name]) if name in ids else json.dumps(value)


def _stored(doc: dict, values: list) -> np.ndarray:
    """Per-cell values reshaped to stored order: (x descending, y, z descending)."""
    sx, sy, sz = doc["size"]
    return np.asarray(values).reshape(sx, sy, sz)


def _costs_and_solid(doc: dict) -> tuple[np.ndarray, np.ndarray]:
    ids = _wire_ids()
    blocks = [_block_token(v, ids) for v in doc["blocks"]]
    data = doc.get("data") or [None] * len(blocks)
    cost = [len(b) + (4 if d is None else len(json.dumps(d))) + 2 for b, d in zip(blocks, data)]
    solid = [b not in _AIR_TOKENS for b in blocks]
    return _stored(doc, cost).astype(np.int64), _stored(doc, solid).astype(bool)


def _to_cells(solid: np.ndarray) -> np.ndarray:
    """Stored order to build-cell order (x and z ascending)."""
    return solid[::-1, :, ::-1]


def tight_bounds(doc: dict) -> dict:
    """Smallest box, in build cells, that holds every non-air block."""
    _, solid = _costs_and_solid(doc)
    return _bounds(_to_cells(solid))


def _bounds(cells: np.ndarray) -> dict:
    if not cells.any():
        raise ValueError("the build has no blocks")
    lo, hi = [], []
    for axis in range(3):
        others = tuple(a for a in range(3) if a != axis)
        used = np.nonzero(cells.any(axis=others))[0]
        lo.append(int(used[0]))
        hi.append(int(used[-1]))
    return {"min": lo, "max": hi, "size": [h - l + 1 for l, h in zip(lo, hi)]}


def plan_sections(doc: dict, limit: int = DEFAULT_LIMIT) -> dict:
    """Stacked layer ranges inside the tight box, each with an upload payload under ``limit``."""
    if doc.get("direction") != buildpaste.DIRECTION:
        raise ValueError(f"only builds stored facing {buildpaste.DIRECTION} are supported")
    cost, solid = _costs_and_solid(doc)
    cost, solid = _to_cells(cost), _to_cells(solid)
    box = _bounds(solid)
    (x0, y0, z0), (x1, y1, z1) = box["min"], box["max"]
    layers = cost[x0:x1 + 1, :, z0:z1 + 1].sum(axis=(0, 2))
    overhead = 200
    sections: list[dict] = []
    start, total = y0, overhead
    for y in range(y0, y1 + 1):
        layer = int(layers[y])
        if layer + overhead > limit:
            raise ValueError(f"layer {y} alone needs ~{layer} bytes, over the {limit} byte limit")
        if total + layer > limit:
            sections.append({"layers": [start, y - 1], "bytes": total})
            start, total = y, overhead
        total += layer
    sections.append({"layers": [start, y1], "bytes": total})
    count = len(sections)
    for k, s in enumerate(sections, 1):
        s["part"] = k
        s["min"] = [x0, s["layers"][0], z0]
        s["max"] = [x1, s["layers"][1], z1]
    return {
        "size": list(doc["size"]),
        "tight": box,
        "limit": limit,
        "single_upload": count == 1,
        "sections": sections,
    }


def world_pos(cell: list[int], origin: list[int], size_z: int) -> list[int]:
    """World position of a build cell pasted facing north by a player at ``origin``."""
    ox, oy, oz = origin
    x, y, z = cell
    return [ox + 1 + x, oy + y, oz - size_z + 1 + z]


def add_selections(plan: dict, origin: list[int]) -> dict:
    """Adds ``pos1``/``pos2`` world corners for each section of a build pasted at ``origin``."""
    sz = plan["size"][2]
    for s in plan["sections"]:
        s["pos1"] = world_pos(s["min"], origin, sz)
        s["pos2"] = world_pos(s["max"], origin, sz)
    return plan


def upload_name(title: str, part: int, count: int, stamp: str, note: str = "") -> str:
    """Upload title with a timestamp, since buildpaste.net shows no dates."""
    name = f"{title} {stamp}"
    if count > 1:
        name += f" part {part} of {count}"
    return f"{name} ({note})" if note else name


def fetch_build(build_id: str, timeout: float = 120) -> dict:
    url = f"{API_ROOT}/builds/get/{urllib.parse.quote(build_id, safe='')}"
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _sub(grid: Grid, lo: list[int], hi: list[int]) -> Grid:
    out = Grid(*(h - l + 1 for l, h in zip(lo, hi)), palette=list(grid.palette))
    out.cells = grid.cells[lo[0]:hi[0] + 1, lo[1]:hi[1] + 1, lo[2]:hi[2] + 1].copy()
    return out


def verify_upload(doc: dict, remote: dict, layers: list[int] | None = None) -> dict:
    """Compares an uploaded build with the matching layer range of the local build.

    The upload may be the whole size or the tight box in x and z; the game adds default
    properties when it reads blocks back, which ``diff`` accepts.
    """
    local = buildpaste.from_json(doc)
    got = buildpaste.from_json(remote)
    box = _bounds(local.cells != 0)
    a, b = layers if layers else (box["min"][1], box["max"][1])
    for lo_x, hi_x, lo_z, hi_z in (
        (box["min"][0], box["max"][0], box["min"][2], box["max"][2]),
        (0, local.size_x - 1, 0, local.size_z - 1),
    ):
        want = _sub(local, [lo_x, a, lo_z], [hi_x, b, hi_z])
        if want.shape == got.shape:
            result = buildpaste.diff(want, got)
            result["blocks"] = int(np.count_nonzero(want.cells))
            result["layers"] = [a, b]
            return result
    return {"ok": False, "reason": f"uploaded size {list(got.shape)} matches neither the tight box nor the "
                                    f"full width for layers {a}-{b}", "mismatches": []}


def fit(doc: dict, origin_y: int, top: int = DEFAULT_TOP, bottom: int = OVERWORLD_MIN_Y) -> dict:
    """Whether a paste whose ground layer lands at ``origin_y`` stays inside the world."""
    _, solid = _costs_and_solid(doc)
    cells = _to_cells(solid)
    box = _bounds(cells)
    first, last = box["min"][1], box["max"][1]
    per_layer = cells.sum(axis=(0, 2))
    above = max(top - origin_y + 1, 0)
    clipped = int(per_layer[above:].sum())
    below = max(bottom - origin_y, 0)
    clipped_below = int(per_layer[:below].sum())
    return {
        "origin_y": origin_y,
        "lowest_y": origin_y + first,
        "highest_y": origin_y + last,
        "world": [bottom, top],
        "fits": clipped == 0 and clipped_below == 0,
        "clipped_above": clipped,
        "clipped_below": clipped_below,
        "max_origin_y": top - last,
        "min_origin_y": bottom - first,
        "top_needed": origin_y + last,
    }


def height_pack(out_dir: Path, top: int, version: str = registry.DEFAULT_VERSION,
                name: str = "tall-overworld") -> Path:
    """Writes a datapack that keeps the overworld floor and raises its top to at least ``top``."""
    jar = registry._loom_dir(version) / "minecraft-client.jar"
    with zipfile.ZipFile(jar) as client:
        formats = json.loads(client.read("version.json"))["pack_version"]
        overworld = json.loads(client.read("data/minecraft/dimension_type/overworld.json"))
    min_y = int(overworld["min_y"])
    height = max(int(overworld["height"]), math.ceil((top + 1 - min_y) / 16) * 16)
    if height > 4064 or min_y + height > 2032:
        raise ValueError(f"a top of y {top} is beyond what the game allows")
    overworld["height"] = height
    overworld["logical_height"] = height
    pack = Path(out_dir) / name
    if pack.exists():
        raise FileExistsError(f"refusing to overwrite {pack}")
    target = pack / "data" / "minecraft" / "dimension_type"
    target.mkdir(parents=True)
    data_format = [formats["data_major"], formats["data_minor"]]
    (pack / "pack.mcmeta").write_text(json.dumps({"pack": {
        "description": f"Overworld build height y {min_y} to {min_y + height - 1}, for tall 1:1 buildings",
        "min_format": data_format,
        "max_format": formats["data_major"],
    }}, indent=2), encoding="utf-8")
    (target / "overworld.json").write_text(json.dumps(overworld, indent=2), encoding="utf-8")
    return pack
