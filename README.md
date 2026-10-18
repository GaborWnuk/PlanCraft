<img src="icon.png" alt="" width="96" align="right">

# BuildPaste (Fabric, NeoForge, Server)

Real buildings in Minecraft at 1:1 scale, one block to a metre, pasted in one go.

The repository has two parts:

- **[A real-building toolchain](tools/building/README.md)**, in Python. It describes a
  building as data (plans in centimetres, materials, rooms), compiles it deterministically
  into a build file, pastes that into a fresh, real game world, reads it back cell by
  cell and photographs it. Nothing is placed by hand, so the same inputs always produce the
  same blocks.
- **The BuildPaste mod**, a server-side mod for **Fabric** and **NeoForge** that pastes
  build files and [buildpaste.net](https://buildpaste.net) builds into a world, uploads
  selections, and undoes pastes. The toolchain uses it for every paste; you can also use it
  on its own.

## Real buildings

```
research -> building.yaml -> compile -> build.json -> review in the game -> approve -> /pastefile or upload
```

The toolchain's [README](tools/building/README.md) covers the model format, the rules for
fitting real dimensions to whole blocks, reading PDF plans, the in-game review, walkthrough
worlds, height checks and lossless uploads of big builds. Two step-by-step workflows sit
on top of it:

- [real-building](.github/skills/real-building/SKILL.md): from a building's name (or private
  plans) to an approved build: research, model, compile, review, publish.
- [deploy-build-to-server](.github/skills/deploy-build-to-server/SKILL.md): pasting an
  approved build into an existing server world, including raising the world height for
  tall buildings and rehearsing on a copy first.

Varso Tower in Warsaw, for example, is 94 × 311 × 68 blocks: 53 storeys, the glazed
facade, cores, stairs and the 310 m spire. It pastes as about two million blocks from a
local file, or as two lossless sections from buildpaste.net.

| Varso Tower, Warsaw | Built with this tool |
| :---: | :---: |
| <img src="docs/images/varso-tower-real.jpg" alt="Real Varso Tower in Warsaw, photographed in May 2022" width="360"> | <img src="docs/images/varso-tower-minecraft.png" alt="The complete Varso Tower recreation, including its spire, pasted into a real Minecraft review world" width="360"> |

Real photo: [Anty000, Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Varso_Tower_Warsaw_22(cropped).jpg),
[CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) (Commons' cropped version,
resized thumbnail; no further edits). Minecraft screenshot: actual in-game review, cropped
to remove excess sky; the complete building is preserved. The views show different sides.

Plans of private homes stay private: projects live in `buildings/`, which git ignores.

## Mod commands

Select a region, look at the front of your build, and upload it:

```
/pos1                    set the first corner (or left-click with the selector)
/pos2                    set the second corner (or right-click with the selector)
/selector                get the position selector stick
/removepos               clear both corners
/upload [name]           upload the selected region
```

Paste builds back in, oriented to the way you are facing:

```
/paste                          paste the build selected on buildpaste.net
/paste <build-id>               paste a particular build
/paste <build-id> dontplaceair  drop the build into the scene, keeping what is already there
/undopaste                      put back whatever the last paste overwrote
```

Build from your own inventory instead of pasting outright:

```
/construct [build-id]    list the materials the build needs and what you are missing
/construct confirm       build as much of it as your inventory pays for
```

Share and select builds:

```
/setbuild <build-id>     make a build your selected one
/sharebuild [build-id]   post a clickable paste link to everyone on the server
/pastepaper [name]       get a piece of paper that pastes your selected build on right-click
/connectaccounts [email] link your Minecraft account to your buildpaste.net account
```

Operator settings:

```
/buildpaste                                          what this is, with example links
/buildpaste allowall | disallowall                   let everyone use it, or not
/buildpaste pastePermission <player> allow|disallow  grant one player one permission
/buildpaste uploadPermission <player> allow|disallow
/buildpaste constructPermission <player> allow|disallow
/buildpaste allPermissions <player> allow|disallow
/buildpaste debug true|false                         trace pastes in the server log
```

