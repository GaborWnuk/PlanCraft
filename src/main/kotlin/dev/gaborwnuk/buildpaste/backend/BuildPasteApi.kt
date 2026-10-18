package dev.gaborwnuk.buildpaste.backend

import com.google.gson.JsonParser
import dev.gaborwnuk.buildpaste.BuildPasteLog
import dev.gaborwnuk.buildpaste.protocol.ApiResult
import dev.gaborwnuk.buildpaste.protocol.BuildData
import dev.gaborwnuk.buildpaste.protocol.BuildJson
import java.net.URI
import java.net.URLEncoder
import java.net.http.HttpClient
import java.net.http.HttpRequest
import java.net.http.HttpResponse
import java.nio.charset.StandardCharsets
import java.time.Duration
import java.util.concurrent.CompletableFuture

/**
 * Client for the buildpaste.net backend.
 *
 * Every call is asynchronous. The Bukkit plugin this was ported from made these requests
 * synchronously from the command handler, which stalls the server for the length of the
 * round trip; here the caller receives a [CompletableFuture] and is expected to resume on
 * the server thread via `thenAcceptAsync(action, server)`.
 */
object BuildPasteApi {

	private const val FUNCTIONS_ROOT = "https://us-central1-buildpastemod.cloudfunctions.net/v1"

	/** The site itself, used for the links sent to players in chat. */
	const val SITE_ROOT = "https://buildpaste.net"

	// The upload endpoint answers 201 Created, so every 2xx counts as success.
	private val SUCCESS = 200..299

	private val client: HttpClient = HttpClient.newBuilder()
		.connectTimeout(Duration.ofSeconds(10))
		.followRedirects(HttpClient.Redirect.NORMAL)
		.build()

