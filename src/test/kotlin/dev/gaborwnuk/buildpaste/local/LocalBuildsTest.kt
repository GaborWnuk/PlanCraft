package dev.gaborwnuk.buildpaste.local

import java.nio.file.Files
import kotlin.test.Test
import kotlin.test.assertEquals
import kotlin.test.assertFalse
import kotlin.test.assertNull
import kotlin.test.assertTrue

class LocalBuildsTest {

	@Test
	fun `plain names are accepted`() {
		for (name in listOf("house", "warsaw-tower_v2", "a.b", "0")) {
			assertTrue(LocalBuilds.isValidName(name), name)
		}
	}

	@Test
	fun `names that could leave the folder are rejected`() {
		for (name in listOf("", "..", "../x", "a/b", "a\\b", ".hidden", "a..b", "C:x", "x y", "a".repeat(65))) {
			assertFalse(LocalBuilds.isValidName(name), name)
		}
	}

	@Test
	fun `files round trip inside the builds folder`() {
		val root = Files.createTempDirectory("buildpaste-test")
		val builds = LocalBuilds(root)

		assertNull(builds.read("missing"))
		assertNull(builds.fileFor("../escape"))

		val file = builds.write("house", "{}")
		assertEquals(builds.directory, file.parent)
		assertEquals("{}", builds.read("house"))
		assertEquals(listOf("house"), builds.list())
	}
}
