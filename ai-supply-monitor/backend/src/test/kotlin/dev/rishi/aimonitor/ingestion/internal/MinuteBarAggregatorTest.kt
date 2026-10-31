package dev.rishi.aimonitor.ingestion.internal

import dev.rishi.aimonitor.ingestion.internal.bars.MinuteBarAggregator
import dev.rishi.aimonitor.ingestion.internal.bars.Trade
import dev.rishi.aimonitor.reference.api.DelayClass
import dev.rishi.aimonitor.reference.api.ListingId
import dev.rishi.aimonitor.reference.api.SourceId
import org.assertj.core.api.Assertions.assertThat
import org.junit.jupiter.api.Test
import java.time.Instant

class MinuteBarAggregatorTest {
    private val sap = ListingId("DE0007164600@XETR")
    private val ifx = ListingId("DE0006231004@XETR")

    @Test
    fun `folds unordered trades into OHLCV per listing and minute`() {
        val trades =
            listOf(
                trade(sap, "231.40", "50", "08:00:41"),
                trade(sap, "231.10", "100", "08:00:05"),
                trade(sap, "230.95", "20", "08:00:20"),
                trade(sap, "231.55", "10", "08:01:02"),
                trade(ifx, "35.20", "300", "08:00:10"),
            )

        val bars = MinuteBarAggregator.aggregate(trades, SourceId("test"), DelayClass.DELAYED_15M, Instant.EPOCH)

        assertThat(bars).hasSize(3)
        val first = bars.first { it.listing == sap && it.barStart == Instant.parse("2026-10-29T08:00:00Z") }
        assertThat(first.open).isEqualByComparingTo("231.10")
        assertThat(first.high).isEqualByComparingTo("231.40")
        assertThat(first.low).isEqualByComparingTo("230.95")
        assertThat(first.close).isEqualByComparingTo("231.40")
        assertThat(first.volume).isEqualByComparingTo("170")
        assertThat(first.tradeCount).isEqualTo(3)
        assertThat(first.firstTradeAt).isEqualTo(Instant.parse("2026-10-29T08:00:05Z"))
        assertThat(first.lastTradeAt).isEqualTo(Instant.parse("2026-10-29T08:00:41Z"))
    }

    private fun trade(
        listing: ListingId,
        price: String,
        qty: String,
        time: String,
    ) = Trade(listing, price.toBigDecimal(), qty.toBigDecimal(), Instant.parse("2026-10-29T${time}Z"))
}
