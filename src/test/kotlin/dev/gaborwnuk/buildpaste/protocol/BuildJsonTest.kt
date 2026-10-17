package dev.gaborwnuk.buildpaste.protocol

import kotlin.test.Test
import kotlin.test.assertEquals

class BuildJsonTest {

	@Test
	fun `a written build parses back unchanged`() {
		val json = BuildJson.toJson(
			blocks = listOf(1, "minecraft:oak_stairs", "minecraft:air"),
			data = listOf(null, "[facing=east,half=bottom]", null),
			size = listOf(1, 1, 3),
			direction = "north",
			nbt = mapOf(1 to "{foo:1b}"),
		)

		val build = BuildJson.parse(json.toString())

		assertEquals(1, build.sizeX)
		assertEquals(3, build.sizeZ)
		assertEquals("north", build.uploadDirection)
		assertEquals(BlockTable.resolve("1"), build.blocks[0])
		assertEquals("minecraft:oak_stairs", build.blocks[1])
		assertEquals(listOf(null, "[facing=east,half=bottom]", null), build.data)
		assertEquals(mapOf(1 to "{foo:1b}"), build.nbt)
	}
}
