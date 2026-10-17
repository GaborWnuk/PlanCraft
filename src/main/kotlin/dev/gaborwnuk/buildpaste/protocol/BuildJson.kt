package dev.gaborwnuk.buildpaste.protocol

import com.google.gson.JsonArray
import com.google.gson.JsonNull
import com.google.gson.JsonObject
import com.google.gson.JsonParser

/**
 * The JSON form of a build, as buildpaste.net stores and serves it.
 *
 * Local build files use exactly the same form, so a build written to disk pastes the
 * same way as one fetched from the backend, and one exported from the world can be
 * uploaded unchanged.
 */
object BuildJson {

	/**
	 * Reads a build.
	 *
	 * Block ids arrive either as numbers indexing [BlockTable] or as namespaced names for
	 * blocks the table does not cover; both are resolved to names here.
	 */
	fun parse(body: String): BuildData {
		val json = JsonParser.parseString(body).asJsonObject

		val size = json.getAsJsonArray("size")
		val blocks = json.getAsJsonArray("blocks").map { BlockTable.resolve(it.asString) }
		val data = json.getAsJsonArray("data").map { element ->
			if (element.isJsonNull) null else element.asString
		}

		val nbt = mutableMapOf<Int, String>()
		if (json.has("nbt") && json.get("nbt").isJsonObject) {
			for ((key, value) in json.getAsJsonObject("nbt").entrySet()) {
				val index = key.toIntOrNull() ?: continue
				if (!value.isJsonNull) nbt[index] = value.asString
			}
		}

		return BuildData(
			sizeX = size[0].asInt,
			sizeY = size[1].asInt,
			sizeZ = size[2].asInt,
			uploadDirection = json.get("direction").asString,
			blocks = blocks,
			data = data,
			nbt = nbt,
		)
	}

	/**
	 * Writes a build.
	 *
	 * [blocks] holds either an Integer id from [BlockTable] or a namespaced name string;
	 * the mixed-array shape is kept because it is what the backend stores.
	 */
	fun toJson(
		blocks: List<Any>,
		data: List<String?>,
		size: List<Int>,
		direction: String,
		nbt: Map<Int, String>,
	): JsonObject = JsonObject().apply {
		add("blocks", blocks.toJsonArray())
		add("data", data.toJsonArray())
		add("size", size.toJsonArray())
		addProperty("direction", direction)
		add("nbt", JsonObject().apply {
			nbt.toSortedMap().forEach { (index, value) -> addProperty(index.toString(), value) }
		})
	}

	private fun List<*>.toJsonArray() = JsonArray().also { array ->
		for (element in this) when (element) {
			null -> array.add(JsonNull.INSTANCE)
			is Number -> array.add(element)
			else -> array.add(element.toString())
		}
	}
}
