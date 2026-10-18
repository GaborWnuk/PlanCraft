import json
from pathlib import Path
from unittest.mock import Mock
from zipfile import ZipFile

import pytest
from PIL import Image

from building import walkthrough


def test_white_panel_pack_has_uniform_white_texture(tmp_path, monkeypatch):
    jar_dir = tmp_path / "jars"
    jar_dir.mkdir()
    with ZipFile(jar_dir / "minecraft-client.jar", "w") as jar:
        jar.writestr("version.json", json.dumps({
            "pack_version": {"resource_major": 84, "resource_minor": 0},
        }))
    monkeypatch.setattr(walkthrough.registry, "_loom_dir", lambda version: jar_dir)
    pack = walkthrough.white_panel_pack(tmp_path / "game", "26.1.2")
    metadata = json.loads((pack / "pack.mcmeta").read_text())
    assert metadata["pack"]["min_format"] == [84, 0]
    assert metadata["pack"]["max_format"] == [84, 0]
    models = sorted(pack.rglob("*.json"))
    assert len(models) == 3
    for model in models:
        data = json.loads(model.read_text())
        shape = model.stem.removeprefix("pale_oak_trapdoor_")
        assert data["parent"] == f"minecraft:block/template_orientable_trapdoor_{shape}"
        assert data["textures"] == {"texture": "buildpaste:block/review_white_panel"}
    textures = list(pack.rglob("*.png"))
    assert len(textures) == 1
    with Image.open(textures[0]) as image:
        assert image.size == (16, 16)
        assert image.getcolors() == [(256, (242, 242, 242))]
    with pytest.raises(FileExistsError):
        walkthrough.white_panel_pack(tmp_path / "game", "26.1.2")


def test_prepare_rejects_existing_game_directory(tmp_path, monkeypatch):
    run = Mock()
    monkeypatch.setattr(walkthrough.review, "run", run)
    with pytest.raises(FileExistsError):
        walkthrough.prepare(tmp_path / "build.json", tmp_path, "house")
    run.assert_not_called()


@pytest.mark.parametrize("name", ["..", "../house", r"..\house", ""])
def test_prepare_rejects_unsafe_world_name(tmp_path, name):
    with pytest.raises(ValueError):
        walkthrough.prepare(tmp_path / "build.json", tmp_path / "game", name)


def test_prepare_requires_successful_review(tmp_path, monkeypatch):
    monkeypatch.setattr(walkthrough.review, "run", lambda *a, **kw: {"ok": False, "log": "game.log"})
    with pytest.raises(RuntimeError, match="game.log"):
        walkthrough.prepare(tmp_path / "build.json", tmp_path / "game", "house")
    assert not (tmp_path / "game").exists()


def test_prepare_copies_closed_world_and_build(tmp_path, monkeypatch):
    source = tmp_path / "saved-world"
    source.mkdir()
    (source / "level.dat").write_bytes(b"saved level")
    (source / "session.lock").write_bytes(b"lock")
    (source / "dimensions").mkdir()
    (source / "dimensions" / "chunk.mca").write_bytes(b"chunk")
    build = tmp_path / "build.json"
    build.write_text("{}")
    summary = {"ok": True, "game": {"world": str(source), "min": [1, 2, 3], "max": [4, 5, 6]},
               "diff": {"ok": True, "mismatch_count": 0}}
    run = Mock(return_value=summary)
    monkeypatch.setattr(walkthrough.review, "run", run)
    game = tmp_path / "game"
    result = walkthrough.prepare(build, game, "house", ground_layer=1)
    run.assert_called_once_with(build, "house-walkthrough", ground_layer=1, exterior=False,
                                target="26.1.2-fabric", walkthrough=True)
    world = Path(result["world"])
    assert (world / "level.dat").read_bytes() == b"saved level"
    assert (world / "dimensions" / "chunk.mca").read_bytes() == b"chunk"
    assert not (world / "session.lock").exists()
    assert Path(result["build"]).read_text() == "{}"
    assert result["resource_pack"] is None
    assert json.loads((game / "walkthrough.json").read_text()) == result
    assert (source / "session.lock").exists()
