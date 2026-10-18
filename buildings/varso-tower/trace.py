"""Trace solid (black-filled) walls and columns from the registered public floor plans.

Every Foster + Partners plan of the tower shares one registration: the north-west corner of the
typical floor sits at pixel (678, 80) and the printed scale bar measures 17.6 px per metre.
A 1 m cell is solid when enough of it is drawn in solid ink, which keeps thin glazing lines,
furniture and hatching out of the result.

Run from the repository root: python buildings\\varso-tower\\trace.py [drawing ...]
It prints an ASCII map per drawing and writes traced.json next to this file.
"""

import json
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent
ORIGIN = (678, 80)
PX_PER_M = 17.6
EXTENT = (-20, -2, 58, 48)
THRESHOLD = 0.30
DRAWINGS = {
    "ground": "drawing-02.png",
    "typical": "plan-level-04.png",
    "transfer": "drawing-05.png",
    "terrace": "drawing-06.png",
    "high": "drawing-07.png",
    "upper": "drawing-08.png",
    "restaurant": "drawing-09.png",
    "mezzanine": "drawing-10.png",
    "garden": "drawing-11.png",
    "viewing": "drawing-13.png",
}


def scale_bar(gray):
    """Pixels per metre from the 0, 5 and 10 m ticks under the title block."""
    ticks = [x for x in range(540, 740) if gray.getpixel((x, 966)) < 128]
    major = [x for x in ticks if x >= 550]
    return (major[-1] - major[0]) / 10 if len(major) >= 2 else None


def trace(name):
    gray = Image.open(ROOT / "references" / DRAWINGS[name]).convert("L")
    ink = gray.point(lambda v: 255 if v < 100 else 0)
    x0, z0, x1, z1 = EXTENT
    cells = []
    for z in range(z0, z1):
        for x in range(x0, x1):
            left = round(ORIGIN[0] + x * PX_PER_M)
            top = round(ORIGIN[1] + z * PX_PER_M)
            right = round(ORIGIN[0] + (x + 1) * PX_PER_M)
            bottom = round(ORIGIN[1] + (z + 1) * PX_PER_M)
            if left < 0 or top < 0 or right > gray.width or bottom > gray.height:
                continue
            area = (right - left) * (bottom - top)
            dark = sum(ink.crop((left, top, right, bottom)).histogram()[255:])
            if dark / area >= THRESHOLD:
                cells.append([x, z])
    return {"drawing": DRAWINGS[name], "px_per_m": scale_bar(gray), "cells": cells}


def ascii_map(cells):
    solid = {tuple(c) for c in cells}
    x0, z0, x1, z1 = EXTENT
    rows = []
    for z in range(z0, z1):
        rows.append(f"{z:4d} " + "".join("#" if (x, z) in solid else "." for x in range(x0, x1)))
    return "\n".join(rows)


def main(names):
    traced = {}
    for name in names or DRAWINGS:
        traced[name] = trace(name)
        print(f"== {name} ({traced[name]['drawing']}, bar {traced[name]['px_per_m']} px/m)")
        print(ascii_map(traced[name]["cells"]))
    if not names:
        (ROOT / "traced.json").write_text(json.dumps(traced, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
