package dev.gaborwnuk.buildpaste.command

import com.mojang.brigadier.CommandDispatcher
import com.mojang.brigadier.arguments.StringArgumentType
import com.mojang.brigadier.builder.LiteralArgumentBuilder
import com.mojang.brigadier.context.CommandContext
import dev.gaborwnuk.buildpaste.BuildPasteLog
import dev.gaborwnuk.buildpaste.BuildPasteService
import dev.gaborwnuk.buildpaste.chat.Messages
import dev.gaborwnuk.buildpaste.paste.PasteMode
import dev.gaborwnuk.buildpaste.session.BuildPastePermission
import dev.gaborwnuk.buildpaste.session.Permissions
import net.minecraft.commands.CommandSourceStack
import net.minecraft.commands.Commands
import net.minecraft.commands.arguments.EntityArgument
import net.minecraft.server.level.ServerPlayer

/**
 * The command tree.
 *
 * The Bukkit plugin declared its commands in `plugin.yml` and parsed raw string arrays;
 * here each one is a Brigadier node, which the game validates and completes for the
 * player as they type.
 *
 * Permission is checked inside each command rather than in `requires`, so that a player
 * without it is told why, instead of the command silently not existing for them.
 */
object BuildPasteCommands {

	fun register(dispatcher: CommandDispatcher<CommandSourceStack>) {
		dispatcher.register(
			literal("pos1").executes { context ->
				withPlayer(context) { player -> BuildPasteService.setPosition(player, player.blockPosition(), first = true) }
			}
		)
		dispatcher.register(
			literal("pos2").executes { context ->
				withPlayer(context) { player -> BuildPasteService.setPosition(player, player.blockPosition(), first = false) }
			}
		)
		dispatcher.register(
			literal("removepos").executes { context ->
				withPlayer(context) { player -> BuildPasteService.removePositions(player) }
			}
		)
		dispatcher.register(
			literal("selector").executes { context ->
				withPermission(context, BuildPastePermission.UPLOAD) { player -> BuildPasteService.giveSelector(player) }
			}
		)

		dispatcher.register(
			literal("upload")
				.executes { context ->
					withPermission(context, BuildPastePermission.UPLOAD) { player ->
						BuildPasteService.upload(player, "")
					}
				}
				.then(
					Commands.argument("name", StringArgumentType.greedyString()).executes { context ->
						withPermission(context, BuildPastePermission.UPLOAD) { player ->
							BuildPasteService.upload(player, StringArgumentType.getString(context, "name"))
						}
					}
				)
		)

		dispatcher.register(
			literal("paste")
				.executes { context -> paste(context, buildId = null, modifier = null) }
				.then(
					literal(PasteMode.DONT_PLACE_AIR).executes { context ->
						paste(context, buildId = null, modifier = PasteMode.DONT_PLACE_AIR)
					}
				)
				.then(
					Commands.argument("build", StringArgumentType.word())
						.executes { context ->
							paste(context, StringArgumentType.getString(context, "build"), modifier = null)
						}
						.then(
							literal(PasteMode.DONT_PLACE_AIR).executes { context ->
								paste(
									context,
									StringArgumentType.getString(context, "build"),
									PasteMode.DONT_PLACE_AIR,
								)
							}
						)
				)
		)

		dispatcher.register(
			literal("undopaste").executes { context ->
				withPermission(context, BuildPastePermission.PASTE) { player -> BuildPasteService.undo(player) }
			}
		)

		// Local build files are read from and written to the server's disk, so only
		// operators may touch them, whatever has been granted to everyone else.
		dispatcher.register(
			literal("pastefile")
				.executes { context -> withOperator(context) { player -> BuildPasteService.listFiles(player) } }
				.then(
					Commands.argument("name", StringArgumentType.word())
						.executes { context ->
							withOperator(context) { player ->
								BuildPasteService.pasteFile(player, StringArgumentType.getString(context, "name"), null)
							}
						}
						.then(
							literal(PasteMode.DONT_PLACE_AIR).executes { context ->
								withOperator(context) { player ->
									BuildPasteService.pasteFile(
										player,
										StringArgumentType.getString(context, "name"),
										PasteMode.DONT_PLACE_AIR,
									)
								}
							}
						)
				)
		)

		dispatcher.register(
			literal("exportfile").then(
				Commands.argument("name", StringArgumentType.word()).executes { context ->
					withOperator(context) { player ->
						BuildPasteService.exportFile(player, StringArgumentType.getString(context, "name"))
					}
				}
			)
		)

		dispatcher.register(
			literal("construct")
				.executes { context ->
					withPermission(context, BuildPastePermission.CONSTRUCT) { player ->
						BuildPasteService.planConstruct(player, null)
					}
				}
				.then(
					literal("confirm").executes { context ->
						withPermission(context, BuildPastePermission.CONSTRUCT) { player ->
							BuildPasteService.confirmConstruct(player)
						}
					}
				)
				.then(
					Commands.argument("build", StringArgumentType.word()).executes { context ->
						withPermission(context, BuildPastePermission.CONSTRUCT) { player ->
							BuildPasteService.planConstruct(player, StringArgumentType.getString(context, "build"))
						}
					}
				)
		)

		dispatcher.register(
			literal("setbuild").then(
				Commands.argument("build", StringArgumentType.word()).executes { context ->
					withPlayer(context) { player ->
						BuildPasteService.setSelectedBuild(player, StringArgumentType.getString(context, "build"))
					}
				}
			)
		)

		dispatcher.register(
			literal("sharebuild")
				.executes { context ->
					withPermission(context, BuildPastePermission.UPLOAD) { player ->
						BuildPasteService.shareBuild(player, null)
					}
				}
				.then(
					Commands.argument("build", StringArgumentType.word()).executes { context ->
						withPermission(context, BuildPastePermission.UPLOAD) { player ->
							BuildPasteService.shareBuild(player, StringArgumentType.getString(context, "build"))
						}
					}
				)
		)

		dispatcher.register(
			literal("connectaccounts")
				.executes { context -> withPlayer(context) { player -> BuildPasteService.connectAccounts(player, null) } }
				.then(
					Commands.argument("email", StringArgumentType.word()).executes { context ->
						withPlayer(context) { player ->
							BuildPasteService.connectAccounts(player, StringArgumentType.getString(context, "email"))
						}
					}
				)
		)

		// The plugin shipped this command's class but never registered it, so paste paper
		// could be used but never obtained. It is wired up here.
		dispatcher.register(
			literal("pastepaper")
				.executes { context ->
					withPermission(context, BuildPastePermission.PASTE) { player ->
						BuildPasteService.givePastePaper(player, "")
					}
				}
				.then(
					Commands.argument("name", StringArgumentType.greedyString()).executes { context ->
						withPermission(context, BuildPastePermission.PASTE) { player ->
							BuildPasteService.givePastePaper(player, StringArgumentType.getString(context, "name"))
						}
					}
				)
		)

		dispatcher.register(buildpasteCommand())
	}

