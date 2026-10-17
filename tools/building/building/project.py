"""Building projects: a folder holding a model, a palette and generated output.

    buildings/<slug>/
      building.yaml   the model (see model.py); may list more part files under ``include``
      palette.yaml    material name -> block state (or {block, slab, stairs, ...})
      sources.yaml    research notes: links, licences, measurements and their origin
      out/            everything generated: build.json, meta.json, validation.json, preview/

Projects live in the repository's ``buildings`` folder by default; private ones belong
in a gitignored folder.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import yaml

from . import buildpaste, model, preview, validate
from .grid import Grid

ROOT = buildpaste.REPO_ROOT / "buildings"


def _yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def slugify(name: str) -> str:
    import unicodedata

    text = unicodedata.normalize("NFKD", name.replace("ł", "l").replace("Ł", "L")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-") or "building"


@dataclass
class Project:
    folder: Path

    @property
    def slug(self) -> str:
        return self.folder.name

    @property
    def out(self) -> Path:
        return self.folder / "out"

    @property
    def build_file(self) -> Path:
        return self.out / "build.json"

    def data(self) -> dict:
        data = _yaml(self.folder / "building.yaml")
        parts = list(data.get("parts") or [])
        for extra in data.get("include") or []:
            parts += list(_yaml(self.folder / extra).get("parts") or [])
        data["parts"] = parts
        return data

    def palette(self) -> dict:
        return _yaml(self.folder / "palette.yaml")

    def model(self) -> model.Model:
        return model.Model(self.data(), self.palette())

    def meta(self) -> dict:
        path = self.out / "meta.json"
        if not path.exists():
            raise FileNotFoundError(f"{path} is missing; run compile first")
        return json.loads(path.read_text(encoding="utf-8"))

    @property
    def ground_layer(self) -> int:
        return int(self.meta()["ground_layer"])

    def compile(self) -> tuple[model.Compiled, dict]:
        compiled = self.model().compile()
        grid = compiled.grid.compact()
        self.out.mkdir(parents=True, exist_ok=True)
        buildpaste.write(grid, self.build_file)
        meta = compiled.meta()
        meta["cameras"] = self.cameras(compiled)
        (self.out / "meta.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
        report = validate.validate(grid, compiled.rooms, compiled.ground_layer)
        report["warnings"] = compiled.warnings + report["warnings"]
        (self.out / "validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
        return compiled, report

    def preview(self) -> list[Path]:
        grid = buildpaste.read(self.build_file)
        meta = self.meta()
        floors: dict[int, str] = {}
        for room in meta["rooms"]:
            floors.setdefault(room["floor_layer"], f"y{room['floor_layer']}")
        floors.setdefault(meta["ground_layer"], f"y{meta['ground_layer']}")
        return preview.render_all(grid, self.out / "preview", list(floors), floors)

    def cameras(self, compiled: model.Compiled) -> list[dict]:
        """Shots inside rooms plus any declared in the model, in grid coordinates."""
        f = compiled.frame
        shots = []
        g = compiled.grid
        for room, mask in zip(compiled.rooms, compiled.room_masks):
            if room.get("camera") is False:
                continue
            y = room["floor_layer"]
            if not (0 <= y and y + 1 < g.size_y):
                continue
            # cells a camera can stand in: inside the room, with air at feet and eye height
            free = mask & (g.cells[:, y, :] == 0) & (g.cells[:, y + 1, :] == 0)
            cells = np.argwhere(free)
            if not len(cells):
                compiled.warnings.append(f"{room['name']}: no free cell for a camera")
                continue
            diag = cells[:, 0] + cells[:, 1]
            anti = cells[:, 0] - cells[:, 1]
            corners = [cells[diag.argmin()], cells[diag.argmax()]]
            if (anti.max() - anti.min()) > (diag.max() - diag.min()):
                corners = [cells[anti.argmax()], cells[anti.argmin()]]
            for i, (eye, target) in enumerate((corners, corners[::-1])):
                ex, ez = eye[0] + 0.5, eye[1] + 0.5
                dx, dz = target[0] + 0.5 - ex, target[1] + 0.5 - ez
                if dx == 0 and dz == 0:
                    dz = 1
                yaw = math.degrees(math.atan2(-dx, dz))
                shots.append({"name": f"room-{slugify(room['name'])}-{i + 1}", "pos": [ex, y, ez], "yaw": round(yaw, 2), "pitch": 12})
        m = self.model()
        for cam in self.data().get("cameras") or []:
            x, z = cam["at"]
            elevation = m.elevation(cam.get("elevation", 0))
            gx, gz = f.fx(x), f.fz(z)
            gy = f.fy(elevation)
            if "look_at" in cam:
                lx, lz = cam["look_at"][:2]
                target = m.elevation(cam["look_at"][2]) if len(cam["look_at"]) > 2 else elevation + 160
                dx, dz = lx - x, lz - z
                yaw = math.degrees(math.atan2(-dx, dz))
                pitch = -math.degrees(math.atan2(target - (elevation + 162), math.hypot(dx, dz)))
            else:
                yaw, pitch = float(cam.get("yaw", 0)), float(cam.get("pitch", 0))
            shots.append({"name": cam["name"], "pos": [gx, gy, gz], "yaw": round(yaw, 2), "pitch": round(pitch, 2)})
        return shots

    def review_shots(self) -> list[dict]:
        return self.meta().get("cameras", [])


def load(folder: Path) -> Project:
    folder = Path(folder)
    if not folder.is_absolute() and not folder.exists():
        folder = ROOT / folder
    if not (folder / "building.yaml").exists():
        raise FileNotFoundError(f"no building.yaml in {folder}")
    return Project(folder.resolve())


TEMPLATE_BUILDING = """\
name: {name}
# centimetres per block; 100 keeps the real size
scale: 100
margin: 3
# elevation of the surrounding terrain, in cm
ground: 0
terrain: {{material: grass_block, below: dirt, depth: 1}}
levels:
  ground: 0
  first: 300
  roof: 600
