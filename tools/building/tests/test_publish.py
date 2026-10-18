import json
from zipfile import ZipFile

import pytest

from building import buildpaste, publish
from building.grid import Grid


def _tower() -> Grid:
    """A 5x10x4 box with an off-centre column, so tight bounds differ from the size."""
    grid = Grid(5, 10, 4)
    for y in range(8):
        grid.set(1, y, 2, "minecraft:stone")
        grid.set(2, y, 2, "minecraft:oak_stairs[facing=north,half=bottom,shape=straight]")
    grid.set(3, 0, 1, "minecraft:some_mod_block")
    return grid


def test_plan_sections_are_tight_lossless_and_stacked():
    doc = buildpaste.to_json(_tower())
    whole = publish.plan_sections(doc, limit=10**9)
    assert whole["single_upload"] is True
    assert whole["tight"] == {"min": [1, 0, 1], "max": [3, 7, 2], "size": [3, 8, 2]}
    assert whole["sections"][0]["layers"] == [0, 7]

    small = publish.plan_sections(doc, limit=whole["sections"][0]["bytes"] // 2)
    layers = [s["layers"] for s in small["sections"]]
    assert len(layers) > 1
    assert layers[0][0] == 0 and layers[-1][1] == 7
    assert all(b[0] == a[1] + 1 for a, b in zip(layers, layers[1:]))
    assert all(s["bytes"] <= small["limit"] for s in small["sections"])
    with pytest.raises(ValueError):
        publish.plan_sections(doc, limit=50)


def test_world_selections_follow_the_north_paste_rule():
    plan = publish.add_selections(publish.plan_sections(buildpaste.to_json(_tower()), 10**9), [100, 64, 200])
    section = plan["sections"][0]
    assert section["pos1"] == [102, 64, 198]
    assert section["pos2"] == [104, 71, 199]


def test_upload_names_carry_a_timestamp():
    assert publish.upload_name("Tower", 2, 3, "2026-01-02 03:04") == "Tower 2026-01-02 03:04 part 2 of 3"
    assert publish.upload_name("Tower", 1, 1, "2026-01-02 03:04") == "Tower 2026-01-02 03:04"


def test_verify_upload_accepts_tight_sections_with_added_defaults():
    grid = _tower()
    doc = buildpaste.to_json(grid)
    part = Grid(3, 4, 2, palette=list(grid.palette))
    part.cells = grid.cells[1:4, 4:8, 1:3].copy()
    remote = buildpaste.to_json(part)
    remote["data"] = [d.replace("]", ",waterlogged=false]") if d else d for d in remote["data"]]
    assert publish.verify_upload(doc, remote, [4, 7])["ok"] is True

    part.set(0, 0, 1, "minecraft:dirt")
    result = publish.verify_upload(doc, buildpaste.to_json(part), [4, 7])
    assert result["ok"] is False and result["mismatch_count"] == 1
    assert publish.verify_upload(doc, remote, [0, 7])["ok"] is False


def test_fit_reports_clipping_and_safe_origins():
    doc = buildpaste.to_json(_tower())
    assert publish.fit(doc, 64)["fits"] is True
    high = publish.fit(doc, 316)
    assert high["fits"] is False
    assert high["clipped_above"] == 8  # layers 4..7 above y 319, two blocks each
    assert high["max_origin_y"] == 312
    low = publish.fit(doc, -66)
    assert low["clipped_below"] == 5 and low["min_origin_y"] == -64


def test_height_pack_raises_only_the_top(tmp_path, monkeypatch):
    jar_dir = tmp_path / "jars"
    jar_dir.mkdir()
    with ZipFile(jar_dir / "minecraft-client.jar", "w") as jar:
        jar.writestr("version.json", json.dumps({"pack_version": {"data_major": 101, "data_minor": 1}}))
        jar.writestr("data/minecraft/dimension_type/overworld.json",
                     json.dumps({"min_y": -64, "height": 384, "logical_height": 384, "has_skylight": True}))
    monkeypatch.setattr(publish.registry, "_loom_dir", lambda version: jar_dir)
    pack = publish.height_pack(tmp_path, 374, "26.1.2")
    meta = json.loads((pack / "pack.mcmeta").read_text())["pack"]
    assert meta["min_format"] == [101, 1] and meta["max_format"] == 101
    overworld = json.loads((pack / "data/minecraft/dimension_type/overworld.json").read_text())
    assert overworld == {"min_y": -64, "height": 448, "logical_height": 448, "has_skylight": True}
    with pytest.raises(FileExistsError):
        publish.height_pack(tmp_path, 374, "26.1.2")
    with pytest.raises(ValueError):
        publish.height_pack(tmp_path, 5000, "26.1.2", name="too-tall")
