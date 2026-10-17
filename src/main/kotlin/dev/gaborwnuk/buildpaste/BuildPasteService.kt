package dev.gaborwnuk.buildpaste

import dev.gaborwnuk.buildpaste.backend.BuildPasteApi
import dev.gaborwnuk.buildpaste.chat.Messages
import dev.gaborwnuk.buildpaste.item.BuildPasteItems
import dev.gaborwnuk.buildpaste.local.LocalBuilds
import dev.gaborwnuk.buildpaste.paste.InventoryBilling
import dev.gaborwnuk.buildpaste.paste.PasteJob
import dev.gaborwnuk.buildpaste.paste.PasteMode
import dev.gaborwnuk.buildpaste.paste.PasteScheduler
import dev.gaborwnuk.buildpaste.protocol.ApiResult
import dev.gaborwnuk.buildpaste.protocol.BlockTable
import dev.gaborwnuk.buildpaste.protocol.BuildData
import dev.gaborwnuk.buildpaste.protocol.BuildJson
import dev.gaborwnuk.buildpaste.protocol.Rotation
import dev.gaborwnuk.buildpaste.session.PlayerSession
import dev.gaborwnuk.buildpaste.session.Sessions
import dev.gaborwnuk.buildpaste.world.BlockCodec
import net.minecraft.ChatFormatting
import net.minecraft.core.BlockPos
import net.minecraft.network.chat.Component
import net.minecraft.server.level.ServerLevel
import net.minecraft.server.level.ServerPlayer
import java.util.concurrent.CompletableFuture

/**
 * Everything the commands actually do.
 *
 * Calls to the backend are asynchronous, so an operation that needs one is written as a
 * request followed by a continuation that resumes on the server thread. Nothing here may
 * touch the world off that thread.
 */
object BuildPasteService {

	// region selection

	fun setPosition(player: ServerPlayer, pos: BlockPos, first: Boolean) {
		val session = Sessions[player]
		val level = player.level().dimension()

		// A selection spanning two worlds cannot describe a region; keep the newer corner.
		if (session.selectionLevel != null && session.selectionLevel != level) {
			session.clearSelection()
			player.sendSystemMessage(
				Component.literal("Your other position was in a different world, so it was cleared.")
					.withStyle(ChatFormatting.YELLOW)
			)
		}
		session.selectionLevel = level

		if (first) session.pos1 = pos else session.pos2 = pos
		val label = if (first) "Pos1" else "Pos2"
		player.sendSystemMessage(Messages.plain("$label has been set to (${pos.x}, ${pos.y}, ${pos.z})"))

		if (session.pos1 != null && session.pos2 != null) Messages.selectionReady(player)
	}

	fun removePositions(player: ServerPlayer) {
		Sessions[player].clearSelection()
		player.sendSystemMessage(Messages.plain("All positions were removed"))
	}

	fun giveSelector(player: ServerPlayer) {
		if (!player.inventory.add(BuildPasteItems.positionSelector())) {
			player.sendSystemMessage(Messages.error("Your inventory is full."))
		}
	}

	// region upload