parts:
  - {{type: slab, material: foundation, polygon: [[0, 0], [1000, 0], [1000, 800], [0, 800]], bottom: -30, top: ground}}
  - type: wall
    name: outer walls
    material: facade
    closed: true
    path: [[0, 0], [1000, 0], [1000, 800], [0, 800]]
    thickness: 40
    bottom: ground
    top: roof
    # the walls run clockwise seen from above, so the outside is on their left
    outside: left
    openings:
      - {{at: 2600, width: 100, top: 210, kind: door}}
      - {{at: 300, width: 200, bottom: 90, top: 230}}
  - {{type: slab, material: floor, polygon: [[0, 0], [1000, 0], [1000, 800], [0, 800]], bottom: first-30, top: first}}
  - {{type: room, name: hall, polygon: [[20, 20], [980, 20], [980, 780], [20, 780]], floor: ground, ceiling: first-30, finish: wood_floor}}
  - {{type: room, name: attic, polygon: [[20, 20], [980, 20], [980, 780], [20, 780]], floor: first, ceiling: roof, finish: wood_floor}}
  - {{type: stair, material: wood, at: [850, 150], direction: south, width: 100, from: ground, to: first}}
  - {{type: roof, material: roof, polygon: [[-30, -30], [1030, -30], [1030, 830], [-30, 830]], low: roof, slope: 0.2, rises: north, thickness: 30}}
cameras: []
"""

TEMPLATE_PALETTE = """\
# material name -> block state, or {block, slab, stairs, ...} for shaped variants
foundation: minecraft:smooth_stone
facade: minecraft:white_concrete
floor: minecraft:smooth_stone
wood_floor: minecraft:spruce_planks
wood: minecraft:spruce_planks
roof: {block: minecraft:deepslate_tiles, slab: minecraft:deepslate_tile_slab}
glass_pane: minecraft:glass_pane
door: minecraft:spruce_door
garage_door: minecraft:gray_concrete
"""

TEMPLATE_SOURCES = """\
# Every number in the model should be traceable to an entry here.
name: {name}
sources: []
#  - url: https://...
#    what: floor plan / photo / height
#    licence: CC BY-SA 4.0
facts: []
#  - {{fact: height to roof, value: 6.0 m, source: 0}}
"""


def create(folder: Path, name: str) -> Project:
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "building.yaml").write_text(TEMPLATE_BUILDING.format(name=name), encoding="utf-8")
    (folder / "palette.yaml").write_text(TEMPLATE_PALETTE, encoding="utf-8")
    (folder / "sources.yaml").write_text(TEMPLATE_SOURCES.format(name=name), encoding="utf-8")
    return Project(folder)


# ---------------------------------------------------------------- CLI


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_new(args) -> int:
    folder = Path(args.folder) if args.folder else ROOT / slugify(args.name)
    proj = create(folder, args.name)
    print(proj.folder)
    return 0


def cmd_compile(args) -> int:
    proj = load(Path(args.project))
    _, report = proj.compile()
    meta = proj.meta()
    _print({"build": str(proj.build_file), "size": meta["size"], "blocks": meta["blocks"], "ground_layer": meta["ground_layer"], **report})
    if not args.no_preview:
        proj.preview()
        print(f"previews in {proj.out / 'preview'}")
    return 0 if report["ok"] else 1


def cmd_preview(args) -> int:
    proj = load(Path(args.project))
    for path in proj.preview():
        print(path)
    return 0


def cmd_slice(args) -> int:
    proj = load(Path(args.project))
    grid: Grid = buildpaste.read(proj.build_file)
    out = Path(args.out) if args.out else proj.out / "preview" / f"slice-y{args.layer}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    preview.plan(grid, args.layer, px=args.px).save(out)
    print(out)
    return 0


def add_commands(sub) -> None:
    p = sub.add_parser("new", help="create a building project from the template")
    p.add_argument("name")
    p.add_argument("--folder")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("compile", help="compile a project to out/build.json, validate it and draw previews")
    p.add_argument("project")
    p.add_argument("--no-preview", action="store_true")
    p.set_defaults(func=cmd_compile)

    p = sub.add_parser("preview", help="redraw a project's previews from out/build.json")
    p.add_argument("project")
    p.set_defaults(func=cmd_preview)

    p = sub.add_parser("slice", help="draw one horizontal layer of a compiled project")
    p.add_argument("project")
    p.add_argument("layer", type=int)
    p.add_argument("--px", type=int, default=16)
    p.add_argument("--out")
    p.set_defaults(func=cmd_slice)
