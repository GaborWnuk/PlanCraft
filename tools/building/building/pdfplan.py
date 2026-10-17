"""Reading architectural PDF sheets: text with positions, vector lines, renders and overlays.

CAD exports keep their geometry as vectors, so wall faces, axis lines and dimension
texts can be read exactly instead of guessed from pixels. A sheet is tied to the model
by a calibration in ``sources.yaml``::

    sheets:
      A20:
        file: plans/ground-floor.pdf   # relative to the project folder
        page: 0
        scale: 100            # drawing scale, 1:100
        origin_pt: [123.4, 567.8]   # page point of model (0, 0)
        level: ground         # the layer drawn on the overlay is the one above this floor

With that, ``cm = (pt - origin_pt) * 2.54 / 72 * scale``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image, ImageDraw

from . import buildpaste

PT_PER_CM_PAPER = 72 / 2.54


def open_pdf(path: Path) -> fitz.Document:
    return fitz.open(str(path))


# All coordinates below are in the page as displayed (rotation applied), in points,
# with the origin top-left and y growing down: the same frame as renders.


def _shown(pg, x: float, y: float) -> tuple[float, float]:
    p = fitz.Point(x, y) * pg.rotation_matrix
    return p.x, p.y


def words(path: Path, page: int = 0, pattern: str | None = None, clip: tuple[float, float, float, float] | None = None) -> list[dict]:
    """Every word on a page with its centre and box."""
    doc = open_pdf(path)
    pg = doc[page]
    rx = re.compile(pattern) if pattern else None
    out = []
    for x0, y0, x1, y1, text, *_ in pg.get_text("words"):
        if rx and not rx.fullmatch(text):
            continue
        ax, ay = _shown(pg, x0, y0)
        bx, by = _shown(pg, x1, y1)
        ax, bx = sorted((ax, bx))
        ay, by = sorted((ay, by))
        if clip and not (clip[0] <= (ax + bx) / 2 <= clip[2] and clip[1] <= (ay + by) / 2 <= clip[3]):
            continue
        out.append({"text": text, "x": round((ax + bx) / 2, 2), "y": round((ay + by) / 2, 2), "box": [round(v, 2) for v in (ax, ay, bx, by)], "dir": "vertical" if (by - ay) > (bx - ax) * 1.2 and len(text) > 1 else "horizontal"})
    return out


def segments(path: Path, page: int = 0, min_length: float = 0.0) -> list[dict]:
    """Straight lines from the page's vector drawings, with their style."""
    doc = open_pdf(path)
    pg = doc[page]
    out = []
    for d in pg.get_drawings():
        width = d.get("width") or 0
        color = d.get("color")
        fill = d.get("fill")
        dashes = d.get("dashes")
        for item in d["items"]:
            if item[0] == "l":
                a, b = item[1], item[2]
                pts = [(a.x, a.y), (b.x, b.y)]
            elif item[0] == "re":
                r = item[1]
                pts = [(r.x0, r.y0), (r.x1, r.y0), (r.x1, r.y1), (r.x0, r.y1), (r.x0, r.y0)]
            else:
                continue
            pts = [_shown(pg, x, y) for x, y in pts]
            for (ax, ay), (bx, by) in zip(pts, pts[1:]):
                length = ((bx - ax) ** 2 + (by - ay) ** 2) ** 0.5
                if length < min_length:
                    continue
                out.append(
                    {
                        "a": [round(ax, 2), round(ay, 2)],
                        "b": [round(bx, 2), round(by, 2)],
                        "len": round(length, 2),
                        "width": round(width, 3),
                        "color": [round(c, 2) for c in color] if color else None,
                        "fill": [round(c, 2) for c in fill] if fill else None,
                        "dashes": dashes if dashes and dashes != "[] 0" else None,
                    }
                )
    return out