	fun upload(player: ServerPlayer, buildName: String) {
		val session = Sessions[player]
		val level = player.level()
		val pos1 = session.pos1
		val pos2 = session.pos2

		when {
			pos1 == null && pos2 == null -> {
				player.sendSystemMessage(
					Messages.plain(
						"Select two positions before uploading, with /pos1 and /pos2 " +
							"or the position selector from /selector"
					)
				)
				return
			}
			pos1 == null -> { player.sendSystemMessage(Messages.plain("Pos1 isn't selected")); return }
			pos2 == null -> { player.sendSystemMessage(Messages.plain("Pos2 isn't selected")); return }
			pos1 == pos2 -> {
				player.sendSystemMessage(Messages.plain("Both positions are on the same spot. That's illegal!"))
				return
			}
			session.selectionLevel != level.dimension() -> {
				player.sendSystemMessage(Messages.error("Your selection is in a different world."))
				return
			}
		}

		val scan = scanRegion(level, player, pos1, pos2)
		if (scan == null) {
			player.sendSystemMessage(Messages.error("That selection is too large to upload."))
			return
		}

		player.sendSystemMessage(Messages.plain("Uploading ${scan.blocks.size} blocks..."))

		BuildPasteApi.uploadBuild(
			uuid = player.uuid.toString(),
			blocks = scan.blocks,
			data = scan.data,
			size = scan.size,
			lookDirection = scan.lookDirection,
			buildName = buildName.replace('/', ' '),
			nbt = scan.nbt,
		).thenAcceptAsync({ result ->
			when (result) {
				is ApiResult.Success -> {
					session.uploadedBuildId = result.value
					session.clearSelection()
					Messages.uploadSucceeded(player, result.value)
				}
				is ApiResult.NotFound -> player.sendSystemMessage(Messages.error("The backend rejected the upload."))
				is ApiResult.Failed -> {
					BuildPasteLog.warn("Upload failed for ${player.gameProfile.name}: ${result.reason}")
					player.sendSystemMessage(Messages.error("Upload failed: ${result.reason}"))
				}
			}
		}, player.gameServer)
	}

	private class RegionScan(
		val blocks: List<Any>,
		val data: List<String?>,
		val nbt: Map<Int, String>,
		val size: List<Int>,
		val lookDirection: String,
	)

	/**
	 * Reads the selected region into the backend's block list.
	 *
	 * The sweep runs x, then y, then z, with x and z each running forwards or backwards
	 * according to the direction the uploader faces. That is what makes a build's block
	 * order relative to its own front, and it is the order the paste walk replays.
	 */
	private fun scanRegion(
		level: ServerLevel,
		player: ServerPlayer,
		pos1: BlockPos,
		pos2: BlockPos,
	): RegionScan? {
		val xSmall = minOf(pos1.x, pos2.x)
		val xLarge = maxOf(pos1.x, pos2.x)
		val ySmall = minOf(pos1.y, pos2.y)
		val yLarge = maxOf(pos1.y, pos2.y)
		val zSmall = minOf(pos1.z, pos2.z)
		val zLarge = maxOf(pos1.z, pos2.z)

		val sizeX = xLarge - xSmall + 1
		val sizeY = yLarge - ySmall + 1
		val sizeZ = zLarge - zSmall + 1
		val volume = sizeX.toLong() * sizeY.toLong() * sizeZ.toLong()
		if (volume > BuildPaste.MAX_PASTE_BLOCKS) return null

		val lookDirection = Rotation.lookDirection(player.yRot)
		val xDescending = lookDirection == "north" || lookDirection == "west"
		val zDescending = lookDirection == "north" || lookDirection == "east"

		val blocks = ArrayList<Any>(volume.toInt())
		val data = ArrayList<String?>(volume.toInt())
		val nbt = HashMap<Int, String>()
		val cursor = BlockPos.MutableBlockPos()

		var index = 0
		for (xi in 0 until sizeX) {
			val x = if (xDescending) xLarge - xi else xSmall + xi
			for (yi in 0 until sizeY) {
				val y = ySmall + yi
				for (zi in 0 until sizeZ) {
					val z = if (zDescending) zLarge - zi else zSmall + zi
					cursor.set(x, y, z)

					val state = level.getBlockState(cursor)
					val serialized = BlockCodec.serialize(state)

					// Untabled blocks travel as their name. The plugin called equals() on a null
					// id here, so uploading any block outside the table threw and lost the upload.
					blocks.add(BlockTable.idOf(serialized.name) ?: serialized.name)
					data.add(serialized.properties)

					if (!state.isAir) {
						BlockCodec.captureNbt(level, cursor)?.let { nbt[index] = it }
					}
					index++
				}
			}
		}

		return RegionScan(blocks, data, nbt, listOf(sizeX, sizeY, sizeZ), lookDirection)
	}

	// region paste

