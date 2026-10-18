# PlanCraft buildings

These are shared examples made with the [PlanCraft toolchain](../tools/building/README.md).
You do **not** need Python, Copilot or a buildpaste.net account to paste a supplied build
file. You need Minecraft Java Edition and the matching BuildPaste mod installed on the
server, or in your client for singleplayer.

| Building | Download / project | Size |
| --- | --- | --- |
| Varso Tower, Warsaw | [Instructions and model](varso-tower/README.md) / [ready-to-paste JSON](varso-tower/out/build.json) | Stored box: 94 x 313 x 68; occupied height: 311 blocks, including the 310 m spire |

## Use in your game

1. Back up your world. Install **BuildPaste 2.3.1 or newer** for your exact Minecraft
   version and loader, with its [dependencies](../docs/buildpaste.md#dependencies). The supplied
   Varso build was reviewed in Minecraft **26.1.2**. Other supported versions need their
   matching mod jar and a check that all block states still exist. This is not a Bedrock
   Edition schematic.
2. Download the JSON using GitHub's **Raw / Download raw file** button, not Save Page on
   the GitHub preview. Keep the file name simple, for example `varso-tower.json`.
3. Copy it to:
   - **Singleplayer:** `<game directory>\buildpaste\builds\varso-tower.json`. In Prism,
     this is inside that instance's `minecraft` folder, not the launcher root.
   - **Server:** `<server root>\buildpaste\builds\varso-tower.json`, next to `mods`,
     not inside the world folder. Players do not need the mod on their own clients.
4. Enable commands in singleplayer, or obtain operator rights on the server.
   Check the building's height and placement instructions **before pasting**.
5. Stand at the intended origin on solid ground, face **north** (F3 shows your direction),
   and run:

   ```text
   /pastefile varso-tower
   ```

   With a north-facing paste, cell `(x, y, z)` lands at
   `(playerX + 1 + x, playerY + y, playerZ - sizeZ + 1 + z)`, using the player's
   block position. The build therefore extends east and north from your feet.
   Other facing directions rotate the build.

6. Wait for the paste to finish. To restore what the paste replaced, use `/undopaste`
   before another paste replaces your undo history. Undo is not a substitute for a backup.

By default, air in the build clears the site. `/pastefile varso-tower dontplaceair`
leaves existing blocks in air cells, which may leave terrain or old buildings inside rooms.
Choose deliberately and rehearse in a disposable world first.

**Height limits still apply.** Varso cannot fit at sea level in a default Overworld.
Follow its [height instructions](varso-tower/README.md#world-height) rather than accepting
a clipped spire.

## Models and privacy

The shared projects contain editable YAML, source citations and, where supplied, generators.
See each project's README for recompilation and limitations. Original research images are
not included unless separately licensed for redistribution.

Other building folders remain gitignored by default. Only the explicitly allowlisted Varso
example is published; private home plans and their derived builds must remain excluded.
