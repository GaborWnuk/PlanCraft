"""Reading and writing builds in the buildpaste.net JSON form.

The tools always write builds facing north. Pasted by a player facing north, a build's
cell ``(x, y, z)`` lands at world ``(ox + 1 + x, oy + y, oz - size_z + 1 + z)`` for a
player standing at ``(ox, oy, oz)``, with no rotation applied to any block. That mirrors
``PlacementOrder`` and ``scanRegion`` in the mod: index ``i`` walks x, then y, then z,
with both x and z descending for the north direction.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache
from pathlib import Path

import numpy as np

from .grid import AIR, Grid, join_state, split_state

DIRECTION = "north"

REPO_ROOT = Path(__file__).resolve().parents[3]
BLOCK_TABLE_KT = REPO_ROOT / "src/main/kotlin/dev/gaborwnuk/buildpaste/protocol/BlockTable.kt"

# Properties the mod drops when it reads blocks from the world (BlockCodec.PROPERTY_BLACKLIST).
IGNORED_PROPERTIES = {("level", "0"), ("snowy", "false"), ("waterlogged", "true")}


@lru_cache(maxsize=1)
def block_table() -> tuple[list[str], dict[str, str]]:
    """The wire-id table and rename map, read from the mod source so the two cannot drift."""
    text = BLOCK_TABLE_KT.read_text(encoding="utf-8")
    names_block = text.split("val names: List<String> = listOf(", 1)[1].split(")", 1)[0]
    names = re.findall(r'"([a-z0-9_]+)"', names_block)
    renamed_block = text.split("private val RENAMED = mapOf(", 1)[1].split(")", 1)[0]
    renamed = dict(re.findall(r'"([a-z0-9_]+)" to "([a-z0-9_]+)"', renamed_block))
    return names, renamed


def resolve_block(value: str | int | float) -> str:
    names, renamed = block_table()
    if isinstance(value, (int, float)) or re.fullmatch(r"-?\d+(\.\d+)?", str(value)):
        idx = round(float(value))
        if 0 <= idx < len(names):
            name = names[idx]
            return "minecraft:" + renamed.get(name, name)
        return str(value)
    return str(value)


def walk(size_x: int, size_y: int, size_z: int):
    """Grid cell for each block index, for a build stored facing north."""
    xs = np.arange(size_x)[::-1]
    zs = np.arange(size_z)[::-1]
    for x in xs:
        for y in range(size_y):
            for z in zs:
                yield int(x), y, int(z)


def to_json(grid: Grid) -> dict:
    blocks: list[str] = []
    data: list[str | None] = []
    names = [split_state(s) for s in grid.palette]
    cells = grid.cells
    # Same order as walk(), done with array ops: x descending, then y, then z descending.
    ordered = cells[::-1, :, ::-1].reshape(-1)
    for sid in ordered:
        name, props = names[int(sid)]
        blocks.append(name)
        data.append("[" + ",".join(f"{k}={v}" for k, v in sorted(props.items())) + "]" if props else None)
    return {
        "blocks": blocks,
        "data": data,
        "size": [grid.size_x, grid.size_y, grid.size_z],
        "direction": DIRECTION,
        "nbt": {},
    }


def write(grid: Grid, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(to_json(grid), separators=(",", ":")), encoding="utf-8")
    return path


def read(path: Path) -> Grid:
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("direction") != DIRECTION:
        raise ValueError(f"only builds stored facing {DIRECTION} can be read, got {doc.get('direction')}")
    sx, sy, sz = doc["size"]
    grid = Grid(sx, sy, sz)
    flat = np.zeros(sx * sy * sz, dtype=np.uint16)
    for i, (block, props) in enumerate(zip(doc["blocks"], doc["data"])):
        name = resolve_block(block)
        if not name.startswith("minecraft:") and ":" not in name:
            name = "minecraft:" + name
        _, parsed = split_state("x" + props) if props else ("", {})
        parsed = {k: v for k, v in parsed.items() if k and (k, v) not in IGNORED_PROPERTIES}
        flat[i] = grid.state_id(join_state(name, parsed))
    grid.cells = flat.reshape(sx, sy, sz)[::-1, :, ::-1].copy()
    return grid


def diff(expected: Grid, actual: Grid, limit: int = 50) -> dict:
    """Compares a build with what the world reports back.

    A cell matches when the block names agree and every property the build asked for is
    present with the same value; the game fills in the rest with defaults.
    """
    if expected.shape != actual.shape:
        return {"ok": False, "reason": f"size {expected.shape} != {actual.shape}", "mismatches": []}

    def compatible(want: str, got: str) -> bool:
        wn, wp = split_state(want)
        gn, gp = split_state(got)
        if wn != gn:
            return False
        return all(gp.get(k) == v for k, v in wp.items() if (k, v) not in IGNORED_PROPERTIES)

    pairs: dict[tuple[int, int], bool] = {}
    mismatches = []
    total = 0
    e, a = expected.cells, actual.cells
    for x, y, z in zip(*np.nonzero((e != 0) | (a != 0))):
        key = (int(e[x, y, z]), int(a[x, y, z]))
        ok = pairs.get(key)
        if ok is None:
            ok = pairs[key] = compatible(expected.palette[key[0]], actual.palette[key[1]])
        if not ok:
            total += 1
            if len(mismatches) < limit:
                mismatches.append(
                    {"pos": [int(x), int(y), int(z)], "expected": expected.palette[key[0]], "actual": actual.palette[key[1]]}
                )
    return {"ok": total == 0, "mismatch_count": total, "mismatches": mismatches}