	fun paste(player: ServerPlayer, buildIdArgument: String?, modifier: String?) {
		val session = Sessions[player]
		if (session.pasteInProgress) {
			player.sendSystemMessage(Messages.error("A paste is already running. Wait for it to finish."))
			return
		}

		val mode = PasteMode.fromArgument(modifier)
		val direction = Rotation.lookDirection(player.yRot)
		val origin = player.blockPosition()

		withBuild(player, session, buildIdArgument) { build ->
			startPaste(player, session, build, origin, direction, mode, constructing = false)
		}
	}

	private fun startPaste(
		player: ServerPlayer,
		session: PlayerSession,
		build: BuildData,
		origin: BlockPos,
		direction: String,
		mode: PasteMode,
		constructing: Boolean,
	) {
		val level = player.level()

		if (build.volume > BuildPaste.MAX_PASTE_BLOCKS) {
			player.sendSystemMessage(Messages.error("That build is too large to paste."))
			return
		}

		val job = PasteJob(
			level = level,
			session = session,
			origin = origin,
			sizeX = build.sizeX,
			sizeY = build.sizeY,
			sizeZ = build.sizeZ,
			blocks = build.blocks,
			data = build.data,
			nbt = build.nbt,
			rotateFrom = build.uploadDirection,
			rotateTo = direction,
			mode = mode,
			constructing = constructing,
		)

		if (job.blockCount == 0) {
			player.sendSystemMessage(Messages.error("That build could not be placed: its orientation is unknown."))
			return
		}

		session.pasteInProgress = true
		PasteScheduler.submit(job)
		player.sendSystemMessage(Messages.plain("Pasting ${job.blockCount} blocks..."))
	}

	fun undo(player: ServerPlayer) {
		val session = Sessions[player]
		val record = session.undo
		if (record == null) {
			player.sendSystemMessage(Messages.plain("You can't undo what hasn't been done"))
			return
		}
		if (session.pasteInProgress) {
			player.sendSystemMessage(Messages.error("A paste is already running. Wait for it to finish."))
			return
		}

		val level = player.gameServer.getLevel(record.levelKey)
		if (level == null) {
			player.sendSystemMessage(Messages.error("The world that paste happened in is no longer loaded."))
			return
		}

		// Both directions are the paste direction so that rotation is a no-op: the captured
		// blocks are already oriented the way the world had them. The plugin passed the
		// build's upload direction here, turning every restored stair a second time.
		val job = PasteJob(
			level = level,
			session = session,
			origin = record.origin,
			sizeX = record.sizeX,
			sizeY = record.sizeY,
			sizeZ = record.sizeZ,
			blocks = record.blocks,
			data = record.data,
			nbt = record.nbt,
			rotateFrom = record.pasteDirection,
			rotateTo = record.pasteDirection,
			mode = PasteMode.REPLACE,
			constructing = false,
		)

		session.pasteInProgress = true
		PasteScheduler.submit(job)
		player.sendSystemMessage(Messages.plain("Undoing ${job.blockCount} blocks..."))
	}

	// region local files

	/**
	 * Pastes a build from the server's local build folder, exactly as `/paste` would paste
	 * the same build fetched from buildpaste.net.
	 */
	fun pasteFile(player: ServerPlayer, name: String, modifier: String?) {
		val session = Sessions[player]
		if (session.pasteInProgress) {
			player.sendSystemMessage(Messages.error("A paste is already running. Wait for it to finish."))
			return
		}

		val builds = localBuilds(player)
		val body = builds.read(name)
		if (body == null) {
			player.sendSystemMessage(Messages.error("No local build named '$name' in ${builds.directory}"))
			return
		}

		val build = runCatching { BuildJson.parse(body) }.getOrElse { error ->
			player.sendSystemMessage(Messages.error("Local build '$name' is malformed: ${error.message}"))
			return
		}

		startPaste(
			player = player,
			session = session,
			build = build,
			origin = player.blockPosition(),
			direction = Rotation.lookDirection(player.yRot),
			mode = PasteMode.fromArgument(modifier),
			constructing = false,
		)
	}

