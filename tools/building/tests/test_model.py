from __future__ import annotations

import copy

import numpy as np
import pytest
import yaml

from building import buildpaste, project, validate
from building.grid import Grid, split_state
from building.model import Frame, Model, Warp

PALETTE = yaml.safe_load(project.TEMPLATE_PALETTE)
SHELL = [[0, 0], [1000, 0], [1000, 800], [0, 800]]


def house(*parts: dict, **extra) -> dict:
    """A 10 x 8 m single storey box with 40 cm outer walls and a flat roof."""
    data = {
        "name": "test",
        "scale": 100,
        "margin": 2,
        "ground": 0,
        "levels": {"ground": 0, "roof": 300},
        "parts": [
            {"type": "slab", "material": "foundation", "polygon": SHELL, "bottom": -30, "top": "ground"},
            {"type": "wall", "name": "outer", "material": "facade", "closed": True, "path": SHELL,
             "thickness": 40, "bottom": "ground", "top": "roof", "outside": "left"},
            *parts,
            {"type": "slab", "material": "facade", "polygon": SHELL, "bottom": "roof", "top": "roof+30"},
        ],
    }
    data.update(extra)
    return data


def compile_(data: dict):
    return Model(data, PALETTE).compile()


def name(state: str) -> str:
    return split_state(state)[0]


# ---------------------------------------------------------------- warp


def test_warp_maps_breakpoints_and_extrapolates():
    w = Warp([0, 100, 250], [0, 1, 3], 100)
    assert w.fwd(100) == 1
    assert w.fwd(175) == pytest.approx(2)
    assert w.fwd(-100) == -1
    assert w.fwd(350) == 4
    for b in (0.5, 1.5, 2.5, 3.5):
        assert w.fwd(w.inv(b)) == pytest.approx(b)


def test_warp_inverse_skips_collapsed_spans():
    w = Warp([0, 100, 110, 210], [0, 1, 1, 2], 100)
    assert w.inv(1.5) == pytest.approx(160)


def test_frame_round_trips_through_meta():
    out = compile_(house())
    again = Frame.from_meta(out.meta())
    for v in (0, 40, 333, 960, 1000):
        assert again.fx(v) == pytest.approx(out.frame.fx(v), abs=1e-3)
        assert again.fz(v) == pytest.approx(out.frame.fz(v), abs=1e-3)


def test_uniform_frame_from_legacy_meta():
    f = Frame.from_meta({"scale": 100, "size": [4, 4, 4], "origin_cm": [-200, -100, -200]})
    assert f.cx(0) == 2
    assert f.cy(0) == 1


# ---------------------------------------------------------------- ceil quantisation


def test_rooms_get_at_least_their_ceiled_length():
    # 920 cm clear inside 40 cm walls -> ceil(9.2 - 0.1) = 10 blocks of air
    out = compile_(house())
    f, g = out.frame, out.grid
    y, z = f.cy(150), f.cz(400)
    row = [g.get(x, y, z) for x in range(g.size_x)]
    inside = [s for s in row[f.cx(40) : f.cx(960)]]
    assert all(s == "minecraft:air" for s in inside)
    assert len(inside) == 10


def test_round_mode_keeps_the_uniform_grid():
    out = compile_(house(quantize="round"))
    assert out.frame.fx(500) - out.frame.fx(0) == pytest.approx(5)


def test_tolerance_controls_inflation():
    tight = compile_(house(quantization={"tolerance": 0.3}))
    loose = compile_(house(quantization={"tolerance": 0.0}))
    assert tight.grid.size_x <= loose.grid.size_x


# ---------------------------------------------------------------- thin walls


def test_thin_interior_wall_becomes_edge_panels():
    wall = {"type": "wall", "name": "partition", "material": "facade", "path": [[500, 40], [500, 760]],
            "thickness": 12, "bottom": "ground", "top": "roof"}
    out = compile_(house(wall))
    f, g = out.frame, out.grid
    y, z = f.cy(150), f.cz(400)
    states = {g.get(x, y, z) for x in range(g.size_x)}
    panels = [s for s in states if name(s) == "minecraft:pale_oak_trapdoor"]
    assert panels, states
    props = split_state(panels[0])[1]
    assert props["open"] == "true" and props["facing"] in ("east", "west")
    # the panel stands in a cell that is still walkable floor space
    assert not any(name(s) == "minecraft:white_concrete" for s in [g.get(f.cx(500), y, z)])


