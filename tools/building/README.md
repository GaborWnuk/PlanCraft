# Real buildings to BuildPaste builds

A deterministic toolchain that turns a real building into a BuildPaste build at 1:1 scale
(one block is one metre), checks it in a real game, and only then gets uploaded.

```
building.yaml + palette.yaml  ->  compile  ->  out/build.json  ->  review (real game)  ->  /pastefile, /upload
   (centimetres, from plans)      (voxels,      (BuildPaste       (paste, read back,
                                   validation,    JSON)              diff, screenshots)
                                   previews)
```

Nothing is placed by hand. The whole build is described in a model, compiled in one go
and pasted in one go, so the same inputs always give the same blocks.

## Setup

Python 3.11 or newer:

```sh
cd tools/building
pip install -r requirements.txt
python -m building registry          # block list and preview colours for 26.1.2, cached in .cache/
python -m pytest -q tests
```

The in-game review also needs the Gradle build of the mod to work (Java 25; see the main
README). It runs the Fabric client gametest, which opens a real 26.1.2 client.

## A project

Projects live in `buildings/<slug>/` at the repository root. That folder is ignored by git
because plans of real homes are often private; add a project you want to share with
`git add -f`.

```sh
python -m building new "Warsaw Tower"               # buildings/warsaw-tower/ with templates
python -m building compile buildings/warsaw-tower   # out/build.json, out/meta.json, out/preview/
python -m building slice buildings/warsaw-tower 2   # one layer, as an image
python -m building review --project buildings/warsaw-tower
```

| File | What it holds |
| --- | --- |
| `building.yaml` | levels and parts, in centimetres: x east, z south, elevations up |
| `palette.yaml` | material names to block states, with `slab`, `stairs` variants |
| `sources.yaml` | where every number came from, and PDF sheet calibrations |
| `out/` | compiled build, metadata (the warp tables), previews; regenerated |

### Parts

| Type | Meaning |
| --- | --- |
| `slab`, `box` | a polygon between two elevations (foundations, floors, chimneys) |
| `wall` | a path with `thickness`, `bottom`, `top`, `outside: left/right`, `openings` |
| `room` | clears the air of a room and lays its `finish`; checked for reachability |
| `clear` | carves air (stair wells, double-height spaces) |
| `stair`, `spiral_stair` | flights between two levels; a landing fills the rest of the well |
| `roof` | sloped or flat; `smooth: slabs`, `stairs` or `none`; `underside`, `cover`, `down_to` |
| `block`, `bed` | single placed blocks and furniture |

Openings take `at` (cm along the path), `width`, `bottom`, `top` and a `kind`: `window`
(default, glass pane), `door`, `hole` or `garage`. Doors can carry a `transom`.

Elevations may name a level with an offset: `first`, `first-30`, `roof+20`.

## Quantisation

A one metre grid cannot show a 12 cm partition or a 2.65 m room exactly. The default
`quantize: ceil` mode warps the grid instead of rounding it:

* Every wall face and level is a breakpoint. Each pair of facing breakpoints with open space
  between them gets `ceil(gap / scale - tolerance)` blocks, so a room never shrinks and walls
  never clip into furniture or each other. Spans that face nothing keep `floor` of their
  length, so the building only grows where a room needs it.
* Structural walls get at least one block.
* Interior walls up to `thin_wall` (15 cm) are not blocks at all: they are open trapdoors
  (`panel`, default pale oak) standing on the cell edge, with doors in the same plane.
* Exterior walls thinner than `glazed_below` (25 cm) are glazing: `glass_pane` bodies with
  pillars of the wall material at corners.
* Pillars between neighbouring openings are kept: if two windows would touch, the wider
  one gives up a block, or a one block window slides aside.
* Solids narrower than a block still get the cell that holds their middle.

Tune it per project:

```yaml
quantize: ceil          # or: round, the plain uniform grid
quantization:
  tolerance: 0.1        # blocks = ceil(length / scale - tolerance)
  thin_wall: 15         # cm
  glazed_below: 25      # cm
  panel: minecraft:pale_oak_trapdoor
```

A wall can force a mode with `edge: true/false` or `glazed: true/false`.

`compile` reports the size, warnings (lost piers, unreachable rooms, invalid states) and
writes the warp tables to `out/meta.json`; tools that map grid cells back to centimetres
read them from there.

## Working from PDF plans

CAD exports keep exact vector geometry. Calibrate a sheet once in `sources.yaml`:

```yaml
sheets:
  ground:
    file: plans/ground-floor.pdf    # relative to the project folder
    page: 0
    scale: 100                      # 1:100
    origin_pt: [123.4, 567.8]       # page point of model (0, 0)
    level: ground
```

| Command | Use |
| --- | --- |
| `pdf-words <pdf> --pattern 'D\d'` | dimension texts and labels with their positions |
| `pdf-lines <pdf> --summary` | vector lines by width, to find wall strokes |
| `pdf-walls <pdf> --scale 100 --origin x,y` | wall faces and thicknesses, in centimetres |
| `pdf-render <pdf> out.png --clip ...` | a region at a chosen DPI |
| `pdf-grid <project> <sheet>` | the sheet with a centimetre grid, to read coordinates |
| `pdf-overlay <project> <sheet>` | the compiled layer drawn over the sheet |

The overlay is the main check that the model matches the drawing: solid cells, panels
(green bars on their edge), glass and openings are drawn at their warped extents.

## Review in the real game

```sh
python -m building review --project buildings/<slug>
python -m building review --build some.json --ground-layer 1
```

This starts the Fabric client gametest (`:26.1.2-fabric:runClientGameTest`) in a brand
new flat world, so there is nothing to reset or clean up. The game pastes the build through
the same code as `/pastefile`, exports the region back, and photographs four elevations,
four three-quarter views, a plan view and every room. Results land in
`build/review/<slug>/`:

* `summary.json`: `ok`, timing and the cell by cell diff between the build and what the
  game holds;
* `shots/`: the screenshots;
* `gradle.log`: the full game log.

A build is ready only when the diff is empty, `compile` has no warnings that matter,
and the screenshots match the photos and visualisations.

## Into a server

Copy `out/build.json` to `buildpaste/builds/<name>.json` in a server folder and run
`/pastefile <name>` as an operator; `/undopaste` takes it away again. Upload to
buildpaste.net with `/upload` only once the build has been approved.
