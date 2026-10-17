"""A dense voxel grid of block states.

Axes follow Minecraft: x grows east, y grows up, z grows south. Each cell holds an
index into a palette of block-state strings such as ``minecraft:oak_stairs[facing=north]``;
index 0 is always air.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Iterator

import numpy as np

AIR = "minecraft:air"


def normalize_state(state: str) -> str:
    """Canonical block-state text: namespaced, with properties sorted by key."""
    state = state.strip()
    if ":" not in state.split("[", 1)[0]:
        state = "minecraft:" + state
    name, props = split_state(state)
    return join_state(name, props)


def split_state(state: str) -> tuple[str, dict[str, str]]:
    if "[" not in state:
        return state, {}
    name, rest = state.split("[", 1)
    if not rest.endswith("]"):
        raise ValueError(f"malformed block state: {state}")
    props: dict[str, str] = {}
    for part in rest[:-1].split(","):
        part = part.strip()
        if not part:
            continue
        key, _, value = part.partition("=")
        props[key.strip()] = value.strip()
    return name, props


def join_state(name: str, props: dict[str, str]) -> str:
    if not props:
        return name
    return name + "[" + ",".join(f"{k}={props[k]}" for k in sorted(props)) + "]"


@dataclass
class Grid:
    size_x: int
    size_y: int
    size_z: int
    palette: list[str] = field(default_factory=lambda: [AIR])

    def __post_init__(self) -> None:
        if min(self.size_x, self.size_y, self.size_z) <= 0:
            raise ValueError("grid dimensions must be positive")
        self._index = {s: i for i, s in enumerate(self.palette)}
        self.cells = np.zeros((self.size_x, self.size_y, self.size_z), dtype=np.uint16)

    @property
    def shape(self) -> tuple[int, int, int]:
        return self.size_x, self.size_y, self.size_z

    def state_id(self, state: str | None) -> int:
        if state is None:
            return 0
        state = normalize_state(state)
        if state == AIR:
            return 0
        found = self._index.get(state)
        if found is None:
            found = len(self.palette)
            self.palette.append(state)
            self._index[state] = found
        return found

    def in_bounds(self, x: int, y: int, z: int) -> bool:
        return 0 <= x < self.size_x and 0 <= y < self.size_y and 0 <= z < self.size_z

    def set(self, x: int, y: int, z: int, state: str | None) -> None:
        if self.in_bounds(x, y, z):
            self.cells[x, y, z] = self.state_id(state)

    def get(self, x: int, y: int, z: int) -> str:
        if not self.in_bounds(x, y, z):
            return AIR
        return self.palette[int(self.cells[x, y, z])]

    def fill(self, x0: int, y0: int, z0: int, x1: int, y1: int, z1: int, state: str | None) -> None:
        """Fills the inclusive box between two corners, clipped to the grid."""
        xa, xb = sorted((x0, x1))
        ya, yb = sorted((y0, y1))
        za, zb = sorted((z0, z1))
        xa, ya, za = max(xa, 0), max(ya, 0), max(za, 0)
        xb, yb, zb = min(xb, self.size_x - 1), min(yb, self.size_y - 1), min(zb, self.size_z - 1)
        if xa > xb or ya > yb or za > zb:
            return
        self.cells[xa : xb + 1, ya : yb + 1, za : zb + 1] = self.state_id(state)

    def set_mask(self, mask: np.ndarray, state: str | None) -> None:
        self.cells[mask] = self.state_id(state)

    def counts(self) -> Counter[str]:
        ids, counts = np.unique(self.cells, return_counts=True)
        return Counter({self.palette[int(i)]: int(c) for i, c in zip(ids, counts)})

    def non_air(self) -> Iterator[tuple[int, int, int, str]]:
        for x, y, z in zip(*np.nonzero(self.cells)):
            yield int(x), int(y), int(z), self.palette[int(self.cells[x, y, z])]

    def compact(self) -> "Grid":
        """A copy whose palette holds only the states still in use, in first-use order."""
        used = sorted({int(i) for i in np.unique(self.cells)} - {0})
        out = Grid(self.size_x, self.size_y, self.size_z)
        remap = np.zeros(len(self.palette), dtype=np.uint16)
        for old in used:
            remap[old] = out.state_id(self.palette[old])
        out.cells = remap[self.cells]
        return out
