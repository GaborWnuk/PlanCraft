"""Offline pictures of a grid, for checking a model before starting the game.

* ``plan``: one horizontal slice (head height above a floor shows walls, doors, windows).
* ``top``: the highest block in every column, shaded by height.
* ``elevation``: the first block seen from one side, shaded by depth.
* ``isometric``: a small 3D render from the south-east.

Colours are the average texture colours from the game's own jar.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from . import registry
from .grid import AIR, Grid

BACKGROUND = (250, 250, 248)


def palette_colors(grid: Grid) -> np.ndarray:
    out = np.zeros((len(grid.palette), 4), dtype=np.float32)
    for i, state in enumerate(grid.palette):
        out[i] = (0, 0, 0, 0) if state == AIR else registry.color(state)
    return out


def _canvas(colors: np.ndarray, px: int, grid_lines: bool = True) -> Image.Image:
    """colors: (w, h, 3) uint8 indexed [x, row]."""
    w, h = colors.shape[:2]
    img = Image.fromarray(np.transpose(colors, (1, 0, 2)).astype(np.uint8), "RGB").resize((w * px, h * px), Image.NEAREST)
    if grid_lines and px >= 6:
        draw = ImageDraw.Draw(img)
        for i in range(w + 1):
            draw.line([(i * px, 0), (i * px, h * px)], fill=(150, 150, 150) if i % 5 == 0 else (215, 215, 215))
        for j in range(h + 1):
            draw.line([(0, j * px), (w * px, j * px)], fill=(150, 150, 150) if j % 5 == 0 else (215, 215, 215))
    return img


def _blend(rgba: np.ndarray, under: np.ndarray) -> np.ndarray:
    a = rgba[..., 3:4] / 255.0
    return rgba[..., :3] * a + under * (1 - a)


def plan(grid: Grid, layer: int, px: int = 12) -> Image.Image:
    """The slice at ``layer``; open cells show the floor below them, lightened."""
    colors = palette_colors(grid)
    here = colors[grid.cells[:, layer, :]]
    below = colors[grid.cells[:, layer - 1, :]] if layer > 0 else np.zeros_like(here)
    floor = _blend(below, np.array(BACKGROUND, dtype=np.float32)) * 0.45 + np.array(BACKGROUND) * 0.55
    rgb = _blend(here, floor)
    # outline solid cells darker so walls read clearly
    solid = grid.cells[:, layer, :] != 0
    rgb[solid] *= 0.8
    return _canvas(rgb, px)


def top(grid: Grid, px: int = 8) -> Image.Image:
    colors = palette_colors(grid)
    sx, sy, sz = grid.shape
    filled = grid.cells != 0
    any_block = filled.any(axis=1)
    highest = sy - 1 - np.argmax(filled[:, ::-1, :], axis=1)
    ids = np.take_along_axis(grid.cells, highest[:, None, :], axis=1)[:, 0, :]
    rgb = colors[ids][..., :3]
    shade = 0.55 + 0.45 * (highest / max(1, sy - 1))
    rgb = rgb * shade[..., None]
    rgb[~any_block] = BACKGROUND
    return _canvas(rgb, px, grid_lines=False)


_VIEWS = {
    # name: (axis looked along, flip that axis, flip the horizontal image axis)
    "south": ("z", True, False),  # seen from the south, looking north; east is on the right
    "north": ("z", False, True),
    "east": ("x", True, True),
    "west": ("x", False, False),
}


def elevation(grid: Grid, side: str, px: int = 8) -> Image.Image:
    axis, flip_depth, flip_h = _VIEWS[side]
    cells = grid.cells if axis == "z" else np.transpose(grid.cells, (2, 1, 0))  # -> [h, y, depth]
    if flip_depth:
        cells = cells[:, :, ::-1]
    if flip_h:
        cells = cells[::-1, :, :]
    colors = palette_colors(grid)
    filled = cells != 0
    first = np.argmax(filled, axis=2)
    any_block = filled.any(axis=2)
    ids = np.take_along_axis(cells, first[:, :, None], axis=2)[:, :, 0]
    rgb = colors[ids][..., :3]
    depth = cells.shape[2]
    rgb = rgb * (1.0 - 0.45 * (first / max(1, depth - 1)))[..., None]
    rgb[~any_block] = BACKGROUND
    rgb = rgb[:, ::-1, :]  # up is up
    return _canvas(rgb, px, grid_lines=False)


def isometric(grid: Grid, px: int = 6) -> Image.Image:
    """Cubes seen from the south-east and above; only faces that can be seen are drawn."""
    colors = palette_colors(grid)
    sx, sy, sz = grid.shape
    c = grid.cells
    full = c != 0
    exposed = np.zeros_like(full)
    exposed[:, :-1, :] |= ~full[:, 1:, :]
    exposed[:, -1, :] = True
    exposed[:-1, :, :] |= ~full[1:, :, :]
    exposed[-1, :, :] = True
    exposed[:, :, :-1] |= ~full[:, :, 1:]
    exposed[:, :, -1] = True
    visible = full & exposed

    hw, hh = px, px / 2  # half width and half height of a top face

    def project(x: float, y: float, z: float) -> tuple[float, float]:
        return (x - z) * hw, (x + z) * hh - y * px * 1.15

    corners = [project(x, y, z) for x in (0, sx) for y in (0, sy) for z in (0, sz)]
    minx = min(p[0] for p in corners) - px
    miny = min(p[1] for p in corners) - px
    w = int(max(p[0] for p in corners) - minx + px)
    h = int(max(p[1] for p in corners) - miny + px)
    img = Image.new("RGB", (w, h), BACKGROUND)
    draw = ImageDraw.Draw(img)

    def pt(x: float, y: float, z: float) -> tuple[float, float]:
        a, b = project(x, y, z)
        return a - minx, b - miny

    order = np.argwhere(visible)
    order = order[np.lexsort((order[:, 1], order[:, 0] + order[:, 2]))]
    for x, y, z in order:
        r, g, b, a = colors[c[x, y, z]]
        if a < 20:
            continue
        base = np.array([r, g, b])
        top_face = [pt(x, y + 1, z), pt(x + 1, y + 1, z), pt(x + 1, y + 1, z + 1), pt(x, y + 1, z + 1)]
        east = [pt(x + 1, y, z), pt(x + 1, y + 1, z), pt(x + 1, y + 1, z + 1), pt(x + 1, y, z + 1)]
        south = [pt(x, y, z + 1), pt(x + 1, y, z + 1), pt(x + 1, y + 1, z + 1), pt(x, y + 1, z + 1)]
        draw.polygon(east, fill=tuple(int(v) for v in base * 0.72))
        draw.polygon(south, fill=tuple(int(v) for v in base * 0.86))
        draw.polygon(top_face, fill=tuple(int(v) for v in base))
    return img


def legend(grid: Grid, px: int = 18) -> Image.Image:
    counts = grid.counts()
    states = [s for s, _ in counts.most_common() if s != AIR]
    img = Image.new("RGB", (620, (len(states) + 1) * (px + 4)), BACKGROUND)
    draw = ImageDraw.Draw(img)
    for i, state in enumerate(states):
        y = 4 + i * (px + 4)
        draw.rectangle([4, y, 4 + px, y + px], fill=registry.color(state)[:3], outline=(0, 0, 0))
        draw.text((px + 12, y + 3), f"{counts[state]:>7}  {state}", fill=(0, 0, 0))
    return img


def render_all(grid: Grid, out_dir: Path, floor_layers: list[int], names: dict[int, str] | None = None) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []

    def save(img: Image.Image, name: str) -> None:
        path = out_dir / f"{name}.png"
        img.save(path)
        written.append(path)

    for layer in sorted(set(floor_layers)):
        label = (names or {}).get(layer, f"y{layer}")
        if 0 <= layer + 1 < grid.size_y:
            save(plan(grid, layer + 1), f"plan-{label}")
    save(top(grid), "top")
    for side in _VIEWS:
        save(elevation(grid, side), f"elevation-{side}")
    save(isometric(grid), "isometric")
    save(legend(grid), "legend")
    return written
