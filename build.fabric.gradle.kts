plugins {
	id("org.jetbrains.kotlin.jvm") version "2.4.0"
	// Since Minecraft 26.1 the game is unobfuscated: use the non-remapping loom variant
	id("net.fabricmc.fabric-loom") version "1.17-SNAPSHOT"
}

val javaVersion = JavaVersion.VERSION_25
val fabricApiVersion: String = sc.properties["deps.fabric_api"]
val mcVersionRangeForFabric: String = sc.properties["mod.mc_compat"]

val modId: String = property("mod.id").toString()
val modName: String = property("mod.name").toString()

group = property("mod.group").toString()
version = "${property("mod.version")}+${sc.current.version}"

base {
	archivesName = "$modId-fabric"
}

dependencies {
	minecraft("com.mojang:minecraft:${sc.current.version}")
	implementation("net.fabricmc:fabric-loader:${property("deps.fabric_loader")}")
	implementation("net.fabricmc.fabric-api:fabric-api:$fabricApiVersion")
	implementation("net.fabricmc:fabric-language-kotlin:${property("deps.fabric_kotlin")}")

	testImplementation(kotlin("test"))
}

tasks {
	processResources {
		inputs.property("java", javaVersion.majorVersion)
		inputs.property("minecraftVersionRange", mcVersionRangeForFabric)
		inputs.property("version", project.version)
		inputs.property("name", modName)

		filesMatching("fabric.mod.json") {
			expand(mapOf(
				"java" to inputs.properties["java"],
				"minecraftVersionRange" to inputs.properties["minecraftVersionRange"],
				"version" to inputs.properties["version"],
				"name" to inputs.properties["name"],
			))
		}

		from(rootProject.file("icon.png")) {
			into("assets/$modId")
		}

		exclude("META-INF/neoforge.mods.toml")
	}

	test {
		useJUnitPlatform()
	}

	jar {
		inputs.property("archivesName", project.base.archivesName)

		from(rootProject.file("LICENSE")) {
			rename { "${it}_${inputs.properties["archivesName"]}" }
		}
	}
}

tasks.withType<JavaCompile>().configureEach {
	options.release.set(javaVersion.majorVersion.toInt())
}

tasks.withType<org.jetbrains.kotlin.gradle.tasks.KotlinCompile>().configureEach {
	compilerOptions {
		jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.fromTarget(javaVersion.majorVersion)
	}
}

java {
	sourceCompatibility = javaVersion
	targetCompatibility = javaVersion
}

loom {
	runConfigs.all {
		generateRunConfig = true // Run configurations are not created for subprojects by default
		runDirectory = rootProject.file("run") // Use a shared run folder and create separate worlds
	}
}

// A development-only client game test that pastes a local build into a fresh world, reads
// it back and photographs it. It never ships: the source set is not part of the jar.
// Driven by tools/building (`python -m building review ...`), see that README.
fabricApi {
	configureTests {
		createSourceSet = true
		modId = "$modId-review"
		enableGameTests = false
		enableClientGameTests = true
		eula = true
		clearRunDirectory = true
	}
}

tasks.matching { it.name == "runClientGameTest" }.configureEach {
	(this as JavaExec).systemProperty(
		"buildpaste.review.spec",
		rootProject.file("build/review/spec.json").absolutePath,
	)
}
