package dev.rishi.aimonitor.ingestion.internal.deutscheboerse

import dev.rishi.aimonitor.ingestion.internal.calendar.SessionCalendar
import org.slf4j.LoggerFactory
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty
import org.springframework.scheduling.annotation.Scheduled
import org.springframework.stereotype.Component
import java.time.Clock

/**
 * Polls the file service once per interval, but only while the venue behind a feed is in session
 * (plus a trailing window for the delayed tail), so nothing polls a closed venue.
 */
@Component
@ConditionalOnProperty("aimonitor.ingestion.deutsche-boerse.enabled", havingValue = "true")
class DeutscheBoersePoller(
    private val properties: DeutscheBoerseProperties,
    private val client: DeutscheBoerseClient,
    private val ingestion: DeutscheBoerseIngestion,
    private val calendar: SessionCalendar,
    private val clock: Clock,
) {
    private val log = LoggerFactory.getLogger(javaClass)

    @Scheduled(fixedDelayString = "\${aimonitor.ingestion.deutsche-boerse.poll-interval:PT1M}")
    fun poll() {
        val now = clock.instant()
        properties.feeds
            .filter { (_, mic) -> calendar.isWithin(mic, now, properties.trailingAfterClose) }
            .forEach { (prefix, mic) ->
                runCatching { pollFeed(prefix, mic) }
                    .onFailure { log.warn("Polling {} failed: {}", prefix, it.message) }
            }
    }

    private fun pollFeed(
        prefix: String,
        mic: String,
    ) {
        client
            .listFiles(prefix)
            .filterNot { ingestion.isArchived(prefix, it) }
            .forEach { file -> ingestion.ingest(prefix, mic, file, client.download(file)) }
    }
}