	/** Writes the selected region to the local build folder, in the form `/upload` would send. */
	fun exportFile(player: ServerPlayer, name: String) {
		val session = Sessions[player]
		val pos1 = session.pos1
		val pos2 = session.pos2
		if (pos1 == null || pos2 == null || session.selectionLevel != player.level().dimension()) {
			player.sendSystemMessage(Messages.error("Select two positions in this world first, with /pos1 and /pos2."))
			return
		}

		val scan = scanRegion(player.level(), player, pos1, pos2)
		if (scan == null) {
			player.sendSystemMessage(Messages.error("That selection is too large to export."))
			return
		}

		val json = BuildJson.toJson(scan.blocks, scan.data, scan.size, scan.lookDirection, scan.nbt)
		val file = localBuilds(player).write(name, json.toString())
		player.sendSystemMessage(Messages.plain("Exported ${scan.blocks.size} blocks to $file"))
	}

	fun listFiles(player: ServerPlayer) {
		val builds = localBuilds(player)
		val names = builds.list()
		player.sendSystemMessage(
			Messages.plain(
				if (names.isEmpty()) "No local builds in ${builds.directory}"
				else "Local builds: ${names.joinToString(", ")}"
			)
		)
	}

	private fun localBuilds(player: ServerPlayer) = LocalBuilds(player.gameServer.serverDirectory)

	// region construct

	fun planConstruct(player: ServerPlayer, buildIdArgument: String?) {
		val session = Sessions[player]

		withBuild(player, session, buildIdArgument) { build ->
			session.availableItems.clear()
			session.availableItems.putAll(InventoryBilling.gather(player))
			session.requiredBlocks.clear()

			for (block in build.blocks) {
				session.requiredBlocks.merge(BlockItemNameFor(block), 1, Int::plus)
			}
			session.requiredBlocks.remove("minecraft:air")
			session.availableItems.remove("minecraft:air")

			player.sendSystemMessage(buildMaterialsReport(session))
		}
	}

	private fun BlockItemNameFor(block: String) =
		dev.gaborwnuk.buildpaste.paste.BlockItemMapping.itemFor(block)

	private fun buildMaterialsReport(session: PlayerSession): Component {
		val report = Component.literal("Needed materials:\n")
		var hasAll = true
		var hasAny = false

		for ((item, needed) in session.requiredBlocks.entries.sortedByDescending { it.value }) {
			val held = session.availableItems[item] ?: 0
			val label = item.removePrefix("minecraft:")
			when {
				held >= needed -> {
					hasAny = true
					report.append(Component.literal("$needed x $label\n").withStyle(ChatFormatting.GREEN))
				}
				held > 0 -> {
					hasAny = true
					hasAll = false
					report.append(Component.literal("$needed x $label ($held/$needed)\n").withStyle(ChatFormatting.WHITE))
				}
				else -> {
					hasAll = false
					report.append(Component.literal("$needed x $label (0/$needed)\n").withStyle(ChatFormatting.WHITE))
				}
			}
		}

		report.append("\n")
		report.append(
			if (hasAll) Component.literal("You have all the required materials!")
			else Component.literal("You don't have all the required materials")
		)
		report.append("\n")
		report.append(
			Messages.buttonRow(
				Messages.runButton(
					if (hasAll || !hasAny) "Construct" else "Construct anyway",
					"/construct confirm",
					"Build it from your inventory",
					ChatFormatting.LIGHT_PURPLE,
				)
			)
		)
		return report
	}

	fun confirmConstruct(player: ServerPlayer) {
		val session = Sessions[player]
		val build = session.cachedBuild
		if (build == null) {
			player.sendSystemMessage(Messages.error("Plan a build with /construct first."))
			return
		}
		if (session.pasteInProgress) {
			player.sendSystemMessage(Messages.error("A paste is already running. Wait for it to finish."))
			return
		}

		startPaste(
			player = player,
			session = session,
			build = build,
			origin = player.blockPosition(),
			direction = Rotation.lookDirection(player.yRot),
			mode = PasteMode.KEEP_EXISTING_UNDER_AIR,
			constructing = true,
		)
	}

	// region account and build selection