def filled_polygons(path: Path, page: int = 0, min_area: float = 1.0) -> list[dict]:
    """Closed filled shapes (wall hatches and poché are usually these), as point lists."""
    doc = open_pdf(path)
    pg = doc[page]
    out = []
    for d in pg.get_drawings():
        if not d.get("fill"):
            continue
        r = d["rect"] * pg.rotation_matrix
        if r.width * r.height < min_area:
            continue
        pts = []
        for item in d["items"]:
            if item[0] == "l":
                pts += [(item[1].x, item[1].y), (item[2].x, item[2].y)]
            elif item[0] == "re":
                q = item[1]
                pts += [(q.x0, q.y0), (q.x1, q.y0), (q.x1, q.y1), (q.x0, q.y1)]
            elif item[0] == "qu":
                q = item[1]
                pts += [(p.x, p.y) for p in (q.ul, q.ur, q.lr, q.ll)]
        pts = [_shown(pg, x, y) for x, y in pts]
        out.append({"rect": [round(v, 2) for v in (r.x0, r.y0, r.x1, r.y1)], "fill": [round(c, 2) for c in d["fill"]], "points": [[round(x, 2), round(y, 2)] for x, y in pts]})
    return out


def render(path: Path, page: int = 0, dpi: int = 150, clip: tuple[float, float, float, float] | None = None) -> Image.Image:
    doc = open_pdf(path)
    pix = doc[page].get_pixmap(dpi=dpi, clip=fitz.Rect(*clip) if clip else None)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


class Calibration:
    """Maps model centimetres to page points for one sheet."""

    def __init__(self, scale: float, origin_pt: tuple[float, float]):
        self.scale = float(scale)
        self.ox, self.oy = origin_pt

    @property
    def pt_per_cm(self) -> float:
        return PT_PER_CM_PAPER / self.scale

    def to_pt(self, x_cm: float, z_cm: float) -> tuple[float, float]:
        return self.ox + x_cm * self.pt_per_cm, self.oy + z_cm * self.pt_per_cm

    def to_cm(self, x_pt: float, y_pt: float) -> tuple[float, float]:
        return (x_pt - self.ox) / self.pt_per_cm, (y_pt - self.oy) / self.pt_per_cm


def cm_grid(img: Image.Image, cal: Calibration, dpi: int, clip_pt: tuple[float, float] = (0, 0), step_cm: float = 100, label_every: int = 1) -> Image.Image:
    """Draw model-coordinate grid lines (every ``step_cm``) with cm labels over a rendered sheet."""
    k = dpi / 72
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    w_pt, h_pt = img.size[0] / k, img.size[1] / k
    x_lo, z_lo = cal.to_cm(clip_pt[0], clip_pt[1])
    x_hi, z_hi = cal.to_cm(clip_pt[0] + w_pt, clip_pt[1] + h_pt)
    import math

    for axis, lo, hi in (("x", x_lo, x_hi), ("z", z_lo, z_hi)):
        i = math.ceil(lo / step_cm)
        while i * step_cm <= hi:
            v = i * step_cm
            strong = i % label_every == 0
            colour = (0, 140, 255, 170) if strong else (0, 140, 255, 70)
            if axis == "x":
                px = (cal.to_pt(v, 0)[0] - clip_pt[0]) * k
                d.line([(px, 0), (px, img.size[1])], fill=colour, width=1)
                if strong:
                    d.text((px + 2, 2), f"{v:g}", fill=(0, 90, 200, 255))
            else:
                py = (cal.to_pt(0, v)[1] - clip_pt[1]) * k
                d.line([(0, py), (img.size[0], py)], fill=colour, width=1)
                if strong:
                    d.text((2, py + 2), f"{v:g}", fill=(0, 90, 200, 255))
            i += 1
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


def overlay(sheet_pdf: Path, page: int, cal: Calibration, grid, frame, layer: int, dpi: int = 150, alpha: int = 110) -> Image.Image:
    """The sheet with one grid layer drawn over it: solid cells red, openings blue, panels green.

    Cells are drawn where their block edges fall in centimetres (through the frame's warp),
    and partition panels as a bar on the edge they stand against.
    """
    base = render(sheet_pdf, page, dpi).convert("RGBA")
    k = dpi / 72
    layer_img = Image.new("RGBA", base.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer_img)
    xs = [frame.wx.inv(i) for i in range(grid.size_x + 1)]
    zs = [frame.wz.inv(i) for i in range(grid.size_z + 1)]
    for gx in range(grid.size_x):
        for gz in range(grid.size_z):
            state = grid.get(gx, layer, gz)
            if state == "minecraft:air":
                continue
            name = state.split("[")[0]
            cx0, cx1, cz0, cz1 = xs[gx], xs[gx + 1], zs[gz], zs[gz + 1]
            if name.endswith("_trapdoor") and "open=true" in state:
                facing = state.split("facing=")[1].split(",")[0].rstrip("]")
                bar = 12.0  # cm drawn for the panel
                cx0, cx1, cz0, cz1 = {
                    "east": (cx0, cx0 + bar, cz0, cz1),
                    "west": (cx1 - bar, cx1, cz0, cz1),
                    "south": (cx0, cx1, cz0, cz0 + bar),
                    "north": (cx0, cx1, cz1 - bar, cz1),
                }[facing]
                colour = (0, 170, 60, 220)
            elif any(t in name for t in ("pane", "glass", "door")):
                colour = (40, 90, 255, alpha)
            else:
                colour = (255, 40, 40, alpha)
            ax, ay = cal.to_pt(cx0, cz0)
            bx, by = cal.to_pt(cx1, cz1)
            draw.rectangle([min(ax, bx) * k, min(ay, by) * k, max(ax, bx) * k, max(ay, by) * k], fill=colour)
    return Image.alpha_composite(base, layer_img).convert("RGB")


