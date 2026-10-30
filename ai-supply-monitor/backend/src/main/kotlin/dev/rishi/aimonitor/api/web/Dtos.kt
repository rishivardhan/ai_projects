package dev.rishi.aimonitor.api.web

import java.math.BigDecimal
import java.time.Instant

data class ListingDto(
    val id: String,
    val symbol: String,
    val companyId: String,
    val companyName: String,
    val tier: String,
    val mic: String,
    val currency: String,
    val source: String,
    val lastBar: BarDto?,
)

data class BarDto(
    val time: Instant,
    val open: BigDecimal,
    val high: BigDecimal,
    val low: BigDecimal,
    val close: BigDecimal,
    val volume: BigDecimal,
    val tradeCount: Int,
    /** Source delay by design (e.g. DELAYED_15M), shown as a badge next to the price. */
    val delay: String,
    val receivedAt: Instant,
)

data class BarSeriesDto(
    val listingId: String,
    val currency: String,
    val from: Instant,
    val to: Instant,
    val bars: List<BarDto>,
)
