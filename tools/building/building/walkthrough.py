"""Prepare a verified, saved world for a normal interactive Minecraft client."""

from __future__ import annotations

import json
import shutil
import zipfile
from pathlib import Path

from PIL import Image

from . import registry, review


def white_panel_pack(game_dir: Path, version: str) -> Path:
    """Generate a uniform near-white panel texture; no game assets are copied."""
    jar = registry._loom_dir(version) / "minecraft-client.jar"
    with zipfile.ZipFile(jar) as client:
        formats = json.loads(client.read("version.json"))["pack_version"]
    resource_format = [formats["resource_major"], formats["resource_minor"]]
    pack = game_dir / "resourcepacks" / "buildpaste-white-panels"
    pack.mkdir(parents=True, exist_ok=False)
    (pack / "pack.mcmeta").write_text(
        json.dumps({"pack": {
            "description": "Smooth white thin panels (pale oak trapdoors). Local visual option only.",
            "min_format": resource_format,
            "max_format": resource_format,
        }}, indent=2),
        encoding="utf-8",
    )
    models = pack / "assets" / "minecraft" / "models" / "block"
    models.mkdir(parents=True)
    texture = pack / "assets" / "buildpaste" / "textures" / "block" / "review_white_panel.png"
    texture.parent.mkdir(parents=True)
    Image.new("RGB", (16, 16), (242, 242, 242)).save(texture)
    for shape in ("bottom", "top", "open"):
        (models / f"pale_oak_trapdoor_{shape}.json").write_text(
            json.dumps({
                "parent": f"minecraft:block/template_orientable_trapdoor_{shape}",
                "textures": {"texture": "buildpaste:block/review_white_panel"},
            }, indent=2),
            encoding="utf-8",
        )
    return pack


def prepare(build_file: Path, game_dir: Path, name: str, ground_layer: int = 0,
            target: str = review.DEFAULT_TARGET, white_panels: bool = False) -> dict:
    game_dir = game_dir.resolve()
    # Only a new, isolated game directory is accepted; never change an existing instance.
    if game_dir.exists():
        raise FileExistsError(f"walkthrough needs a new game directory: {game_dir}")
    if not name or Path(name).name != name or name in (".", "..") or "/" in name or "\\" in name:
        raise ValueError("world name must be a single folder name")
    summary = review.run(build_file, f"{name}-walkthrough", ground_layer=ground_layer, exterior=False,
                         target=target, walkthrough=True)
    if not summary["ok"]:
        raise RuntimeError(f"game review failed; see {summary['log']}")
    source = Path(summary["game"]["world"])
    if not (source / "level.dat").is_file():
        raise FileNotFoundError(f"review produced no saved world at {source}")
    destination = game_dir / "saves" / name
    destination.parent.mkdir(parents=True)
    shutil.copytree(source, destination, ignore=shutil.ignore_patterns("session.lock"))
    builds = game_dir / "buildpaste" / "builds"
    builds.mkdir(parents=True)
    shutil.copyfile(build_file, builds / f"{name}.json")
    pack = white_panel_pack(game_dir, target.rsplit("-", 1)[0]) if white_panels else None
    result = {
        "world": str(destination),
        "build": str(builds / f"{name}.json"),
        "min": summary["game"]["min"],
        "max": summary["game"]["max"],
        "diff": summary["diff"],
        "resource_pack": str(pack) if pack else None,
        "note": "Resource packs are not included in BuildPaste uploads.",
    }
    (game_dir / "walkthrough.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result