	fun setSelectedBuild(player: ServerPlayer, buildId: String) {
		BuildPasteApi.setSelectedBuild(player.uuid.toString(), buildId).thenAcceptAsync({ result ->
			when (result) {
				is ApiResult.Success -> player.sendSystemMessage(Messages.plain("Build copied"))
				else -> Messages.notConnected(player)
			}
		}, player.gameServer)
	}

	fun shareBuild(player: ServerPlayer, buildIdArgument: String?) {
		val session = Sessions[player]
		withBuildId(player, session, buildIdArgument) { buildId ->
			val message = Messages.shared(player.gameProfile.name, buildId)
			player.gameServer.playerList.players.forEach { it.sendSystemMessage(message) }
		}
	}

	fun connectAccounts(player: ServerPlayer, email: String?) {
		BuildPasteApi.connectAccounts(player.gameProfile.name, player.uuid.toString(), email)
			.thenAcceptAsync({ result ->
				when (result) {
					is ApiResult.Success -> player.sendSystemMessage(Messages.plain("Accounts connected successfully"))
					is ApiResult.NotFound -> player.sendSystemMessage(
						Messages.plain("Your email wasn't found in combination with your Minecraft name :(")
					)
					is ApiResult.Failed -> player.sendSystemMessage(Messages.error("Could not connect: ${result.reason}"))
				}
			}, player.gameServer)
	}

	fun givePastePaper(player: ServerPlayer, label: String) {
		val session = Sessions[player]
		withBuildId(player, session, null) { buildId ->
			if (label.isNotBlank()) {
				givePaper(player, label, buildId)
			} else {
				BuildPasteApi.fetchBuildName(buildId).thenAcceptAsync({ result ->
					givePaper(player, (result as? ApiResult.Success)?.value, buildId)
				}, player.gameServer)
			}
		}
	}

	private fun givePaper(player: ServerPlayer, name: String?, buildId: String) {
		if (!player.inventory.add(BuildPasteItems.pastePaper(name, buildId))) {
			player.sendSystemMessage(Messages.error("Your inventory is full."))
		}
	}

	// region shared plumbing

	/**
	 * Resolves the build id an operation should act on and hands it to [action] on the
	 * server thread. With no id given, the player's selected build on the website is used.
	 */
	private inline fun withBuildId(
		player: ServerPlayer,
		session: PlayerSession,
		buildIdArgument: String?,
		crossinline action: (String) -> Unit,
	) {
		if (buildIdArgument != null) {
			action(buildIdArgument)
			return
		}

		BuildPasteApi.fetchSelectedBuild(player.gameProfile.name, player.uuid.toString())
			.thenAcceptAsync({ result ->
				when (result) {
					is ApiResult.Success -> action(result.value)
					is ApiResult.NotFound -> Messages.notConnected(player)
					is ApiResult.Failed -> {
						BuildPasteLog.debug("Could not resolve selected build: {}", result.reason)
						Messages.notConnected(player)
					}
				}
			}, player.gameServer)
	}

	/** Resolves a build id, then the build behind it, reusing the session's cached copy. */
	private inline fun withBuild(
		player: ServerPlayer,
		session: PlayerSession,
		buildIdArgument: String?,
		crossinline action: (BuildData) -> Unit,
	) {
		withBuildId(player, session, buildIdArgument) { buildId ->
			val cached = session.cached(buildId)
			if (cached != null) {
				action(cached)
			} else {
				BuildPasteApi.fetchBuild(buildId).thenAcceptAsync({ result ->
					when (result) {
						is ApiResult.Success -> {
							session.cache(buildId, result.value)
							action(result.value)
						}
						is ApiResult.NotFound ->
							player.sendSystemMessage(Messages.plain("This build doesn't exist (404)"))
						is ApiResult.Failed -> {
							BuildPasteLog.warn("Could not fetch build $buildId: ${result.reason}")
							player.sendSystemMessage(Messages.error("Could not fetch that build: ${result.reason}"))
						}
					}
				}, player.gameServer)
			}
		}
	}

	@Suppress("unused")
	private fun <T> completed(value: T): CompletableFuture<T> = CompletableFuture.completedFuture(value)
}
