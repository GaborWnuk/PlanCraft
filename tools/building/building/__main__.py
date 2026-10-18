"""Command line: ``python -m building <command>`` from ``tools/building``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import buildpaste, registry, review


def _print(obj) -> None:
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def cmd_registry(args) -> int:
    path = registry.ensure_reports(args.version)
    print(f"{len(registry.blocks(args.version))} blocks in {path}")
    print(f"{len(registry.colors(args.version))} preview colours")
    return 0


def cmd_sample(args) -> int:
    path = buildpaste.write(review.sample_build(), Path(args.out))
    print(path)
    return 0


def cmd_review(args) -> int:
    if args.project:
        from . import project

        proj = project.load(Path(args.project))
        build_file, ground, shots = proj.build_file, proj.ground_layer, proj.review_shots()
        name = args.name or proj.slug
    else:
        build_file, ground, shots, name = Path(args.build), args.ground_layer, [], args.name or Path(args.build).stem
    summary = review.run(build_file, name, ground_layer=ground, extra_shots=shots, exterior=not args.no_exterior, target=args.target)
    _print(summary)
    return 0 if summary.get("ok") else 1


def cmd_diff(args) -> int:
    result = review.diff_files(Path(args.expected), Path(args.actual))
    _print(result)
    return 0 if result["ok"] else 1


def cmd_walkthrough(args) -> int:
    from . import project, walkthrough

    proj = project.load(Path(args.project))
    _print(walkthrough.prepare(proj.build_file, Path(args.game_dir), proj.slug,
                               proj.ground_layer, args.target, args.white_panels))
    return 0


def _build_doc(args) -> dict:
    if args.project:
        from . import project

        path = project.load(Path(args.project)).build_file
    else:
        path = Path(args.build)
    return json.loads(path.read_text(encoding="utf-8"))


def cmd_sections(args) -> int:
    from datetime import datetime

    from . import publish

    plan = publish.plan_sections(_build_doc(args), args.limit)
    if args.origin:
        publish.add_selections(plan, args.origin)
    if args.title:
        stamp = args.stamp or datetime.now().strftime("%Y-%m-%d %H:%M")
        count = len(plan["sections"])
        for s in plan["sections"]:
            s["name"] = publish.upload_name(args.title, s["part"], count, stamp)
    _print(plan)
    return 0


def cmd_verify_upload(args) -> int:
    from . import publish

    result = publish.verify_upload(_build_doc(args), publish.fetch_build(args.id), args.layers)
    _print(result)
    return 0 if result["ok"] else 1


def cmd_fit(args) -> int:
    from . import publish

    result = publish.fit(_build_doc(args), args.origin_y, args.top)
    _print(result)
    return 0 if result["fits"] else 1


def cmd_height_pack(args) -> int:
    from . import publish

    print(publish.height_pack(Path(args.out), args.top, args.version, args.name))
    return 0


def _add_build_source(p) -> None:
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", help="building project folder (uses out/build.json)")
    group.add_argument("--build", help="a build JSON file")


def main(argv: list[str] | None = None) -> int:
    from . import project  # noqa: F401  (registers project commands)

    parser = argparse.ArgumentParser(prog="building")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("registry", help="generate the block registry and preview colours for a version")
    p.add_argument("--version", default=registry.DEFAULT_VERSION)
    p.set_defaults(func=cmd_registry)

    p = sub.add_parser("sample", help="write the small orientation test build")
    p.add_argument("out")
    p.set_defaults(func=cmd_sample)

    p = sub.add_parser("review", help="paste into a fresh game world, read back and photograph")
    group = p.add_mutually_exclusive_group(required=True)
    group.add_argument("--project", help="building project folder (compiles nothing; uses out/build.json)")
    group.add_argument("--build", help="a build JSON file")
    p.add_argument("--name")
    p.add_argument("--ground-layer", type=int, default=0)
    p.add_argument("--no-exterior", action="store_true", help="skip the automatic exterior views")
    p.add_argument("--target", default=review.DEFAULT_TARGET)
    p.set_defaults(func=cmd_review)

    p = sub.add_parser("walkthrough", help="verify and copy a playable world into a new game directory")
    p.add_argument("--project", required=True)
    p.add_argument("--game-dir", required=True, help="new, isolated instance's minecraft folder")
    p.add_argument("--target", default=review.DEFAULT_TARGET)
    p.add_argument("--white-panels", action="store_true", help="add an optional smooth-white panel resource pack")
    p.set_defaults(func=cmd_walkthrough)

    p = sub.add_parser("diff", help="compare two build JSON files cell by cell")
    p.add_argument("expected")
    p.add_argument("actual")
    p.set_defaults(func=cmd_diff)

    from . import publish

    p = sub.add_parser("sections", help="split a build into lossless uploads under the size limit")
    _add_build_source(p)
    p.add_argument("--limit", type=int, default=publish.DEFAULT_LIMIT, help="payload bytes per upload")
    p.add_argument("--origin", type=int, nargs=3, metavar=("X", "Y", "Z"),
                   help="where the build was pasted (player feet, facing north); adds world selections")
    p.add_argument("--title", help="upload title; adds timestamped part names")
    p.add_argument("--stamp", help="timestamp for the names (default: now, YYYY-MM-DD HH:MM)")
    p.set_defaults(func=cmd_sections)

    p = sub.add_parser("verify-upload", help="fetch an uploaded build and compare it with the local one")
    _add_build_source(p)
    p.add_argument("--id", required=True, help="buildpaste.net build id")
    p.add_argument("--layers", type=int, nargs=2, metavar=("FIRST", "LAST"),
                   help="layer range the upload covers (default: the whole tight build)")
    p.set_defaults(func=cmd_verify_upload)

    p = sub.add_parser("fit", help="check that a paste from a given height stays inside the world")
    _add_build_source(p)
    p.add_argument("--origin-y", type=int, required=True, help="y of the player's feet when pasting")
    p.add_argument("--top", type=int, default=publish.DEFAULT_TOP, help="highest buildable y (default 319)")
    p.set_defaults(func=cmd_fit)

    p = sub.add_parser("height-pack", help="write a datapack that raises the overworld build limit")
    p.add_argument("--out", required=True, help="folder to write the datapack folder into")
    p.add_argument("--top", type=int, required=True, help="highest y that must be buildable")
    p.add_argument("--version", default=registry.DEFAULT_VERSION)
    p.add_argument("--name", default="tall-overworld")
    p.set_defaults(func=cmd_height_pack)

    project.add_commands(sub)
    from . import pdfplan

    pdfplan.add_commands(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