# ---------------------------------------------------------------- walls


def _merge(intervals: list[tuple[float, float]], tolerance: float) -> list[list[float]]:
    out: list[list[float]] = []
    for a, b in sorted(intervals):
        if out and a <= out[-1][1] + tolerance:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _subtract(interval: tuple[float, float], used: list[tuple[float, float]]) -> list[tuple[float, float]]:
    pieces = [interval]
    for ua, ub in used:
        nxt = []
        for a, b in pieces:
            if ub <= a or ua >= b:
                nxt.append((a, b))
                continue
            if a < ua:
                nxt.append((a, ua))
            if ub < b:
                nxt.append((ub, b))
        pieces = nxt
    return pieces


def detect_walls(
    segs: list[dict],
    min_width: float = 0.9,
    min_thickness_pt: float = 2.0,
    max_thickness_pt: float = 16.0,
    min_length_pt: float = 1.0,
    snap: float = 0.15,
) -> list[dict]:
    """Wall pieces from pairs of parallel thick outline lines, in page points.

    Each face is used once, pairing closest faces first, so the inside of a room is never
    mistaken for a wall as long as rooms are wider than ``max_thickness_pt``.
    """
    walls = []
    for horizontal in (True, False):
        rows: dict[float, list[tuple[float, float]]] = {}
        for sg in segs:
            if sg["width"] < min_width:
                continue
            (ax, ay), (bx, by) = sg["a"], sg["b"]
            if horizontal and abs(ay - by) < 0.05:
                key, a, b = (ay + by) / 2, min(ax, bx), max(ax, bx)
            elif not horizontal and abs(ax - bx) < 0.05:
                key, a, b = (ax + bx) / 2, min(ay, by), max(ay, by)
            else:
                continue
            k = round(key / snap) * snap
            rows.setdefault(round(k, 3), []).append((a, b))
        runs = []
        for k, ivs in rows.items():
            for a, b in _merge(ivs, 0.3):
                runs.append((k, a, b))
        candidates = []
        for i, (k1, a1, b1) in enumerate(runs):
            for j, (k2, a2, b2) in enumerate(runs):
                gap = k2 - k1
                if not (min_thickness_pt <= gap <= max_thickness_pt):
                    continue
                lo, hi = max(a1, a2), min(b1, b2)
                if hi - lo >= min_length_pt:
                    candidates.append((gap, i, j, lo, hi))
        candidates.sort()
        used_low: dict[int, list] = {}
        used_high: dict[int, list] = {}
        for gap, i, j, lo, hi in candidates:
            for a, b in _subtract((lo, hi), used_low.get(i, []) + used_high.get(j, [])):
                if b - a < min_length_pt:
                    continue
                used_low.setdefault(i, []).append((a, b))
                used_high.setdefault(j, []).append((a, b))
                centre = runs[i][0] + gap / 2
                if horizontal:
                    walls.append({"a": [a, centre], "b": [b, centre], "thickness": gap})
                else:
                    walls.append({"a": [centre, a], "b": [centre, b], "thickness": gap})
    return walls


def walls_in_cm(walls: list[dict], cal: "Calibration", round_to: float = 1.0) -> list[dict]:
    out = []
    for w in walls:
        a = cal.to_cm(*w["a"])
        b = cal.to_cm(*w["b"])
        t = w["thickness"] / cal.pt_per_cm
        r = lambda v: round(v / round_to) * round_to
        out.append({"path": [[r(a[0]), r(a[1])], [r(b[0]), r(b[1])]], "thickness": r(t)})
    return out


