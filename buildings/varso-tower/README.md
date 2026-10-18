# Varso Tower, Warsaw

A detailed 1:1 recreation of Foster + Partners' Varso Tower: glazed facades, cores, a
continuous service stair, representative office interiors, landscaped terraces, the lobby
and west urban room, and the 310 m spire.

[Real photo and Minecraft comparison](../../README.md#real-buildings)

## Paste without compiling

Download [out/build.json](out/build.json) using **Download raw file**, rename it
`varso-tower.json` and follow the [singleplayer/server instructions](../README.md#use-in-your-game).
The file is included in the repository, so compilation and website uploads are optional.

- Tested with BuildPaste 2.3.1 on Minecraft Java Edition 26.1.2.
- Stored dimensions: **94 x 313 x 68**. Occupied layers: **0 through 310**; the two upper
  stored layers are air. There are **190,392 non-air blocks**.
- North-facing footprint: from one block east of your feet to 94 blocks east, and from
  67 blocks north to your current z coordinate.
- Uses vanilla blocks; no custom block or shader pack is required.

## World height

The spire tip lands at **feet y + 310**. The default Overworld's highest buildable block is
y 319, so the highest safe feet position is **y 9**. At sea level (y 64), the tip would
be at y 374 and **293 non-air blocks would be clipped**.

Either choose an origin at y 9 or lower, or raise the world's build ceiling first.
Low placement can bury the tower in terrain, so rehearse on a copy of your world.
For an existing sea-level site, the toolchain can generate a taller Overworld datapack.
From the repository root in PowerShell, after the
[toolchain setup](../../tools/building/README.md#setup):

```powershell
# Prepare the matching game's cached files for datapack generation.
.\gradlew.bat :26.1.2-fabric:build
Set-Location tools\building
python -m building fit --project varso-tower --origin-y 64
# The fit command intentionally exits with status 1 when the build would be clipped.
python -m building height-pack --out ..\..\build --top 447 --version 26.1.2
python -m building fit --project varso-tower --origin-y 64 --top 447
```

Copy the generated `build\tall-overworld` folder into `<world>\datapacks`, then fully
restart the server or close and reopen singleplayer. `/reload` alone is not enough.
This pack keeps the bottom at y -64 and raises the top to y 447; it does not move existing
terrain. Singleplayer may show an experimental-settings warning.

Back up first and test on a copy, especially with world-generation or height-changing
mods. Generate the pack for the actual game version; do not assume a 26.1.2 datapack is
compatible with other releases. Once height is confirmed, stand on solid ground facing
north and `/pastefile varso-tower`. Water or falling changes your actual feet y.

## Edit and rebuild

| File | Purpose |
| --- | --- |
| [building.yaml](building.yaml) | Complete model in centimetres, ready to compile |
| [palette.yaml](palette.yaml) | Materials and vanilla block states |
| [sources.yaml](sources.yaml) | Public reference URLs, measurements, rights and limitations |
| [generate.py](generate.py) | Regenerates the model from encoded measurements and geometry |
| [trace.py](trace.py) | Optional research helper for local plan images; not needed to generate or compile |
| [out/build.json](out/build.json) | Complete ready-to-paste build; includes air for clearing the site |

After installing the toolchain dependencies, from the repository root:

```powershell
# Optional: overwrites building.yaml from the generator's encoded geometry.
python buildings\varso-tower\generate.py
Set-Location tools\building
python -m building compile varso-tower --no-preview
python -m building review --project varso-tower
```

The generator and compiler do not require the original drawings. The optional tracing
helper does require locally obtained plan images at the names listed in `trace.py`.
Those copyrighted research images are intentionally **not redistributed**.
Generated previews, validation metadata and local references remain ignored.

## Accuracy and scope

Published heights and reference plans guide the model, but the one-metre grid simplifies
some geometry. Tenant interiors are representative, not surveyed fit-outs. Lift shafts
are architectural representations, not working lifts; the service stair is simplified.
Neighbouring Varso 1/2 and basement parking are omitted. See
[sources.yaml](sources.yaml) for the full assumptions and source rights.

The model and generator are covered by the repository's [MIT licence](../../LICENSE);
this does not relicense the external photographs, drawings or source websites.
