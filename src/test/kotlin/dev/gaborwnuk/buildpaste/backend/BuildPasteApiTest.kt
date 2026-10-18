package dev.gaborwnuk.buildpaste.backend

import kotlin.test.Test
import kotlin.test.assertEquals

class BuildPasteApiTest {

	@Test
	fun `upload ids are read from bare, quoted and object bodies`() {
		assertEquals("abc123", BuildPasteApi.uploadedId("abc123\n"))
		assertEquals("abc123", BuildPasteApi.uploadedId("\"abc123\""))
		assertEquals("abc123", BuildPasteApi.uploadedId("{\"id\":\"abc123\"}"))
		assertEquals("abc123", BuildPasteApi.uploadedId("{\"buildId\":\"abc123\"}"))
		assertEquals("", BuildPasteApi.uploadedId("{\"error\":{}}"))
	}
}
