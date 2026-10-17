"""The block registry of a real Minecraft version, for validating and previewing builds.

Valid blocks and properties come from the game's own data generator
(``--reports`` writes ``blocks.json``), and preview colours are averaged from the block
textures in the client jar. Both are cached under ``tools/building/.cache/<version>``.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import subprocess
import zipfile
from functools import lru_cache
from pathlib import Path

from PIL import Image

from .grid import split_state

DEFAULT_VERSION = "26.1.2"
CACHE = Path(__file__).resolve().parents[1] / ".cache"


def _loom_dir(version: str) -> Path:
    return Path.home() / ".gradle" / "caches" / "fabric-loom" / version


def _java() -> str:
    candidates = [
        os.environ.get("BUILDING_JAVA"),
        str(Path(os.environ.get("APPDATA", "")) / "PrismLauncher/java/java-runtime-epsilon/bin/java.exe"),
        shutil.which("java"),
    ]
    for c in candidates:
        if c and Path(c).exists():
            return c
    raise RuntimeError("no Java found; set BUILDING_JAVA to a Java 25 executable")


def ensure_reports(version: str = DEFAULT_VERSION) -> Path:
    out = CACHE / version
    blocks = out / "blocks.json"
    if blocks.exists():
        return blocks
    server_jar = _loom_dir(version) / "minecraft-server.jar"
    if not server_jar.exists():
        raise RuntimeError(f"{server_jar} missing; run a Gradle build for {version} first")
    work = out / "datagen"
    work.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [_java(), "-DbundlerMainClass=net.minecraft.data.Main", "-jar", str(server_jar), "--reports", "--output", str(work / "generated")],
        cwd=work,
        check=True,
        capture_output=True,
    )
    shutil.copy(work / "generated" / "reports" / "blocks.json", blocks)
    shutil.rmtree(work, ignore_errors=True)
    return blocks


@lru_cache(maxsize=4)
def blocks(version: str = DEFAULT_VERSION) -> dict:
    return json.loads(ensure_reports(version).read_text(encoding="utf-8"))


def validate_state(state: str, version: str = DEFAULT_VERSION) -> str | None:
    """None if the state exists in this version, otherwise why not."""
    name, props = split_state(state)
    entry = blocks(version).get(name)
    if entry is None:
        return f"unknown block {name}"
    allowed = entry.get("properties", {})
    for key, value in props.items():
        if key not in allowed:
            return f"{name} has no property {key}"
        if value not in allowed[key]:
            return f"{name}[{key}] cannot be {value} (allowed: {', '.join(allowed[key])})"
    return None


# Texture names tried for a block, most specific first.
_SUFFIXES = ("_stairs", "_slab", "_wall", "_fence_gate", "_fence", "_pressure_plate", "_button", "_trapdoor", "_door", "_pane", "_carpet")
_WOOD = ("oak", "spruce", "birch", "jungle", "acacia", "dark_oak", "mangrove", "cherry", "pale_oak", "bamboo", "crimson", "warped")


def _texture_candidates(block: str) -> list[str]:
    base = block.split(":", 1)[1]
    out = [base, base + "_top", base + "_side", base + "_front"]
    for suffix in _SUFFIXES:
        if base.endswith(suffix):
            stem = base[: -len(suffix)]
            if suffix in ("_door", "_trapdoor"):
                out += [base + "_top", base + "_bottom"]
            if suffix == "_pane":
                out += [stem]
            if suffix == "_carpet":
                out += [stem + "_wool"]
            out += [stem, stem + "_planks", stem + "s", stem + "_block", stem + "_top"]
            if stem.endswith("brick"):
                out += [stem + "s"]
            if stem in _WOOD:
                out += [stem + "_planks"]
    if base.endswith(("_log", "_wood")):
        out.append(base.rsplit("_", 1)[0] + "_log")
    if base.endswith("_wall_sign") or base.endswith("_sign"):
        out.append(base.split("_")[0] + "_planks")
    return out


@lru_cache(maxsize=4)
def colors(version: str = DEFAULT_VERSION) -> dict[str, tuple[int, int, int, int]]:
    """Average RGBA per block, read from the client jar's block textures."""
    cache = CACHE / version / "colors.json"
    if cache.exists():
        return {k: tuple(v) for k, v in json.loads(cache.read_text()).items()}
    jar = _loom_dir(version) / "minecraft-client.jar"
    textures: dict[str, tuple[int, int, int, int]] = {}
    with zipfile.ZipFile(jar) as z:
        for info in z.infolist():
            n = info.filename
            if n.startswith("assets/minecraft/textures/block/") and n.endswith(".png"):
                img = Image.open(io.BytesIO(z.read(n))).convert("RGBA")
                w, h = img.size
                img = img.crop((0, 0, w, min(w, h)))
                px = [p for p in img.getdata() if p[3] > 0]
                if not px:
                    continue
                r = sum(p[0] for p in px) // len(px)
                g = sum(p[1] for p in px) // len(px)
                b = sum(p[2] for p in px) // len(px)
                a = sum(p[3] for p in px) // len(px)
                textures[n.rsplit("/", 1)[1][:-4]] = (r, g, b, a)
    result: dict[str, tuple[int, int, int, int]] = {}
    for block in blocks(version):
        for cand in _texture_candidates(block):
            if cand in textures:
                result[block] = textures[cand]
                break
    # Grass and leaves are tinted by biome in game; their textures are grey.
    for name, rgb in {"grass_block": (110, 160, 70, 255), "short_grass": (100, 150, 60, 255), "water": (60, 90, 200, 180)}.items():
        result["minecraft:" + name] = rgb
    for block in result:
        if block.endswith("_leaves") and block != "minecraft:cherry_leaves":
            result[block] = (70, 120, 50, 255)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(result, sort_keys=True))
    return result


def color(state: str, version: str = DEFAULT_VERSION) -> tuple[int, int, int, int]:
    name, _ = split_state(state)
    return colors(version).get(name, (255, 0, 255, 255))