	private fun get(url: String): CompletableFuture<HttpResponse<String>> {
		val request = HttpRequest.newBuilder(URI.create(url))
			.timeout(Duration.ofSeconds(30))
			.header("Accept", "application/json")
			.GET()
			.build()
		return client.sendAsync(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8))
	}

	private fun encode(segment: String): String =
		URLEncoder.encode(segment, StandardCharsets.UTF_8).replace("+", "%20")

	private fun <T> failure(error: Throwable): ApiResult<T> =
		ApiResult.Failed(error.message ?: error.javaClass.simpleName)

	/**
	 * Downloads a build.
	 *
	 * Block ids arrive either as numbers indexing [BlockTable] or as namespaced names for
	 * blocks the table does not cover; both are resolved to names here.
	 */
	fun fetchBuild(buildId: String): CompletableFuture<ApiResult<BuildData>> =
		get("$FUNCTIONS_ROOT/builds/get/${encode(buildId)}").handle { response, error ->
			when {
				error != null -> failure(error)
				response.statusCode() == 404 -> ApiResult.NotFound
				response.statusCode() !in SUCCESS -> ApiResult.Failed("HTTP ${response.statusCode()}")
				else -> runCatching { ApiResult.Success(BuildJson.parse(response.body())) }
					.getOrElse { ApiResult.Failed("malformed build data: ${it.message}") }
			}
		}

	/**
	 * Uploads a build and returns the id the backend assigns it.
	 *
	 * [blocks] holds either an Integer id from [BlockTable] or a namespaced name string;
	 * the request body keeps that mixed-array shape because it is what the backend stores.
	 */
	fun uploadBuild(
		uuid: String,
		blocks: List<Any>,
		data: List<String?>,
		size: List<Int>,
		lookDirection: String,
		buildName: String,
		nbt: Map<Int, String>,
	): CompletableFuture<ApiResult<String>> {
		val payload = BuildJson.toJson(blocks, data, size, lookDirection, nbt).apply {
			addProperty("uuid", uuid)
		}

		val suffix = if (buildName.isEmpty()) "" else encode(buildName)
		val request = HttpRequest.newBuilder(URI.create("$FUNCTIONS_ROOT/builds/pluginaddbuild/$suffix"))
			.timeout(Duration.ofMinutes(2))
			// The backend expects this content type rather than application/json; it is what
			// the original plugin sent and what the endpoint accepts.
			.header("Content-Type", "application/POST")
			.header("Accept", "application/json")
			.POST(HttpRequest.BodyPublishers.ofString(payload.toString(), StandardCharsets.UTF_8))
			.build()

		return client.sendAsync(request, HttpResponse.BodyHandlers.ofString(StandardCharsets.UTF_8))
			.handle { response, error ->
				when {
					error != null -> failure(error)
					response.statusCode() !in SUCCESS -> ApiResult.Failed("HTTP ${response.statusCode()}")
					else -> {
						val id = uploadedId(response.body())
						if (id.isEmpty() || id == "-") ApiResult.Failed("backend rejected the upload")
						else ApiResult.Success(id)
					}
				}
			}
	}

	/** The build id from an upload response: a bare or quoted string, or an object with an id. */
	internal fun uploadedId(body: String): String {
		val text = body.trim()
		if (text.startsWith("{")) {
			val json = runCatching { JsonParser.parseString(text).asJsonObject }.getOrNull() ?: return ""
			for (key in listOf("id", "buildId", "build_id", "build")) {
				val value = json.get(key)
				if (value != null && value.isJsonPrimitive) return value.asString.trim()
			}
			return ""
		}
		return text.removeSurrounding("\"")
	}

	/** The display name of a build, used to label paste paper. */
	fun fetchBuildName(buildId: String): CompletableFuture<ApiResult<String>> =
		get("$FUNCTIONS_ROOT/_api/build/${encode(buildId)}").handle { response, error ->
			when {
				error != null -> failure(error)
				response.statusCode() == 404 -> ApiResult.NotFound
				response.statusCode() !in SUCCESS -> ApiResult.Failed("HTTP ${response.statusCode()}")
				else -> runCatching {
					ApiResult.Success(JsonParser.parseString(response.body()).asJsonObject.get("name").asString)
				}.getOrElse { ApiResult.Failed("malformed response") }
			}
		}

	/** Links a Minecraft account to a buildpaste.net account, optionally by email address. */
	fun connectAccounts(mcName: String, uuid: String, email: String? = null): CompletableFuture<ApiResult<Unit>> {
		val url = buildString {
			append(FUNCTIONS_ROOT).append("/users/verify/")
			append(encode(mcName)).append('/').append(encode(uuid))
			if (email != null) append('/').append(encode(email))
		}
		return get(url).handle { response, error ->
			when {
				error != null -> failure(error)
				response.statusCode() in SUCCESS -> ApiResult.Success(Unit)
				response.statusCode() == 404 -> ApiResult.NotFound
				else -> ApiResult.Failed("HTTP ${response.statusCode()}")
			}
		}
	}

	/** Marks a build as the player's currently selected one, as `/setbuild` does. */
	fun setSelectedBuild(uuid: String, buildId: String): CompletableFuture<ApiResult<Unit>> =
		get("$FUNCTIONS_ROOT/users/setselectedbuild/${encode(uuid)}/${encode(buildId)}").handle { response, error ->
			when {
				error != null -> failure(error)
				response.statusCode() == 404 -> ApiResult.NotFound
				response.statusCode() in SUCCESS -> ApiResult.Success(Unit)
				else -> ApiResult.Failed("HTTP ${response.statusCode()}")
			}
		}

	/**
	 * The build the player currently has selected on the website.
	 *
	 * A 404 means the accounts are not linked yet. The original retried once after an
	 * implicit link attempt, which is preserved here.
	 */
	fun fetchSelectedBuild(mcName: String, uuid: String): CompletableFuture<ApiResult<String>> =
		fetchSelectedBuildOnce(uuid).thenCompose { result ->
			if (result !is ApiResult.NotFound) {
				CompletableFuture.completedFuture(result)
			} else {
				BuildPasteLog.debug("No linked account for {}, linking before retrying", uuid)
				connectAccounts(mcName, uuid).thenCompose { linked ->
					if (linked is ApiResult.Success) fetchSelectedBuildOnce(uuid)
					else CompletableFuture.completedFuture(ApiResult.NotFound)
				}
			}
		}

	private fun fetchSelectedBuildOnce(uuid: String): CompletableFuture<ApiResult<String>> =
		get("$FUNCTIONS_ROOT/users/build/${encode(uuid)}").handle { response, error ->
			when {
				error != null -> failure(error)
				response.statusCode() == 404 -> ApiResult.NotFound
				response.statusCode() !in SUCCESS -> ApiResult.Failed("HTTP ${response.statusCode()}")
				else -> {
					val id = response.body().trim().removeSurrounding("\"")
					if (id.isEmpty()) ApiResult.Failed("no build selected") else ApiResult.Success(id)
				}
			}
		}

}
