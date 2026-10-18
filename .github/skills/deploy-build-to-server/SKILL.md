---
name: deploy-build-to-server
description: Paste an approved BuildPaste build into an existing Minecraft server or singleplayer world without uploading to buildpaste.net. Check the mod version, world height and other mods, rehearse on a copy of the world in an isolated client, then hand the user the exact files to copy and the commands to run.
---

# Deploy a build to an existing world

For builds already approved through [real-building](../real-building/SKILL.md). The live world
belongs to the user: never change their server or instances unless they ask for that specific
change, and never paste into a world that has not been backed up.

All commands run from `tools/building`.

## 1. Gather facts

Ask for, or read from a downloaded copy of the world, but never guess:

- Minecraft and loader version, and the server's mod list. In a world copy, `level.dat`
  (`Data.ServerBrands`, `Data.WasModded`) and the server's `mods/` folder tell you this.
- The BuildPaste mod version on the server. `/pastefile` exists from 2.3.1; an older
  jar has to be replaced (remove the old jar, do not keep two versions in `mods/`).
- Where and from what height the user wants to paste (the y of their feet).
- Whether anything around the site matters (a paste replaces blocks;
  `/pastefile <name> dontplaceair` keeps existing terrain where the build has air).

## 2. Check the height

```
python -m building fit --project <project> --origin-y <feet y>
```

- `fits: true`: no world changes needed.
- Otherwise either paste from `max_origin_y` or lower, or raise the top:
  `python -m building height-pack --out <folder> --top <top_needed or more>`.
  The pack goes in `<world>/datapacks/` and needs a server restart. It changes only the
  Overworld's top; existing chunks keep their blocks and gain empty sections above.
- Look for mods that change world height or generation (Tectonic with `increased_height`,
  Lithostitched and similar). Tectonic only applies its own height when its config is not
  vanilla; otherwise the datapack wins. Rehearse to be sure.

## 3. Rehearse on a copy

Never rehearse on the live world. Unpack the user's world download into a temporary,
isolated game directory (the review instance's `runClientGameTest` folder or a new Prism
instance), with the same height-relevant mods, BuildPaste 2.3.1+ and the datapack:

1. Open the world and confirm the datapack is active (`/datapack list`) and that the
   game accepts blocks at the new top (`/setblock ~ <top> ~ stone`). Bedrock and the bottom
   of the world must be unchanged.
2. Copy `out/build.json` to `<game dir>/buildpaste/builds/<name>.json`, stand at the
   intended spot facing north and `/pastefile <name>`.
3. Check the block count in chat and the top (spire, antenna) with `/execute if block`.
   Photograph if the result needs judging. `/undopaste` should restore the site.
4. Delete the rehearsal copy and any temporary jars afterwards.

## 4. Hand over

Prepare a folder that mirrors the server's layout, so the user copies it over as is:

```
<bundle>/
  mods/buildpaste-neoforge-<version>.jar         (only if the server's jar is too old)
  buildpaste/builds/<name>.json                  (server root, not the world folder)
  world/datapacks/<pack>/...                     (only if the height had to be raised)
```

Tell the user, in order: back up the world; stop the server; remove the old BuildPaste jar;
copy the bundle; start the server; check `/datapack list`; stand on solid ground at the
chosen spot facing north (flying or water changes the feet y, so re-run `fit` if unsure);
`/pastefile <name>`; `/undopaste` if it looks wrong. List only the files that change, so the
user never has to upload the whole world.
