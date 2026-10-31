package dev.rishi.aimonitor.ingestion.internal.deutscheboerse

import org.slf4j.LoggerFactory
import org.springframework.beans.factory.annotation.Value
import org.springframework.boot.ApplicationArguments
import org.springframework.boot.ApplicationRunner
import org.springframework.stereotype.Component
import java.nio.file.Files
import java.nio.file.Path
import kotlin.io.path.isDirectory
import kotlin.io.path.listDirectoryEntries
import kotlin.io.path.name
import kotlin.io.path.readBytes

/**
 * Imports post-trade files from a local directory at startup (`aimonitor.ingestion.import-dir`).
 * Used to load a day downloaded by hand, or archived elsewhere, through exactly the same path as live polling.
 * Files go through the raw archive, so importing the same directory twice is harmless.
 */
@Component
class LocalFileImporter(
    private val properties: DeutscheBoerseProperties,
    private val ingestion: DeutscheBoerseIngestion,
    @param:Value("\${aimonitor.ingestion.import-dir:}") private val importDir: String,
) : ApplicationRunner {
    private val log = LoggerFactory.getLogger(javaClass)

    override fun run(args: ApplicationArguments) {
        if (importDir.isBlank()) return
        val dir = Path.of(importDir)
        require(dir.isDirectory()) { "aimonitor.ingestion.import-dir is not a directory: $dir" }
        dir
            .listDirectoryEntries("*.json*")
            .filter(Files::isRegularFile)
            .sortedBy { it.name }
            .forEach(::import)
    }

    private fun import(file: Path) {
        val (prefix, mic) =
            properties.feeds.entries
                .firstOrNull { file.name.startsWith(it.key + "-") }
                ?.toPair()
                ?: return log.warn("Skipping {}: no configured feed prefix matches", file.name)
        val bars = ingestion.ingest(prefix, mic, file.name, file.readBytes())
        log.info("Imported {}: {}", file.name, bars?.let { "$it bars" } ?: "already archived")
    }
}