def draw_walls(img: Image.Image, walls: list[dict], dpi: int, origin_pt: tuple[float, float] = (0, 0), colour=(255, 0, 0, 120)) -> Image.Image:
    k = dpi / 72
    layer = Image.new("RGBA", img.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for w in walls:
        (ax, ay), (bx, by), t = w["a"], w["b"], w["thickness"]
        if abs(ay - by) < 0.01:
            box = [min(ax, bx), ay - t / 2, max(ax, bx), ay + t / 2]
        else:
            box = [ax - t / 2, min(ay, by), ax + t / 2, max(ay, by)]
        d.rectangle([(box[0] - origin_pt[0]) * k, (box[1] - origin_pt[1]) * k, (box[2] - origin_pt[0]) * k, (box[3] - origin_pt[1]) * k], fill=colour)
    return Image.alpha_composite(img.convert("RGBA"), layer).convert("RGB")


# ---------------------------------------------------------------- CLI


def _clip(text: str | None):
    return tuple(float(v) for v in text.split(",")) if text else None


def cmd_words(args) -> int:
    for w in words(Path(args.pdf), args.page, args.pattern, _clip(args.clip)):
        print(json.dumps(w, ensure_ascii=False))
    return 0


def cmd_lines(args) -> int:
    segs = segments(Path(args.pdf), args.page, args.min_length)
    if args.clip:
        x0, y0, x1, y1 = _clip(args.clip)
        segs = [s for s in segs if all(x0 <= p[0] <= x1 and y0 <= p[1] <= y1 for p in (s["a"], s["b"]))]
    if args.width is not None:
        segs = [s for s in segs if abs(s["width"] - args.width) < 1e-3]
    if args.summary:
        from collections import Counter

        c = Counter((s["width"], tuple(s["color"] or ()), str(s["dashes"])) for s in segs)
        for (w, col, dash), n in c.most_common():
            print(f"{n:6}  width={w}  color={col}  dashes={dash}")
        return 0
    for s in segs:
        print(json.dumps(s))
    return 0


def cmd_render(args) -> int:
    img = render(Path(args.pdf), args.page, args.dpi, _clip(args.clip))
    img.save(args.out)
    print(args.out)
    return 0


def cmd_overlay(args) -> int:
    from . import project as project_mod

    proj = project_mod.load(Path(args.project))
    sources = project_mod._yaml(proj.folder / "sources.yaml")
    sheet = (sources.get("sheets") or {})[args.sheet]
    pdf = (proj.folder / sheet["file"]).resolve()
    meta = proj.meta()
    from .model import Frame

    frame = Frame.from_meta(meta)
    m = proj.model()
    level = m.elevation(sheet.get("level", 0)) if args.layer is None else None
    layer = args.layer if args.layer is not None else frame.cy(level) + int(sheet.get("layer_offset", 1))
    grid = buildpaste.read(proj.build_file)
    img = overlay(pdf, int(sheet.get("page", 0)), Calibration(sheet["scale"], sheet["origin_pt"]), grid, frame, layer, args.dpi)
    out = Path(args.out) if args.out else proj.out / "preview" / f"overlay-{args.sheet}-y{layer}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.crop:
        img = img.crop(tuple(int(v * args.dpi / 72) for v in _clip(args.crop)))
    img.save(out)
    print(out)
    return 0


def cmd_grid(args) -> int:
    from . import project as project_mod

    proj = project_mod.load(Path(args.project))
    sheet = (project_mod._yaml(proj.folder / "sources.yaml").get("sheets") or {})[args.sheet]
    pdf = (proj.folder / sheet["file"]).resolve()
    cal = Calibration(sheet["scale"], sheet["origin_pt"])
    if args.area:
        x0, z0, x1, z1 = _clip(args.area)
        (ax, ay), (bx, by) = cal.to_pt(x0, z0), cal.to_pt(x1, z1)
        clip = (ax, ay, bx, by)
    else:
        clip = _clip(args.clip)
    img = render(pdf, int(sheet.get("page", 0)), args.dpi, clip)
    img = cm_grid(img, cal, args.dpi, (clip[0], clip[1]) if clip else (0, 0), args.step, args.label_every)
    out = Path(args.out) if args.out else proj.out / "preview" / f"grid-{args.sheet}.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(out)
    return 0


def cmd_walls(args) -> int:
    import yaml

    pdf = Path(args.pdf)
    clip = _clip(args.clip)
    segs = segments(pdf, args.page)
    if clip:
        segs = [g for g in segs if all(clip[0] <= p[0] <= clip[2] and clip[1] <= p[1] <= clip[3] for p in (g["a"], g["b"]))]
    cal = Calibration(args.scale, tuple(float(v) for v in args.origin.split(",")))
    walls = detect_walls(segs, args.min_line_width, args.min_thickness * cal.pt_per_cm, args.max_thickness * cal.pt_per_cm, args.min_length * cal.pt_per_cm)
    pieces = walls_in_cm(walls, cal)
    text = yaml.safe_dump({"walls": pieces}, sort_keys=False, default_flow_style=None, width=200)
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
        print(f"{len(pieces)} wall pieces -> {args.out}")
    else:
        print(text)
    if args.image:
        img = render(pdf, args.page, args.dpi, clip)
        draw_walls(img, walls, args.dpi, (clip[0], clip[1]) if clip else (0, 0)).save(args.image)
        print(args.image)
    return 0


def add_commands(sub) -> None:
    p = sub.add_parser("pdf-walls", help="detect walls (pairs of parallel thick lines) on a plan sheet")
    p.add_argument("pdf")
    p.add_argument("--page", type=int, default=0)
    p.add_argument("--scale", type=float, default=100, help="drawing scale, 100 for 1:100")
    p.add_argument("--origin", required=True, help="page point of model (0, 0) as x,y")
    p.add_argument("--clip", help="only lines inside x0,y0,x1,y1 (points)")
    p.add_argument("--min-line-width", type=float, default=0.9)
    p.add_argument("--min-thickness", type=float, default=8, help="cm")
    p.add_argument("--max-thickness", type=float, default=55, help="cm")
    p.add_argument("--min-length", type=float, default=5, help="cm")
    p.add_argument("--out", help="write YAML here")
    p.add_argument("--image", help="also draw the detected walls over the sheet")
    p.add_argument("--dpi", type=int, default=150)
    p.set_defaults(func=cmd_walls)

    p = sub.add_parser("pdf-grid", help="render a project sheet with a labelled model-coordinate (cm) grid")
    p.add_argument("project")
    p.add_argument("sheet")
    p.add_argument("--area", help="model area x0,z0,x1,z1 in cm")
    p.add_argument("--clip", help="page area x0,y0,x1,y1 in points (when --area is not given)")
    p.add_argument("--step", type=float, default=100)
    p.add_argument("--label-every", type=int, default=1)
    p.add_argument("--dpi", type=int, default=200)
    p.add_argument("--out")
    p.set_defaults(func=cmd_grid)

    p = sub.add_parser("pdf-words", help="words on a PDF page with positions in points")
    p.add_argument("pdf")
    p.add_argument("--page", type=int, default=0)
    p.add_argument("--pattern", help="regular expression a word must match in full")
    p.add_argument("--clip", help="x0,y0,x1,y1 in points")
    p.set_defaults(func=cmd_words)

    p = sub.add_parser("pdf-lines", help="straight vector lines on a PDF page")
    p.add_argument("pdf")
    p.add_argument("--page", type=int, default=0)
    p.add_argument("--min-length", type=float, default=0.0)
    p.add_argument("--clip")
    p.add_argument("--width", type=float)
    p.add_argument("--summary", action="store_true", help="count lines per style instead of listing them")
    p.set_defaults(func=cmd_lines)

    p = sub.add_parser("pdf-render", help="render a PDF page (or a clip of it) to PNG")
    p.add_argument("pdf")
    p.add_argument("out")
    p.add_argument("--page", type=int, default=0)
    p.add_argument("--dpi", type=int, default=150)
    p.add_argument("--clip")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("pdf-overlay", help="draw a compiled layer over a calibrated plan sheet")
    p.add_argument("project")
    p.add_argument("sheet")
    p.add_argument("--layer", type=int)
    p.add_argument("--dpi", type=int, default=150)
    p.add_argument("--crop", help="x0,y0,x1,y1 in points")
    p.add_argument("--out")
    p.set_defaults(func=cmd_overlay)
