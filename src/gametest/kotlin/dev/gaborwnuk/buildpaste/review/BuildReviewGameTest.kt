package dev.gaborwnuk.buildpaste.review

import com.google.gson.JsonArray
import com.google.gson.JsonObject
import com.google.gson.JsonParser
import dev.gaborwnuk.buildpaste.BuildPasteService
import dev.gaborwnuk.buildpaste.local.LocalBuilds
import dev.gaborwnuk.buildpaste.session.Sessions
import net.fabricmc.fabric.api.client.gametest.v1.FabricClientGameTest
import net.fabricmc.fabric.api.client.gametest.v1.context.ClientGameTestContext
import net.fabricmc.fabric.api.client.gametest.v1.context.TestSingleplayerContext
import net.fabricmc.fabric.api.client.gametest.v1.screenshot.TestScreenshotOptions
import net.minecraft.client.Minecraft
import net.minecraft.core.BlockPos
import net.minecraft.server.MinecraftServer
import net.minecraft.world.level.chunk.status.ChunkStatus
import net.minecraft.world.level.levelgen.Heightmap
import org.slf4j.LoggerFactory
import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption

/**
 * Pastes one local build into a brand-new world, reads it back and photographs it.
 *
 * Everything it needs comes from a spec file written by `tools/building` (its path is
 * passed in the `buildpaste.review.spec` system property), and everything it produces
 * goes to the spec's output folder. Each run starts from a fresh world, so there is
 * nothing to reset between runs. Without a spec the test does nothing and passes.
 *
 * The build is pasted with the player facing north, the direction the tools write
 * builds in, so build cell `(x, y, z)` lands at world `(ox + 1 + x, oy + y, oz - sizeZ + 1 + z)`
 * with no block rotated, and the read-back has exactly the source file's block order.
 * Camera positions in the spec are in those build cell coordinates.
 */
class BuildReviewGameTest : FabricClientGameTest {

	private val log = LoggerFactory.getLogger("buildpaste-review")

	private class Placement(val origin: BlockPos, val sizeX: Int, val sizeY: Int, val sizeZ: Int) {
		val min = BlockPos(origin.x + 1, origin.y, origin.z - sizeZ + 1)
		val max = BlockPos(origin.x + sizeX, origin.y + sizeY - 1, origin.z)

		fun world(local: List<Double>) = Triple(min.x + local[0], min.y + local[1], min.z + local[2])
	}

	override fun runTest(context: ClientGameTestContext) {
		val specFile = System.getProperty("buildpaste.review.spec")?.let(Path::of)
		if (specFile == null || !Files.isRegularFile(specFile)) {
			log.info("No review spec at {}; nothing to do", specFile)
			return
		}
		val spec = JsonParser.parseString(Files.readString(specFile)).asJsonObject
		val out = Path.of(spec.get("out").asString)
		Files.createDirectories(out)

		val build = JsonParser.parseString(Files.readString(Path.of(spec.get("build").asString))).asJsonObject
		val size = build.getAsJsonArray("size").map { it.asInt }

		context.runOnClient<RuntimeException> { minecraft ->
			minecraft.options.hideGui = true
			minecraft.options.renderDistance().set(spec.get("renderDistance")?.asInt ?: 10)
		}

		context.worldBuilder().create().use { world ->
			val server = world.server
			waitForView(context, "world start")

			server.runCommand("gamemode spectator @a")
			server.runCommand("time set ${spec.get("time")?.asInt ?: 6000}")
			server.runCommand("weather clear")
			server.runCommand("effect give @a minecraft:night_vision infinite 0 true")

			val placement = placement(world, spec, size)
			server.runCommand(
				"forceload add ${placement.min.x - 16} ${placement.min.z - 16} ${placement.max.x + 16} ${placement.max.z + 16}"
			)

			val pasteMillis = paste(context, world, build, placement)
			readBack(world, placement, out)
			val shots = screenshots(context, world, spec, placement, out)

			val report = JsonObject().apply {
				add("origin", JsonArray().apply { listOf(placement.origin.x, placement.origin.y, placement.origin.z).forEach(::add) })
				add("min", JsonArray().apply { listOf(placement.min.x, placement.min.y, placement.min.z).forEach(::add) })
				addProperty("pasteMillis", pasteMillis)
				add("shots", shots)
			}
			Files.writeString(out.resolve("report.json"), report.toString())
		}
	}

	/** Puts the build's ground layer on the surface of the test world, wherever that is. */
	private fun placement(world: TestSingleplayerContext, spec: JsonObject, size: List<Int>): Placement {
		val anchor = spec.getAsJsonArray("anchor")?.map { it.asInt } ?: listOf(0, 0)
		val groundLayer = spec.get("groundLayer")?.asInt ?: 0
		val surface = world.server.computeOnServer<Int, RuntimeException> { server ->
			server.overworld().getHeight(Heightmap.Types.MOTION_BLOCKING, anchor[0], anchor[1])
		}
		return Placement(BlockPos(anchor[0], surface - groundLayer, anchor[1]), size[0], size[1], size[2])
	}

