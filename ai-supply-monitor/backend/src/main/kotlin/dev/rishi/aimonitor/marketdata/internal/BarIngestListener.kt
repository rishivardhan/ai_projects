package dev.rishi.aimonitor.marketdata.internal

import dev.rishi.aimonitor.ingestion.api.PriceBarsIngested
import dev.rishi.aimonitor.marketdata.api.PriceBarsStored
import org.slf4j.LoggerFactory
import org.springframework.context.ApplicationEventPublisher
import org.springframework.modulith.events.ApplicationModuleListener
import org.springframework.stereotype.Component

@Component
class BarIngestListener(
    private val bars: BarRepository,
    private val events: ApplicationEventPublisher,
) {
    private val log = LoggerFactory.getLogger(javaClass)

    @ApplicationModuleListener
    fun on(event: PriceBarsIngested) {
        if (event.bars.isEmpty()) return
        if (!bars.claimBatch(event.batchId)) {
            log.info("Batch {} was already applied, skipping", event.batchId)
            return
        }
        event.bars.forEach(bars::upsert)
        events.publishEvent(
            PriceBarsStored(
                batchId = event.batchId,
                listings = event.bars.map { it.listing }.toSet(),
                earliestBarStart = event.bars.minOf { it.barStart },
                latestBarStart = event.bars.maxOf { it.barStart },
            ),
        )
    }
}
