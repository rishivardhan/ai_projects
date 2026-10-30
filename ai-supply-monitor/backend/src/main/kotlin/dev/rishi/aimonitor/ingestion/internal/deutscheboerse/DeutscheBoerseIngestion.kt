package dev.rishi.aimonitor.ingestion.internal.deutscheboerse

import dev.rishi.aimonitor.ingestion.api.PriceBarsIngested
import dev.rishi.aimonitor.ingestion.internal.archive.RawArchive
import dev.rishi.aimonitor.ingestion.internal.archive.RawObject
import dev.rishi.aimonitor.ingestion.internal.bars.MinuteBarAggregator
import dev.rishi.aimonitor.ingestion.internal.bars.Trade
import dev.rishi.aimonitor.reference.api.DelayClass
import dev.rishi.aimonitor.reference.api.ReferenceData
import dev.rishi.aimonitor.reference.api.SourceId
import org.slf4j.LoggerFactory
import org.springframework.context.ApplicationEventPublisher
import org.springframework.stereotype.Service
import org.springframework.transaction.support.TransactionTemplate
import java.time.Instant

/**
 * Archive -> parse -> aggregate -> publish for one Deutsche Börse post-trade file.
 *
 * The raw object is committed on its own before parsing, so a parser failure leaves the payload in the archive
 * for replay. Parsing, the status update and the event publication share one transaction, so the event is in the
 * Modulith publication registry exactly when the object is marked parsed.
 */
@Service
class DeutscheBoerseIngestion(
    private val archive: RawArchive,
    private val reference: ReferenceData,
    private val events: ApplicationEventPublisher,
    private val tx: TransactionTemplate,
) {
    private val log = LoggerFactory.getLogger(javaClass)
    private val parser = PostTradeParser()

    /** Source id for a file-service prefix, e.g. `DETR-posttrade` -> `deutsche-boerse-detr`. */
    fun sourceFor(prefix: String) = SourceId("deutsche-boerse-" + prefix.substringBefore('-').lowercase())

    fun isArchived(
        prefix: String,
        fileName: String,
    ) = archive.contains(sourceFor(prefix), fileName)

    /** Returns the number of bars published, or null if this file was ingested before. */
    fun ingest(
        prefix: String,
        mic: String,
        fileName: String,
        payload: ByteArray,
    ): Int? {
        val raw = tx.execute { archive.storeIfNew(sourceFor(prefix), fileName, payload) } ?: return null
        return try {
            tx.execute { process(raw, mic) }
        } catch (
            @Suppress("TooGenericExceptionCaught") e: Exception,
        ) {
            // Whatever broke, the object must be marked so it is visible and can be replayed after a fix.
            log.warn("Failed to parse {} from {}: {}", fileName, raw.source, e.message)
            archive.markFailed(raw.id, e.toString())
            throw e
        }
    }

    private fun process(
        raw: RawObject,
        mic: String,
    ): Int {
        val tracked = reference.listingsByIsin(mic)
        val parsed = parser.parse(raw.payload)
        val cancelled =
            parsed.records
                .filter { it.cancellation }
                .mapNotNull { it.transactionId }
                .toSet()
        val trades =
            parsed.records
                .asSequence()
                .filterNot { it.cancellation || it.transactionId in cancelled }
                .distinctBy { it.transactionId ?: it }
                .mapNotNull { r -> tracked[r.isin]?.let { Trade(it.id, r.price, r.quantity, r.tradedAt) } }
                .toList()
        val bars = MinuteBarAggregator.aggregate(trades, raw.source, DelayClass.DELAYED_15M, receivedAt = Instant.now())
        if (bars.isNotEmpty()) {
            events.publishEvent(PriceBarsIngested(batchId = "${raw.source}/${raw.objectName}", source = raw.source, bars = bars))
        }
        archive.markParsed(raw.id, bars.size)
        log.info(
            "Ingested {}: {} records, {} skipped, {} cancellations, {} tracked trades -> {} bars",
            raw.objectName,
            parsed.records.size,
            parsed.skipped,
            cancelled.size,
            trades.size,
            bars.size,
        )
        return bars.size
    }
}
