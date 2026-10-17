"""Pasting a build into a real game and checking what landed.

``run`` writes ``build/review/spec.json``, starts the Fabric client game test (a real
26.1.2 client creating a fresh world every time, so there is nothing to reset), and
then compares the region the game exported back with the build, cell by cell.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import buildpaste
from .grid import Grid

REVIEW_DIR = buildpaste.REPO_ROOT / "build" / "review"
DEFAULT_TARGET = "26.1.2-fabric"

# The default client view: 70 degrees vertically, at 16:9.
V_FOV = math.radians(70)
H_FOV = 2 * math.atan(math.tan(V_FOV / 2) * 16 / 9)


def _fit_distance(width: float, height: float, margin: float = 1.2) -> float:
    return margin * max((width / 2) / math.tan(H_FOV / 2), (height / 2) / math.tan(V_FOV / 2))


def exterior_shots(size: tuple[int, int, int], ground_layer: int = 0) -> list[dict]:
    """Four elevations, four three-quarter views and a plan view, in build cell coordinates."""
    sx, sy, sz = size
    cx, cz = sx / 2, sz / 2
    above = sy - ground_layer
    eye = ground_layer + max(1.7, above / 2)
    shots = []
    # name, camera direction from the centre (dx, dz), yaw to look back, facade width
    for name, dx, dz, yaw, width in (
        ("elevation-south", 0, 1, 180, sx),
        ("elevation-north", 0, -1, 0, sx),
        ("elevation-east", 1, 0, 90, sz),
        ("elevation-west", -1, 0, -90, sz),
    ):
        depth = sz if dz else sx
        d = _fit_distance(width, above) + depth / 2
        shots.append({"name": name, "pos": [cx + dx * d, eye, cz + dz * d], "yaw": yaw, "pitch": 0})
    diag = math.hypot(sx, sz)
    for name, dx, dz in (("view-se", 1, 1), ("view-sw", -1, 1), ("view-nw", -1, -1), ("view-ne", 1, -1)):
        d = _fit_distance(diag, above + diag * 0.5) * 0.85
        h = d * math.sin(math.radians(30))
        horizontal = d * math.cos(math.radians(30))
        px = cx + dx * horizontal / math.sqrt(2)
        pz = cz + dz * horizontal / math.sqrt(2)
        yaw = math.degrees(math.atan2(-(cx - px), cz - pz))
        shots.append({"name": name, "pos": [px, eye + h, pz], "yaw": round(yaw, 2), "pitch": 30})
    top = _fit_distance(sx, sz) + sy
    shots.append({"name": "plan-top", "pos": [cx, ground_layer + top, cz], "yaw": 180, "pitch": 90})
    return shots


def gradlew() -> list[str]:
    script = buildpaste.REPO_ROOT / ("gradlew.bat" if os.name == "nt" else "gradlew")
    return [str(script)]


def run(
    build_file: Path,
    name: str,
    ground_layer: int = 0,
    extra_shots: list[dict] | None = None,
    exterior: bool = True,
    target: str = DEFAULT_TARGET,
    time_of_day: int = 6000,
    width: int = 1920,
    height: int = 1080,
) -> dict:
    expected = buildpaste.read(build_file)
    out = REVIEW_DIR / name
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    shots = (exterior_shots(expected.shape, ground_layer) if exterior else []) + list(extra_shots or [])
    spec = {
        "build": str(Path(build_file).resolve()),
        "out": str(out.resolve()),
        "groundLayer": ground_layer,
        "anchor": [0, 0],
        "time": time_of_day,
        "width": width,
        "height": height,
        "shots": shots,
    }
    REVIEW_DIR.mkdir(parents=True, exist_ok=True)
    (REVIEW_DIR / "spec.json").write_text(json.dumps(spec, indent=2), encoding="utf-8")

    started = time.time()
    log = out / "gradle.log"
    with log.open("w", encoding="utf-8") as handle:
        result = subprocess.run(
            gradlew() + [f":{target}:runClientGameTest", "--console=plain"],
            cwd=buildpaste.REPO_ROOT,
            stdout=handle,
            stderr=subprocess.STDOUT,
        )
    summary: dict = {"name": name, "seconds": round(time.time() - started), "gradle_exit": result.returncode, "log": str(log)}

    readback = out / "readback.json"
    if not readback.exists():
        summary["ok"] = False
        summary["reason"] = "the game produced no read-back; see the Gradle log"
    else:
        summary["diff"] = buildpaste.diff(expected, buildpaste.read(readback))
        summary["ok"] = summary["diff"]["ok"] and result.returncode == 0
    report = out / "report.json"
    if report.exists():
        summary["game"] = json.loads(report.read_text(encoding="utf-8"))
    summary["shots_dir"] = str(out / "shots")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def diff_files(expected: Path, actual: Path) -> dict:
    return buildpaste.diff(buildpaste.read(expected), buildpaste.read(actual))


def sample_build() -> Grid:
    """A tiny hut that exercises orientation: stairs, a door, a bed, glass and a torch."""
    g = Grid(7, 6, 5)
    g.fill(0, 0, 0, 6, 0, 4, "minecraft:stone_bricks")
    g.fill(0, 1, 0, 6, 3, 4, "minecraft:oak_planks")
    g.fill(1, 1, 1, 5, 3, 3, None)
    g.set(3, 1, 4, "minecraft:oak_door[facing=north,half=lower,hinge=left,open=false]")
    g.set(3, 2, 4, "minecraft:oak_door[facing=north,half=upper,hinge=left,open=false]")
    g.set(1, 2, 4, "minecraft:glass_pane[east=true,west=true]")
    g.set(5, 2, 4, "minecraft:glass_pane[east=true,west=true]")
    g.set(1, 1, 1, "minecraft:red_bed[facing=east,part=foot]")
    g.set(2, 1, 1, "minecraft:red_bed[facing=east,part=head]")
    g.set(5, 2, 1, "minecraft:wall_torch[facing=south]")
    for x in range(7):
        g.set(x, 4, 0, "minecraft:spruce_stairs[facing=south,half=bottom]")
        g.set(x, 4, 4, "minecraft:spruce_stairs[facing=north,half=bottom]")
        g.fill(x, 4, 1, x, 4, 3, "minecraft:spruce_planks")
        g.set(x, 5, 2, "minecraft:spruce_slab[type=bottom]")
    return g
