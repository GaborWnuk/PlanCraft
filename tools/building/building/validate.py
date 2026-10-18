"""Checks a compiled grid before it goes anywhere near the game.

Errors make a build unusable (unknown blocks, half doors); warnings point at things
that are usually mistakes (rooms nobody can walk into, rooms too low to stand in).
"""

from __future__ import annotations

from collections import deque

import numpy as np

from . import registry
from .grid import AIR, Grid, split_state

CARDINAL = {"north": (0, -1), "south": (0, 1), "east": (1, 0), "west": (-1, 0)}

_NO_COLLISION = (
    "_door",  # walkable: doors open
    "_carpet",
    "torch",
    "_button",
    "_sign",
    "_banner",
    "_pressure_plate",
    "flower",
    "short_grass",
    "fern",
    "rail",
    "lever",
    "ladder",
    "vine",
    "_sapling",
    "tripwire",
    "redstone_wire",
)
_NO_COLLISION_EXACT = {"minecraft:light"}  # the invisible light block, not light_gray_* or light_blue_*
_STEP = ("_stairs", "_slab")


def _open(state: str) -> bool:
    if state == AIR:
        return True
    name = split_state(state)[0]
    return name in _NO_COLLISION_EXACT or any(token in name for token in _NO_COLLISION)


def _step(state: str) -> bool:
    name, props = split_state(state)
    return name.endswith(_STEP) and props.get("half", props.get("type", "bottom")) == "bottom"


def check_states(grid: Grid) -> list[str]:
    errors = []
    for state in grid.palette[1:]:
        problem = registry.validate_state(state)
        if problem:
            errors.append(problem)
    return errors


def check_pairs(grid: Grid, limit: int = 20) -> list[str]:
    """Doors need both halves and beds both parts, matching each other."""
    errors: list[str] = []
    for x, y, z, state in grid.non_air():
        name, props = split_state(state)
        if name.endswith("_door"):
            other_y = y + 1 if props.get("half") == "lower" else y - 1
            other = grid.get(x, other_y, z)
            oname, oprops = split_state(other)
            if oname != name or oprops.get("half") == props.get("half") or oprops.get("facing") != props.get("facing"):
                errors.append(f"door at {x},{y},{z} has no matching {'upper' if props.get('half') == 'lower' else 'lower'} half")
        elif name.endswith("_bed"):
            dx, dz = CARDINAL[props["facing"]]
            sign = -1 if props.get("part") == "head" else 1
            oname, oprops = split_state(grid.get(x + sign * dx, y, z + sign * dz))
            if oname != name or oprops.get("part") == props.get("part") or oprops.get("facing") != props.get("facing"):
                errors.append(f"bed at {x},{y},{z} is missing its {'foot' if sign < 0 else 'head'}")
        if len(errors) >= limit:
            errors.append("...")
            break
    return errors


def _panel_edges(grid: Grid) -> dict[int, tuple[int, int]]:
    """Open trapdoors used as partitions: palette id -> the cell edge (dx, dz) they close."""
    out = {}
    for i, state in enumerate(grid.palette):
        name, props = split_state(state)
        if name.endswith("_trapdoor") and props.get("open") == "true" and props.get("facing") in CARDINAL:
            fx, fz = CARDINAL[props["facing"]]
            out[i] = (-fx, -fz)
    return out


def reachable(grid: Grid, ground_layer: int, max_drop: int = 3) -> np.ndarray:
    """Cells a player can stand in, flood-filled from the outer edge of the ground."""
    panels = _panel_edges(grid)
    open_ids = np.array([_open(s) or i in panels for i, s in enumerate(grid.palette)])
    step_ids = np.array([_step(s) for s in grid.palette])
    cells = grid.cells
    is_open = open_ids[cells]
    feet_ok = is_open | step_ids[cells]
    head_ok = np.zeros_like(is_open)
    head_ok[:, :-1, :] = is_open[:, 1:, :]
    below_solid = np.zeros_like(is_open)
    below_solid[:, 1:, :] = ~is_open[:, :-1, :]
    below_solid[:, 0, :] = True
    # standing on a step: feet are in the step cell, supported by it
    stand = feet_ok & head_ok & (below_solid | step_ids[cells])

    sx, sy, sz = grid.shape

    def walled(x: int, y: int, z: int, dx: int, dz: int) -> bool:
        """A partition panel between this cell and its neighbour, at feet or head height."""
        for k in (y, y + 1):
            if 0 <= k < sy:
                if panels.get(int(cells[x, k, z])) == (dx, dz):
                    return True
                if panels.get(int(cells[x + dx, k, z + dz])) == (-dx, -dz):
                    return True
        return False

    seen = np.zeros_like(stand)
    queue: deque[tuple[int, int, int]] = deque()
    for y in range(max(0, ground_layer - 1), min(sy, ground_layer + 2)):
        for x in range(sx):
            for z in (0, sz - 1):
                if stand[x, y, z] and not seen[x, y, z]:
                    seen[x, y, z] = True
                    queue.append((x, y, z))
        for z in range(sz):
            for x in (0, sx - 1):
                if stand[x, y, z] and not seen[x, y, z]:
                    seen[x, y, z] = True
                    queue.append((x, y, z))
    while queue:
        x, y, z = queue.popleft()
        for dx, dz in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, nz = x + dx, z + dz
            if not (0 <= nx < sx and 0 <= nz < sz):
                continue
            if panels and walled(x, y, z, dx, dz):
                continue
            # climbing one block needs headroom above the current cell
            for dy in (0, 1, *range(-1, -max_drop - 1, -1)):
                ny = y + dy
                if not (0 <= ny < sy) or seen[nx, ny, nz] or not stand[nx, ny, nz]:
                    continue
                if dy == 1 and (y + 2 >= sy or not is_open[x, y + 2, z]) and not step_ids[cells[nx, ny, nz]]:
                    continue
                # dropping down needs open space in the target column from head height down
                if dy < 0 and not all(is_open[nx, k, nz] for k in range(ny + 2, min(y + 2, sy))):
                    continue
                seen[nx, ny, nz] = True
                queue.append((nx, ny, nz))
                break
    # vertical moves inside stair shafts and ladders are covered by the dy = +1 rule
    return seen


def check_rooms(grid: Grid, rooms: list[dict], ground_layer: int) -> list[str]:
    warnings = []
    reach = reachable(grid, ground_layer)
    for room in rooms:
        if "min" not in room:
            continue
        (x0, z0), (x1, z1) = room["min"], room["max"]
        y = room["floor_layer"]
        if room.get("ceiling_layer") is not None and room["ceiling_layer"] - y < 2:
            warnings.append(f"{room['name']}: only {room['ceiling_layer'] - y} block(s) of headroom")
        if room.get("reachable", True) is False:
            continue
        if not (0 <= y < grid.size_y) or not reach[x0 : x1 + 1, y, z0 : z1 + 1].any():
            warnings.append(f"{room['name']}: cannot be walked into from outside")
    return warnings


def validate(grid: Grid, rooms: list[dict], ground_layer: int) -> dict:
    errors = check_states(grid) + check_pairs(grid)
    warnings = check_rooms(grid, rooms, ground_layer)
    return {"ok": not errors, "errors": errors, "warnings": warnings}
