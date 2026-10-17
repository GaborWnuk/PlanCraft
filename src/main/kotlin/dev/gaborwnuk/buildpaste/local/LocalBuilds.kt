package dev.gaborwnuk.buildpaste.local

import java.nio.file.Files
import java.nio.file.Path
import java.nio.file.StandardCopyOption

/**
 * Builds kept as files on the server, in the same JSON form buildpaste.net uses.
 *
 * They let an operator paste a build that was generated offline, and export a region
 * for inspection, without anything leaving the machine. Files live in one folder and
 * are addressed by a plain name, so a command can never reach outside it.
 */
class LocalBuilds(serverDirectory: Path) {

	val directory: Path = serverDirectory.resolve(FOLDER).resolve("builds").toAbsolutePath().normalize()

	/** The file a build name refers to, or null if the name is not a plain file name. */
	fun fileFor(name: String): Path? {
		if (!isValidName(name)) return null
		val file = directory.resolve("$name$EXTENSION").normalize()
		return if (file.parent == directory) file else null
	}

	fun read(name: String): String? {
		val file = fileFor(name) ?: return null
		return if (Files.isRegularFile(file)) Files.readString(file) else null
	}

	fun write(name: String, json: String): Path {
		val file = fileFor(name) ?: throw IllegalArgumentException("invalid build name: $name")
		Files.createDirectories(directory)
		val temporary = file.resolveSibling("${file.fileName}.tmp")
		Files.writeString(temporary, json)
		Files.move(temporary, file, StandardCopyOption.REPLACE_EXISTING)
		return file
	}

	fun list(): List<String> {
		if (!Files.isDirectory(directory)) return emptyList()
		return Files.list(directory).use { files ->
			files.map { it.fileName.toString() }
				.filter { it.endsWith(EXTENSION) }
				.map { it.removeSuffix(EXTENSION) }
				.filter(::isValidName)
				.sorted()
				.toList()
		}
	}

	companion object {
		const val FOLDER = "buildpaste"
		const val EXTENSION = ".json"

		private val NAME = Regex("[A-Za-z0-9_-][A-Za-z0-9_.-]{0,63}")

		fun isValidName(name: String): Boolean = NAME.matches(name) && ".." !in name
	}
}