Operators may do everything by default. Anyone else needs a grant, and grants last until
the server restarts.

Local build files, for operators only, from mod 2.3.1. They live in `buildpaste/builds/`
in the server (or game) folder, not in the world, and use the same JSON as buildpaste.net,
so nothing leaves the machine:

```
/pastefile <name>                paste buildpaste/builds/<name>.json, facing your way
/pastefile <name> dontplaceair   the same, keeping what is already there
/exportfile <name>               write the selected region to buildpaste/builds/<name>.json
```

`/undopaste` works for file pastes too. A paste starts at your feet, so check that a tall
build fits under the world's top first (`python -m building fit`, see
[tools/building](tools/building/README.md)).

## Installing

Get the jar for your loader from the
[releases page](https://github.com/GaborWnuk/buildpaste/releases) —
`buildpaste-fabric-*.jar` or `buildpaste-neoforge-*.jar` — and drop it in your `mods`
folder along with the dependencies below.

The mod is not on Modrinth or CurseForge. It will only go there with the permission of
BuildPaste's author, MistrX.

### Dependencies

| Loader   | Required alongside BuildPaste                                                                                                              |
| -------- | ------------------------------------------------------------------------------------------------------------------------------------------ |
| Fabric   | [Fabric API](https://modrinth.com/mod/fabric-api) and [Fabric Language Kotlin](https://modrinth.com/mod/fabric-language-kotlin) (1.13.12+)   |
| NeoForge | [Kotlin for Forge](https://github.com/thedarkcolour/KotlinForForge) 6.3.0 or newer                                                            |

Both loaders also need **Java 25**, which is what Minecraft 26.1 itself requires.

The mod declares these in its metadata, so a loader will tell you what is missing rather
than crashing. Nothing else is bundled — there are no shaded libraries, and JSON handling
uses the Gson the game already ships.

### Where to install it

The mod is **server-side**, which is the third word in its name. It registers no blocks,
items, entities or network channels, so:

- On a **server**, it is the only place it needs to be installed. Players can join with an
  unmodded client and still use every command — the commands and the chat buttons come
  from the server, and the selector and paste paper are an ordinary stick and an ordinary
  piece of paper with a name on them.
- On a **client**, install it to use the commands in your own singleplayer worlds.

A Fabric server and a NeoForge server each need their own loader's jar, but both speak the
same buildpaste.net protocol, so builds move freely between them.

## Supported versions

| Minecraft      | Loaders          | Jar                                    |
| -------------- | ---------------- | -------------------------------------- |
| 26.2           | Fabric, NeoForge | `buildpaste-{loader}-<version>+26.2.jar`   |
| 26.1.2         | Fabric, NeoForge | `buildpaste-{loader}-<version>+26.1.2.jar` |
| 1.16 – 1.21.10 | Bukkit           | [the original plugin](https://legacy.curseforge.com/minecraft/bukkit-plugins/buildpaste) |

Each release ships four jars, one per Minecraft version and loader. **Take the one whose
version matches your game**: a jar declares a narrow range (`~26.2`, `[26.2,26.3)`), so a
loader refuses to load the wrong one rather than crashing.

Support for a newer Minecraft release is one `match(...)` line in
[settings.gradle.kts](settings.gradle.kts) plus a version block in
[stonecutter.properties.toml](stonecutter.properties.toml). 26.2 needed no source changes
at all — the mod uses only APIs that were stable across the drop.

## Origins and changes from the plugin

The mod started as a fork of
[BuildPaste](https://legacy.curseforge.com/minecraft/bukkit-plugins/buildpaste), a Bukkit
server plugin by **MistrX**. The plugin could not run on NeoForge or Fabric, so it was
rewritten against the mod loaders' APIs. Its commands, chat and buildpaste.net protocol are
unchanged: builds uploaded by the original plugin paste correctly here, and builds uploaded
here work anywhere else BuildPaste runs. The name says what the fork added: **Fabric**,
**NeoForge**, and **Server**, so players need nothing installed.

It is dedicated to my son, who would rather spend an afternoon building a castle than
fighting anything that lives in one :)

Defects fixed from the original along the way:

- **Requests no longer block the server.** Every backend call the plugin made ran
  synchronously inside the command handler, freezing the server for the length of the
  round trip. Calls are asynchronous here and resume on the server thread.
- **Uploading unusual blocks works.** The plugin called `equals` on a null block id, so
  uploading any block outside its 1140-name table threw and lost the whole upload.
  Untabled blocks now travel as their name.
- **Chests and signs keep their contents.** The protocol has always had a field for
  block-entity data, but the plugin sent it empty and ignored it on the way back, so
  every build it uploaded pasted hollow. It is captured and restored now. Data saved
  before Minecraft 1.21 is in a layout this version cannot read; those blocks are placed
  empty and reported rather than half-restored.
- **Undo restores what was there.** Undo re-applied the paste rotation to the blocks it
  had captured, so restored stairs and logs came back facing the wrong way.
- **Pasting over a build corrects it.** Placement compared only the block type, so a
  stair already in the right spot but facing the wrong way was left alone.
- **Blocks the game renamed still paste.** Five names in the shared table — `grass`,
  `grass_path`, `sign`, `wall_sign` and `chain` — no longer exist, and older builds came
  out with holes where they were.
- **Debug output goes to the log**, rather than being broadcast to every player on the
  server as chat.

## Building from source

Requirements: Java 25, which Gradle provisions automatically thanks to the Foojay
toolchain resolver.

```sh
./gradlew build
```

This builds every Minecraft version and loader; the jars land in
`versions/<version>-<loader>/build/libs/`.

The two targets share one source tree. Loader-specific code lives behind Stonecutter
comments (`//? if fabric {`), and only the two entry points need them — everything else is
plain Minecraft API. To work on one loader in an IDE, switch the active target:

```sh
./gradlew "Set active project to 26.2-fabric"
./gradlew "Set active project to 26.1.2-neoforge"
```

Run `./gradlew "Reset active project"` before committing, so the tree goes back to a
consistent state.

Switching the active target rewrites the shared sources in place, which Gradle's
up-to-date checks do not notice — so **run `./gradlew clean build` after a switch**, or
the previous target's classes linger and you get a jar missing its entry point. A fresh
checkout, which is what CI builds, is never affected.

To run a development client or server:

```sh
./gradlew :26.2-fabric:runClient
./gradlew :26.2-neoforge:runServer
```

Kill any leftover server JVM before starting another one — they share the `run` folder,
and a second server dies on the world lock or the port.

The Fabric client gametest pastes a build into a fresh world, reads it back and takes
screenshots. `tools/building` drives it (`python -m building review`); see its README.
The toolchain's tests run with `python -m pytest -q` in `tools/building`.

## Credits and licences

The original BuildPaste plugin and the buildpaste.net service are by **MistrX** — thank
you. This fork is not affiliated with or endorsed by them.

The code, both the mod and the toolchain, is licensed under the [MIT licence](LICENSE).

The icon is **not** covered by that licence. It is
["Minecraft Windows 11 Folder ICO PNG" by SimplexDesignss](https://www.deviantart.com/simplexdesignss/art/Minecraft-Windows-11-Folder-ICO-PNG-950630441),
used under the Creative Commons
[Attribution-NonCommercial-NoDerivatives 3.0](https://creativecommons.org/licenses/by-nc-nd/3.0/)
licence. It is redistributed unchanged, as that licence requires: it must not be resized,
recoloured or otherwise altered, and it must not be put to commercial use. The same notice
travels inside the jar, at `assets/buildpaste/ICON-LICENSE.txt`.
