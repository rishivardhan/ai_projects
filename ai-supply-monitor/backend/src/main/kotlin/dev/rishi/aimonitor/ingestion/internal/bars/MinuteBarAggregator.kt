package dev.rishi.aimonitor.ingestion.internal.bars

import dev.rishi.aimonitor.ingestion.api.PriceBar
import dev.rishi.aimonitor.reference.api.DelayClass
import dev.rishi.aimonitor.reference.api.ListingId
import dev.rishi.aimonitor.reference.api.SourceId
import java.math.BigDecimal
import java.time.Instant
import java.time.temporal.ChronoUnit

/** A single executed trade, already mapped to a tracked listing. */
data class Trade(
    val listing: ListingId,
    val price: BigDecimal,
    val quantity: BigDecimal,
    val tradedAt: Instant,
)

/** Folds trades into 1-minute OHLCV bars keyed on (listing, minute start in UTC). */
object MinuteBarAggregator {
    fun aggregate(
        trades: List<Trade>,
        source: SourceId,
        delay: DelayClass,
        receivedAt: Instant,
    ): List<PriceBar> =
        trades
            .groupBy { it.listing to it.tradedAt.truncatedTo(ChronoUnit.MINUTES) }
            .map { (key, group) ->
                val ordered = group.sortedBy { it.tradedAt }
                PriceBar(
                    listing = key.first,
                    barStart = key.second,
                    open = ordered.first().price,
                    high = ordered.maxOf { it.price },
                    low = ordered.minOf { it.price },
                    close = ordered.last().price,
                    volume = ordered.fold(BigDecimal.ZERO) { acc, t -> acc + t.quantity },
                    tradeCount = ordered.size,
                    firstTradeAt = ordered.first().tradedAt,
                    lastTradeAt = ordered.last().tradedAt,
                    receivedAt = receivedAt,
                    source = source,
                    delay = delay,
                )
            }.sortedWith(compareBy({ it.listing.value }, { it.barStart }))
}
