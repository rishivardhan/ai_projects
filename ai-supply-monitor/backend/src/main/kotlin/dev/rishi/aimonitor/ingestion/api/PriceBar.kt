package dev.rishi.aimonitor.ingestion.api

import dev.rishi.aimonitor.reference.api.DelayClass
import dev.rishi.aimonitor.reference.api.ListingId
import dev.rishi.aimonitor.reference.api.SourceId
import java.math.BigDecimal
import java.time.Instant

/**
 * One-minute OHLCV bar as normalised by an ingestion adapter.
 *
 * [firstTradeAt]/[lastTradeAt] are venue timestamps of the trades that formed the bar, so two partial bars
 * for the same minute (from two source files) can be merged into one without losing open or close.
 */
data class PriceBar(
    val listing: ListingId,
    val barStart: Instant,
    val open: BigDecimal,
    val high: BigDecimal,
    val low: BigDecimal,
    val close: BigDecimal,
    val volume: BigDecimal,
    val tradeCount: Int,
    val firstTradeAt: Instant,
    val lastTradeAt: Instant,
    val receivedAt: Instant,
    val source: SourceId,
    val delay: DelayClass,
)

/**
 * Published once per raw source object after it was archived and parsed.
 * [batchId] is unique per raw object, so consumers can apply a batch at most once.
 */
data class PriceBarsIngested(
    val batchId: String,
    val source: SourceId,
    val bars: List<PriceBar>,
)