def test_door_in_thin_wall_sits_in_the_panel_plane():
    wall = {"type": "wall", "name": "partition", "material": "facade", "path": [[500, 40], [500, 760]],
            "thickness": 12, "bottom": "ground", "top": "roof",
            "openings": [{"at": 300, "width": 90, "top": 200, "kind": "door"}]}
    out = compile_(house(wall))
    doors = [s for _, _, _, s in out.grid.non_air() if name(s) == "minecraft:spruce_door"]
    assert len(doors) == 2  # lower and upper half
    assert {split_state(s)[1]["facing"] for s in doors} <= {"east", "west"}


def test_thin_exterior_wall_is_glazed_with_corner_pillars():
    glass_house = house()
    glass_house["parts"][1]["thickness"] = 12
    out = compile_(glass_house)
    f, g = out.frame, out.grid
    y = f.cy(150)
    zc = f.cell_of(0, 0)[1]
    north = [g.get(x, y, zc) for x in range(f.cell_of(0, 0)[0], f.cell_of(1000, 0)[0] + 1)]
    assert sum(name(s) == "minecraft:glass_pane" for s in north) >= 6
    assert name(north[0]) == "minecraft:white_concrete"
    assert name(north[-1]) == "minecraft:white_concrete"


def test_pier_between_close_windows_survives():
    data = house()
    data["parts"][1]["openings"] = [
        {"at": 300, "width": 70, "top": 270},
        {"at": 400, "width": 70, "top": 270},
    ]
    out = compile_(data)
    f, g = out.frame, out.grid
    assert not [w for w in out.warnings if "pier" in w]
    y, z = f.cy(150), f.cell_of(0, 0)[1]
    row = [name(g.get(x, y, z)) for x in range(g.size_x)]
    runs = "".join("g" if s == "minecraft:glass_pane" else ("w" if s == "minecraft:white_concrete" else ".") for s in row)
    assert "gwg" in runs or "gw" in runs and runs.count("g") >= 2
    first, last = runs.index("g"), runs.rindex("g")
    assert "w" in runs[first:last]


def test_thin_box_never_vanishes():
    box = {"type": "box", "material": "wood", "polygon": [[500, 300], [550, 300], [550, 360], [500, 360]],
           "bottom": "ground", "top": "roof"}
    out = compile_(house(box))
    assert any(name(s) == "minecraft:spruce_planks" for _, _, _, s in out.grid.non_air())


# ---------------------------------------------------------------- stairs and roofs


def test_template_project_compiles_cleanly(tmp_path):
    proj = project.create(tmp_path / "t", "Template")
    out = proj.model().compile()
    report = validate.validate(out.grid, out.rooms, out.ground_layer)
    assert report["ok"], report
    assert not out.warnings
    assert not report["warnings"], report["warnings"]


def test_stair_roof_steps_face_uphill(tmp_path):
    proj = project.create(tmp_path / "t", "Template")
    data = proj.data()
    palette = copy.deepcopy(proj.palette())
    palette["roof"] = {"block": "minecraft:polished_blackstone", "stairs": "minecraft:polished_blackstone_stairs"}
    for p in data["parts"]:
        if p["type"] == "roof":
            p["smooth"] = "stairs"
            p["slope"] = 0.3
    out = Model(data, palette).compile()
    stairs = [s for _, _, _, s in out.grid.non_air() if name(s) == "minecraft:polished_blackstone_stairs"]
    assert stairs
    assert {split_state(s)[1]["facing"] for s in stairs} == {"north"}


# ---------------------------------------------------------------- validation and files


def test_open_trapdoor_blocks_the_edge_opposite_its_facing():
    g = Grid(3, 3, 3)
    g.set(1, 1, 1, "minecraft:oak_trapdoor[facing=east,half=bottom,open=true]")
    edges = validate._panel_edges(g)
    assert list(edges.values()) == [(-1, 0)]


def test_build_json_round_trip(tmp_path):
    out = compile_(house())
    path = buildpaste.write(out.grid, tmp_path / "b.json")
    back = buildpaste.read(path)
    assert buildpaste.diff(out.grid, back)["ok"]
    assert np.array_equal(np.array(back.shape), np.array(out.grid.shape))
