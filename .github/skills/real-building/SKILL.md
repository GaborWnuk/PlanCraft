---
name: real-building
description: Recreate a real building in Minecraft (26.1+) at 1:1 scale from its name, public sources or private plans. Research the building, model it in YAML, compile it deterministically to a BuildPaste build, paste it in one go into a fresh real game world, judge it from read-back and screenshots, and upload to buildpaste.net only after explicit approval.
---

# Real building to Minecraft

One block is one metre. The building is described once, as data, and everything after that is
done by deterministic tools in [tools/building](../../../tools/building/README.md). Nothing is placed
by hand in the game: the compiled build is pasted in one operation into a brand-new world, read
back, compared and photographed.

All commands run from `tools/building` (`pip install -r requirements.txt` once, Java 25 for the game).

## 1. Research

For a named building, collect before modelling:

- Official sources first: owner/architect pages, heritage registers, planning documents,
  published plans and sections. Then encyclopaedias, papers, reputable photo collections.
- Key numbers: footprint dimensions, total height, storey count and storey heights, roof
  shape and pitch, structural grid, setbacks, spire/antenna heights.
- Facade: materials and colours per elevation, window rhythm (bay widths, pier widths,
  mullions), entrances, balconies, cornices.
- Photos from every side, plus aerial/oblique views for the roof; interiors where public.
- Record every source in `sources.yaml` with URL, what it was used for and its licence.
  Prefer measured values over values estimated from photos, and note which is which.

For private plans (for example someone's own house): keep the plans, photos and the project
folder under `buildings/` (ignored) and add the folder name to `.git/info/exclude`. Never commit
or upload private material or anything derived from it.

## 2. Model

```
python -m building new "Building name"          # creates buildings/<slug>/
python -m building pdf-words|pdf-lines|pdf-walls|pdf-grid <sheet.pdf> ...   # read plans
```

Describe the building in `building.yaml` in centimetres (rooms, walls, openings, slabs,
boxes, roof, stairs) and choose blocks in `palette.yaml`. Calibrate each plan sheet once and
check every floor with `pdf-overlay` before going further.

## 3. Compile and check

```
python -m building compile <project>
python -m building slice <project> <layer>
```

Fix every warning; the target is zero. The quantisation rules the compiler applies:

- **Ceil warp**: the grid is warped so every room keeps at least its real clear size
  (rounded up) and thin elements never clip; overall size grows slightly as a result.
- **Thin interior walls** become half-width edge panels (open trapdoors), not full blocks.
- **Thin exterior walls are glazing**: `glass_pane` (never glass blocks) with the solid
  piers between windows preserved; a too-narrow pier slides a 1-block window aside.
- **Thin solids** narrower than a block still get a footprint so nothing disappears.
- **Stairs** get a landing fill so the upper floor is reachable.
- **Sloped roofs** use `smooth: stairs` for definition and `cover` with the `underside`
  material where the roof is a single layer.

## 4. Review in the real game

```
python -m building review --project <project>
```

This runs the Fabric client gametest in a fresh world, pastes the build, reads it back and
writes `build/review/<slug>/` (`summary.json`, `readback.json`, `shots/`, `gradle.log`).
Every review is a new world, so there is nothing to clean up; `/undopaste` removes a paste in a
normal world.

Quality bar, all required:

- `diff.mismatch_count` is 0 and the compile has 0 warnings.
- Every room is reachable (validation passes).
- Screenshots match the photos side by side: massing, roof, window rhythm, materials.
  Look at every shot: a blank or fog-only elevation is a harness or camera problem
  (check `gradle.log` for "still incomplete"), not proof that the build is fine.
- Interior cameras point at the space they are named after, not into a core wall or a hedge.
- Interiors have no gaps, no clipped walls and sensible ceilings.

Iterate on the YAML, not on the world, until the bar is met. Report the remaining trade-offs
(scale growth from the ceil warp, uncertain interpretations of the sources) to the user.

## 5. Walk around (optional)

```
python -m building walkthrough --project <project> --game-dir <new-instance-minecraft-folder>
```

Copies a freshly verified world into a **new** game directory for the user to walk through.
Never install into, launch or modify the user's own launcher instances unless they ask for
that specific change; prefer a dedicated instance.

## 6. Publish

Only after the user explicitly approves the result. Never upload private buildings unless the
user asks for that specific build. Commands and details: "Into a server" in the toolchain README.

- **Local paste**: the compiled `out/build.json` goes to `<server or game root>/buildpaste/builds/<name>.json`;
  `/pastefile <name>` needs mod 2.3.1+ and operator rights, and starts at the player's feet
  facing north. Run `python -m building fit --project <project> --origin-y <feet y>` first; if
  `fits` is false, paste from `max_origin_y` or lower, or raise the world's top with
  `height-pack` (server restart required). For an existing server world, follow the
  [deploy-build-to-server](../deploy-build-to-server/SKILL.md) skill.
- **buildpaste.net upload**: run `sections` first. Uploads of about 16 MB fail with HTTP 500,
  so tall builds go up as stacked, lossless layer sections in the tight box. Every name
  carries a timestamp (the site shows no dates), for example
  "Varso Tower Warsaw 2026-10-18 09:32 part 1 of 2". Paste the build in a review world,
  select each section's `pos1`/`pos2`, face north, `/upload <name>`, take the id from
  [Publish], then `verify-upload --id <id> --layers <first> <last>` must report
  `mismatch_count` 0. Report every id, name and description to the user.
