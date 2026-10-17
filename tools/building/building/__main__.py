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

    p = sub.add_parser("diff", help="compare two build JSON files cell by cell")
    p.add_argument("expected")
    p.add_argument("actual")
    p.set_defaults(func=cmd_diff)

    project.add_commands(sub)
    from . import pdfplan

    pdfplan.add_commands(sub)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
