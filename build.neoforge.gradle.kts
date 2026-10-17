plugins {
	id("org.jetbrains.kotlin.jvm") version "2.4.0"
	id("net.neoforged.moddev") version "2.0.140"
}

val javaVersion = JavaVersion.VERSION_25
val mcVersionRangeForNeoForge: String = sc.properties["mod.mc_compat"]

val modId: String = property("mod.id").toString()
val modName: String = property("mod.name").toString()

group = property("mod.group").toString()
version = "${property("mod.version")}+${sc.current.version}"

base {
	archivesName = "$modId-neoforge"
}

repositories {
	maven("https://thedarkcolour.github.io/KotlinForForge/") { name = "KotlinForForge" }
	mavenCentral()
}

dependencies {
	implementation("thedarkcolour:kotlinforforge-neoforge:${property("deps.kotlin_forge")}")

	testImplementation(kotlin("test"))
	// The game ships Gson at runtime, but NeoForge leaves it off the unit-test classpath.
	testImplementation("com.google.code.gson:gson:2.13.2")
}

neoForge {
	version = sc.properties["deps.neo_loader"]

	mods {
		register("buildpaste") {
			sourceSet(sourceSets.main.get())
		}
	}

	runs {
		register("client") {
			client()
			gameDirectory = rootProject.file("run")
		}
		register("server") {
			server()
			gameDirectory = rootProject.file("run")
		}
	}
}

tasks {
	processResources {
		inputs.property("minecraftVersionRange", mcVersionRangeForNeoForge)
		inputs.property("version", project.version)
		inputs.property("name", modName)

		filesMatching("META-INF/neoforge.mods.toml") {
			expand(mapOf(
				"minecraftVersionRange" to inputs.properties["minecraftVersionRange"],
				"version" to inputs.properties["version"],
				"name" to inputs.properties["name"],
			))
		}

		from(rootProject.file("icon.png")) {
			into("assets/$modId")
		}

		exclude("fabric.mod.json")
	}

	named("createMinecraftArtifacts") {
		dependsOn("stonecutterGenerate")
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

	toolchain {
		languageVersion = JavaLanguageVersion.of(javaVersion.majorVersion)
	}
}
