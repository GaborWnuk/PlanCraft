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

## Copilot-assisted workflow

For the complete workflow from a building's name or plans, use these tools with an LLM
assistant such as **GitHub Copilot in VS Code**, following the bundled
[real-building skill](../../.github/skills/real-building/SKILL.md). Copilot researches the
building, interprets references, writes the model, runs the tools and reviews real-game
screenshots with you. The compiler and read-back checks are deterministic; research and
visual interpretation still need review. Varso Tower in the
[main README](../../README.md#real-buildings) demonstrates the result.

See [Use with GitHub Copilot](../../README.md#use-with-github-copilot) for setup, the required
skills and an example request. Use the
[deploy-build-to-server skill](../../.github/skills/deploy-build-to-server/SKILL.md) when an
approved build is ready for an existing world. The CLI below can also be used directly
with a manually authored model; an LLM is not a runtime dependency of the compiler or mod.

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

Projects live in `buildings/<slug>/` at the repository root. The shared
[Varso Tower project](../../buildings/varso-tower/README.md) includes its model, generator
and a ready-to-paste build file. See [using included buildings](../../buildings/README.md)
to paste it in singleplayer or on a server without compiling.

Other projects are ignored by git because plans of real homes are often private.
Publishing another project requires a deliberate, reviewed allowlist change; never force-add
private plans, research images or their derived builds.

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
| `cells` | explicit plan points, each filling the cell that holds it between two elevations (rasterised patterns from a generator) |
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

Render distance is chosen from the camera positions and build bounds (at least 10 chunks),
with a margin so distance fog does not hide the far side of the build.
Tall buildings need more distant cameras; views requiring more than 32 chunks are rejected
instead of silently photographing unloaded parts of the build.

Before each shot the harness force-loads the chunks round the camera (teleporting into
unloaded chunks can stall the lockstep test server), rebuilds the renderer's section graph
after the jump, and waits until sections of the build itself are compiled. Occlusion culling
is off during the shots and back on for the walkthrough.

A build is ready only when the diff is empty, `compile` has no warnings that matter,
and the screenshots match the photos and visualisations.

## Into a server

Copy `out/build.json` to `buildpaste/builds/<name>.json` in the server's root folder (next
to `mods`, not inside the world) and run `/pastefile <name>` as an operator with mod 2.3.1
or newer; `/undopaste` takes it away again. The paste starts one block east of the player's
feet and grows north, in the direction the player faces.

Check the height before pasting. The default Overworld ends at y 319 and blocks above it
are dropped:

```sh
python -m building fit --project buildings/<slug> --origin-y 64
# fits, clipped_above, max_origin_y (highest feet y that still fits), top_needed
python -m building height-pack --out build/ --top 447
```

`height-pack` writes a datapack, generated from the game's own Overworld dimension type,
that keeps the bottom at y -64 and raises the top to at least `--top` (rounded up to a
multiple of 16). Copy it into the world's `datapacks` folder and restart the server
(`/reload` is not enough). Existing chunks load unchanged; singleplayer worlds show a
one-off "experimental settings" warning. Mods that set world height (Tectonic's
`increased_height`, for example) may override it, so test on a copy of the world first.

### Uploading to buildpaste.net

Upload only once the build has been approved. Payloads of about 16 MB fail on the server
with HTTP 500; 8.5 MB works. Split big builds into stacked, lossless sections:

```sh
python -m building sections --project buildings/<slug> --origin X Y Z --title "Varso Tower Warsaw"
```

Each section lists its layer range, estimated payload, `pos1`/`pos2` world corners for a
build pasted from feet position `X Y Z`, and a name with a timestamp (the site shows no
upload dates). Paste the build, select each section with `/pos1` and `/pos2`, face north
and `/upload <name>`. The id comes back in chat through [Publish]; then check it:

```sh
python -m building verify-upload --project buildings/<slug> --id <id> --layers 0 150
```

That downloads the upload and compares it cell by cell with the same layers of the local
build. Default properties the game adds on read-back (`waterlogged=false` and the like) are
accepted; any other difference fails.

## Walk around the model

```sh
python -m building walkthrough --project <project> --game-dir <new-instance-minecraft-folder> --white-panels
```

This runs a new read-back review, then copies the saved world and the compiled local build
into a **new** game directory. Existing game directories are rejected. Install the matching
BuildPaste mod and its dependencies in that isolated instance, then open its singleplayer
world from your normal launcher. Walkthrough reports use `build/review/<slug>-walkthrough/`
so the normal review's screenshots are preserved. The world starts in adventure mode outside
the building:
walk without accidentally breaking anything, or use `/gamemode spectator` to fly through walls.
Use `/gamemode adventure` to return to collision-aware inspection.

The optional `--white-panels` resource pack replaces pale oak trapdoor model textures with
a generated, uniform near-white texture (RGB 242, 242, 242). Enable it in Options > Resource
Packs; disable it to compare with the vanilla appearance. It preserves panel thickness and
collision and includes no copied
game textures. It affects **all** pale oak trapdoors in that client. There is no vanilla
opaque, unpatterned white vertical half-slab: white concrete is a full block, iron trapdoors
have holes, and white stained-glass panes are translucent.

**A resource pack does not travel with a BuildPaste upload.** Other players see vanilla
trapdoors unless they enable the same pack. The generated `walkthrough.json` records the
exact selection corners and copied build path. Account linking and upload are separate:
launch with your own Minecraft account, sign into the intended buildpaste.net account,
follow `/connectaccounts`, then select the recorded corners with `/pos1` and `/pos2`.
Do not run `/upload` until the model and its vanilla-versus-resource-pack appearance have
been explicitly approved.