	/** `/buildpaste`, which shows the about text and carries the operator-only settings. */
	private fun buildpasteCommand(): LiteralArgumentBuilder<CommandSourceStack> {
		val root = literal("buildpaste").executes { context ->
			context.source.sendSystemMessage(Messages.about())
			1
		}

		root.then(
			literal("allowall").executes { context ->
				requireOperator(context) {
					Permissions.everyoneAllowed = true
					context.source.sendSystemMessage(Messages.plain("Allowed pasting for everyone"))
				}
			}
		)
		root.then(
			literal("disallowall").executes { context ->
				requireOperator(context) {
					Permissions.everyoneAllowed = false
					context.source.sendSystemMessage(Messages.plain("Disallowed pasting for everyone"))
				}
			}
		)
		root.then(
			literal("debug").then(
				Commands.argument("enabled", com.mojang.brigadier.arguments.BoolArgumentType.bool())
					.executes { context ->
						requireOperator(context) {
							BuildPasteLog.verbose =
								com.mojang.brigadier.arguments.BoolArgumentType.getBool(context, "enabled")
							context.source.sendSystemMessage(
								Messages.plain("BuildPaste debug logging ${if (BuildPasteLog.verbose) "on" else "off"}")
							)
						}
					}
			)
		)

		for (permission in BuildPastePermission.entries) {
			root.then(permissionNode(permission.argumentName) { uuid, allow ->
				if (allow) Permissions.grant(uuid, permission) else Permissions.revoke(uuid, permission)
			})
		}
		root.then(permissionNode(BuildPastePermission.ALL) { uuid, allow ->
			if (allow) Permissions.grantAll(uuid) else Permissions.revokeAll(uuid)
		})

		return root
	}

	private fun permissionNode(
		name: String,
		apply: (java.util.UUID, Boolean) -> Unit,
	): LiteralArgumentBuilder<CommandSourceStack> =
		literal(name).then(
			Commands.argument("player", EntityArgument.player())
				.then(
					literal("allow").executes { context ->
						requireOperator(context) {
							val target = EntityArgument.getPlayer(context, "player")
							apply(target.uuid, true)
							context.source.sendSystemMessage(
								Messages.plain("Gave ${target.gameProfile.name} the $name permission")
							)
						}
					}
				)
				.then(
					literal("disallow").executes { context ->
						requireOperator(context) {
							val target = EntityArgument.getPlayer(context, "player")
							apply(target.uuid, false)
							context.source.sendSystemMessage(
								Messages.plain("Took the $name permission from ${target.gameProfile.name}")
							)
						}
					}
				)
		)

	private fun paste(context: CommandContext<CommandSourceStack>, buildId: String?, modifier: String?): Int =
		withPermission(context, BuildPastePermission.PASTE) { player ->
			BuildPasteService.paste(player, buildId, modifier)
		}

	private fun literal(name: String): LiteralArgumentBuilder<CommandSourceStack> = Commands.literal(name)

	private inline fun withPlayer(context: CommandContext<CommandSourceStack>, action: (ServerPlayer) -> Unit): Int {
		val player = context.source.player
		if (player == null) {
			context.source.sendSystemMessage(Messages.error("This command can only be used by a player."))
			return 0
		}
		action(player)
		return 1
	}

	private inline fun withPermission(
		context: CommandContext<CommandSourceStack>,
		permission: BuildPastePermission,
		action: (ServerPlayer) -> Unit,
	): Int = withPlayer(context) { player ->
		if (!Permissions.has(player, permission)) {
			player.sendSystemMessage(
				Messages.error(
					"You are not allowed to use this command. Ask an operator to op you, to grant it with " +
						"'/buildpaste ${permission.argumentName} ${player.gameProfile.name} allow', " +
						"or to run /buildpaste allowall"
				)
			)
			return@withPlayer
		}
		action(player)
	}

	private inline fun withOperator(context: CommandContext<CommandSourceStack>, action: (ServerPlayer) -> Unit): Int =
		withPlayer(context) { player ->
			if (!Permissions.isOperator(player)) {
				player.sendSystemMessage(Messages.error("Only operators can use local build files."))
				return@withPlayer
			}
			action(player)
		}

	private inline fun requireOperator(context: CommandContext<CommandSourceStack>, action: () -> Unit): Int {
		val player = context.source.player
		if (player != null && !Permissions.isOperator(player)) {
			context.source.sendSystemMessage(Messages.error("Only operators can do that."))
			return 0
		}
		action()
		return 1
	}
}
