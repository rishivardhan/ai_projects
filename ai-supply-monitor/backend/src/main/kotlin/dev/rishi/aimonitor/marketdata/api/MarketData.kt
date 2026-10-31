package dev.rishi.aimonitor.marketdata.api

import dev.rishi.aimonitor.reference.api.DelayClass
import dev.rishi.aimonitor.reference.api.ListingId
import dev.rishi.aimonitor.reference.api.SourceId
import java.math.BigDecimal
import java.time.Instant

/** A stored 1-minute bar, in the listing's own currency. */
data class Bar(
    val listing: ListingId,
    val barStart: Instant,
    val open: BigDecimal,
    val high: BigDecimal,
    val low: BigDecimal,
    val close: BigDecimal,
    val volume: BigDecimal,
    val tradeCount: Int,
    val source: SourceId,
    val delay: DelayClass,
    val receivedAt: Instant,
)

/** Published after a batch of bars was written. Carries keys, not prices; consumers query what they need. */
data class PriceBarsStored(
    val batchId: String,
    val listings: Set<ListingId>,
    val earliestBarStart: Instant,
    val latestBarStart: Instant,
)

interface MarketDataQueries {
    /** Bars with `from <= barStart < to`, oldest first. */
    fun bars(
        listing: ListingId,
        from: Instant,
        to: Instant,
    ): List<Bar>

    /** Most recent bar per listing, for the board view and staleness badges. */
    fun latestBars(): Map<ListingId, Bar>
}