	private fun paste(context: ClientGameTestContext, world: TestSingleplayerContext, build: JsonObject, placement: Placement): Long {
		world.server.runOnServer<RuntimeException> { server ->
			LocalBuilds(server.serverDirectory).write(BUILD_NAME, build.toString())

			val player = onlyPlayer(server)
			player.teleportTo(placement.origin.x + 0.5, placement.origin.y.toDouble(), placement.origin.z + 0.5)
			player.setYRot(NORTH_YAW)
			BuildPasteService.pasteFile(player, BUILD_NAME, null)
		}

		val started = System.nanoTime()
		while (world.server.computeOnServer<Boolean, RuntimeException> { server -> Sessions[onlyPlayer(server)].pasteInProgress }) {
			context.waitTicks(5)
		}
		val millis = (System.nanoTime() - started) / 1_000_000
		log.info("Paste finished in {} ms", millis)
		context.waitTicks(5)
		return millis
	}

	private fun readBack(world: TestSingleplayerContext, placement: Placement, out: Path) {
		world.server.runOnServer<RuntimeException> { server ->
			val player = onlyPlayer(server)
			player.setYRot(NORTH_YAW)
			BuildPasteService.setPosition(player, placement.min, first = true)
			BuildPasteService.setPosition(player, placement.max, first = false)
			BuildPasteService.exportFile(player, READBACK_NAME)

			val exported = LocalBuilds(server.serverDirectory).fileFor(READBACK_NAME)!!
			Files.copy(exported, out.resolve("readback.json"), StandardCopyOption.REPLACE_EXISTING)
		}
	}

	private fun screenshots(
		context: ClientGameTestContext,
		world: TestSingleplayerContext,
		spec: JsonObject,
		placement: Placement,
		out: Path,
	): JsonArray {
		val taken = JsonArray()
		val shots = spec.getAsJsonArray("shots") ?: return taken
		val width = spec.get("width")?.asInt ?: 1920
		val height = spec.get("height")?.asInt ?: 1080

		for (element in shots) {
			val shot = element.asJsonObject
			val name = shot.get("name").asString
			val (x, y, z) = placement.world(shot.getAsJsonArray("pos").map { it.asDouble })
			val yaw = shot.get("yaw").asFloat
			val pitch = shot.get("pitch").asFloat

			world.server.runCommand("tp @a $x $y $z $yaw $pitch")
			context.waitTicks(3)
			waitForView(context, name)
			context.waitTicks(shot.get("settleTicks")?.asInt ?: 10)

			val file = context.takeScreenshot(
				TestScreenshotOptions.of(name)
					.disableCounterPrefix()
					.withSize(width, height)
					.withDestinationDir(out.resolve("shots"))
			)
			taken.add(file.toString())
			log.info("Shot {}", name)
		}
		return taken
	}

	/**
	 * Waits until the chunks around the camera are loaded and every visible section is drawn.
	 *
	 * Fabric's own `waitForChunksRender` demands every chunk in render distance and fails the
	 * whole run when that never settles, so this checks a smaller radius and only warns on timeout.
	 */
	private fun waitForView(context: ClientGameTestContext, label: String) {
		val started = System.nanoTime()
		try {
			context.waitFor({ minecraft -> viewReady(minecraft) }, RENDER_TIMEOUT_TICKS)
			log.info("View ready for {} after {} ms", label, (System.nanoTime() - started) / 1_000_000)
		} catch (timeout: AssertionError) {
			log.warn("View for {} still incomplete after {} ms; taking it anyway", label, (System.nanoTime() - started) / 1_000_000)
		}
	}

	private fun viewReady(minecraft: Minecraft): Boolean {
		val level = minecraft.level ?: return false
		val camera = minecraft.player?.chunkPosition() ?: return false
		for (dx in -VIEW_RADIUS_CHUNKS..VIEW_RADIUS_CHUNKS) {
			for (dz in -VIEW_RADIUS_CHUNKS..VIEW_RADIUS_CHUNKS) {
				if (level.getChunk(camera.x + dx, camera.z + dz, ChunkStatus.FULL, false) == null) return false
			}
		}
		return minecraft.levelRenderer.hasRenderedAllSections()
	}

	private fun onlyPlayer(server: MinecraftServer) = server.playerList.players.single()

	companion object {
		const val BUILD_NAME = "review"
		const val READBACK_NAME = "review-readback"

		/** Minecraft yaw for facing north: 0 is south and angles turn clockwise from above. */
		const val NORTH_YAW = 180f

		const val RENDER_TIMEOUT_TICKS = 20 * 60
		const val VIEW_RADIUS_CHUNKS = 4
	}
}
